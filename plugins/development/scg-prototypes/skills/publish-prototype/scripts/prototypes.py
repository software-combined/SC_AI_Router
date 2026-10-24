#!/usr/bin/env python3
"""Publish, list and unpublish Software Combined frontend prototypes.

The configured channel stores each artifact privately and serves it at
https://prototypes.softwarecombined.com/<slug>/. Publishing copies the artifact
into the configured archive first, then uploads that copy and refreshes the
slug's public path.

Only the standard library is used; AWS and git work is delegated to their CLIs.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_DIR / "references" / "channel.json"
GITLEAKS_PIN_PATH = Path.home() / ".config" / "scg-agent-git-hooks" / "config.json"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
SKIP_DIRECTORIES = {".git", "node_modules", ".DS_Store", "__pycache__"}
SKIP_FILE_NAMES = {".DS_Store"}
SKIP_FILE_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "*.p12")
SCANNABLE_SUFFIXES = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg")
REFERENCE_PATTERN = re.compile(
    r"""(?:src|href|poster|action)\s*=\s*["'](/[^"']*)["']"""
    r"""|srcset\s*=\s*["']([^"']*)["']"""
    r"""|url\(\s*["']?(/[^"')\s]*)"""
    r"""|@import\s+["'](/[^"']+)["']""",
    re.IGNORECASE,
)


class ChannelError(RuntimeError):
    """A publish, unpublish or configuration failure the operator must fix."""


def load_config(path=None) -> dict:
    config_path = Path(path or os.environ.get("PROTOTYPE_CHANNEL_CONFIG") or DEFAULT_CONFIG_PATH)
    try:
        config = json.loads(config_path.read_text())
    except FileNotFoundError as error:
        raise ChannelError(f"channel config not found: {config_path}") from error
    except json.JSONDecodeError as error:
        raise ChannelError(f"channel config is not valid JSON: {config_path}: {error}") from error
    required = ("account", "bucket", "distributionId", "domain", "profile", "archiveRepository", "expiryDays")
    for key in required:
        if key not in config:
            raise ChannelError(f"channel config is missing {key}: {config_path}")
    if any(not isinstance(config[key], str) or not config[key].strip() for key in required[:-1]):
        raise ChannelError(
            "the prototype channel is not configured; select a complete private config "
            "with --config or PROTOTYPE_CHANNEL_CONFIG",
        )
    return config


def resolve_repo_dir(config: dict, override=None) -> Path:
    configured = override or os.environ.get("PROTOTYPE_CHANNEL_REPO_DIR")
    return Path(configured).expanduser() if configured else Path.home() / "Documents" / "Github" / "prototype-archive"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:34].strip("-") or "prototype"


def make_slug(directory: Path, requested=None) -> str:
    if requested:
        validate_slug(requested)
        return requested
    suffix = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(4))
    slug = f"{slugify(directory.name)}-{suffix}"
    validate_slug(slug)
    return slug


def validate_slug(slug: str) -> None:
    if not SLUG_PATTERN.match(slug):
        raise ChannelError(
            f"invalid slug {slug!r}: use 3-40 lowercase letters, digits and hyphens, "
            "starting and ending with a letter or digit",
        )


def should_skip(path: Path) -> bool:
    if path.name in SKIP_FILE_NAMES or any(part in SKIP_DIRECTORIES for part in path.parts):
        return True
    return any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in SKIP_FILE_PATTERNS)


def ignore_publish_paths(_directory, names):
    return [name for name in names if should_skip(Path(name))]


def find_root_absolute_refs(root: Path, slug: str) -> list[str]:
    """Return file:line references that would break under the /<slug>/ prefix."""
    allowed = {f"/{slug}", f"/{slug}/"}
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or should_skip(relative) or path.suffix.lower() not in SCANNABLE_SUFFIXES:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in REFERENCE_PATTERN.finditer(line):
                if match.group(1):
                    candidates = [match.group(1)]
                elif match.group(2):
                    candidates = [part.strip().split(" ")[0] for part in match.group(2).split(",")]
                else:
                    candidates = [match.group(3) or match.group(4) or ""]
                for reference in (candidate for candidate in candidates if candidate.startswith("/")):
                    if reference.startswith("//") or reference.startswith("/" + slug + "/") or reference in allowed:
                        continue
                    findings.append(f"{relative}:{number}: {reference}")
    return findings


def find_symlinks(root: Path) -> list[str]:
    """Symlinks are refused: copying one would publish content from outside root."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_symlink())


def load_registry(repo_dir: Path) -> dict:
    registry_file = repo_dir / "prototypes.json"
    if not registry_file.exists():
        return {"prototypes": {}}
    registry = json.loads(registry_file.read_text())
    registry.setdefault("prototypes", {})
    return registry


def save_registry(repo_dir: Path, registry: dict) -> None:
    registry_file = repo_dir / "prototypes.json"
    registry_file.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")


def entry_for(slug: str, title: str, config: dict, published_at: datetime, author: str) -> dict:
    expiry = published_at + timedelta(days=int(config["expiryDays"]))
    return {
        "expiresAt": expiry.isoformat(timespec="seconds"),
        "publishedAt": published_at.isoformat(timespec="seconds"),
        "publishedBy": author,
        "source": f"prototypes/{slug}",
        "title": title,
        "url": public_url(config, slug),
    }


def public_url(config: dict, slug: str) -> str:
    return f"https://{config['domain']}/{slug}/"


def run_command(args, cwd=None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ChannelError(f"command failed ({' '.join(args)}): {detail}")
    return result.stdout


def git(repo_dir: Path, *args, run=run_command) -> str:
    return run(["git", "-C", str(repo_dir), *args])


def aws(config: dict, args, run=run_command) -> str:
    profile = os.environ.get("PROTOTYPE_CHANNEL_PROFILE") or config["profile"]
    return run(["aws", *args, "--profile", profile, "--output", "json"])


def assert_account(config: dict, run=run_command) -> None:
    identity = json.loads(aws(config, ["sts", "get-caller-identity"], run=run) or "{}")
    if str(identity.get("Account")) != str(config["account"]):
        raise ChannelError("the selected AWS profile does not match the configured account")


def load_gitleaks_pin():
    """Return the SCG review hook's gitleaks pin, or None when it is not installed."""
    try:
        config = json.loads(GITLEAKS_PIN_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    gitleaks = config.get("gitleaks") or {}
    if gitleaks.get("binary") and gitleaks.get("sha256"):
        return gitleaks["binary"], gitleaks["sha256"]
    return None


def gitleaks_binary() -> str:
    """Resolve the scanner from the SCG review hook's verified pin."""
    if os.environ.get("GITLEAKS_CONFIG") or os.environ.get("GITLEAKS_CONFIG_TOML"):
        raise ChannelError(
            "GITLEAKS_CONFIG and GITLEAKS_CONFIG_TOML must be unset: a publish always scans "
            "with the pinned default rules, and an environment config could allowlist a finding",
        )
    pin = load_gitleaks_pin()
    if not pin:
        raise ChannelError(
            f"no gitleaks pin found at {GITLEAKS_PIN_PATH}: install the SCG review plugin and run its "
            "review-setup skill (which verifies the scanner) before publishing",
        )
    binary, digest = pin
    path = Path(binary)
    if not path.is_file():
        raise ChannelError(f"the pinned gitleaks binary is missing: {binary}; run the SCG review setup")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise ChannelError(f"the gitleaks binary does not match its recorded SHA-256: {binary}")
    return str(path)


def gitleaks_scan(root: Path, run=run_command) -> None:
    for forbidden in (".gitleaks.toml", ".gitleaksignore"):
        if (root / forbidden).exists():
            raise ChannelError(f"remove {forbidden} from the prototype: publishing scans with the pinned default rules only")
    try:
        run([gitleaks_binary(), "detect", "--no-git", "--redact", "--exit-code", "1", "--source", str(root)])
    except ChannelError as error:
        raise ChannelError(f"gitleaks found a potential secret; nothing was published: {error}") from error


@contextlib.contextmanager
def channel_lock(repo_dir: Path):
    """Serialise publishes and unpublishes so the shared registry cannot lose entries."""
    lock_path = repo_dir / ".git" / "prototype-publish.lock"
    if not lock_path.parent.is_dir():
        raise ChannelError(f"not a prototype archive clone: {repo_dir}; clone {repo_dir.name} before publishing")
    with open(lock_path, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ChannelError("another publish or unpublish is already running on this machine") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_archive_repo(repo_dir: Path, config: dict, run=run_command) -> None:
    if (repo_dir / ".git").is_dir():
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", f"https://github.com/{config['archiveRepository']}.git", str(repo_dir)])


def sync_commands(config: dict, slug: str, source: Path, run=run_command) -> None:
    prefix = f"s3://{config['bucket']}/prototypes/{slug}/"
    aws(config, ["s3", "rm", "--recursive", prefix], run=run)
    aws(config, ["s3", "sync", str(source), prefix, "--exclude", "*", "--include", "*.html", "--cache-control", "no-cache"], run=run)
    aws(config, ["s3", "sync", str(source), prefix, "--exclude", "*.html", "--cache-control", "public, max-age=3600"], run=run)
    aws(config, ["cloudfront", "create-invalidation", "--distribution-id", config["distributionId"], "--paths", f"/{slug}/*"], run=run)


def verify_live(url: str, attempts: int = 6, delay: float = 10.0) -> str:
    """Return an empty string when the live URL is healthy, else a reason."""
    request = urllib.request.Request(url, headers={"User-Agent": "scg-prototypes/0.1"})
    reason = "no attempt was made"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read(4096).decode("utf-8", "replace")
                headers = {key.lower(): value for key, value in response.headers.items()}
                if response.geturl() != url:
                    reason = f"the request was redirected to {response.geturl()}"
                elif response.status != 200:
                    reason = f"HTTP {response.status}"
                elif "text/html" not in headers.get("content-type", ""):
                    reason = f"content type {headers.get('content-type')!r} is not HTML"
                elif "noindex" not in headers.get("x-robots-tag", ""):
                    reason = "the noindex response header is missing"
                else:
                    return ""
        except urllib.error.HTTPError as error:
            reason = f"HTTP {error.code}"
        except Exception as error:  # noqa: BLE001 - surface any transport failure to the operator
            reason = str(error)
        if attempt < attempts - 1:
            time.sleep(delay)
    return reason


def publish_steps(config: dict, slug: str, source_dir: Path, site_dir: Path, update: bool) -> list[str]:
    action = "update" if update else "publish"
    prefix = f"s3://{config['bucket']}/prototypes/{slug}/"
    return [
        f"copy {source_dir} -> {site_dir}",
        f"git commit prototypes/{slug} and prototypes.json, then push",
        f"aws s3 rm --recursive {prefix}",
        f"aws s3 sync {site_dir} {prefix} (HTML revalidates, assets cache for an hour)",
        f"aws cloudfront create-invalidation --distribution-id {config['distributionId']} --paths /{slug}/*",
        f"verify {public_url(config, slug)} returns 200 with the noindex header",
        f"{action} complete",
    ]


def publish(args, config: dict, run=run_command, verifier=verify_live, out=print, now=None) -> dict:
    source_dir = Path(args.directory).expanduser().resolve()
    if not source_dir.is_dir():
        raise ChannelError(f"not a directory: {source_dir}")
    if not (source_dir / "index.html").is_file():
        raise ChannelError(f"{source_dir} has no index.html; build the prototype before publishing")

    slug = make_slug(source_dir, args.slug)
    findings = find_root_absolute_refs(source_dir, slug)
    if findings:
        raise ChannelError(
            "root-absolute references would break under /" + slug + "/:\n- " + "\n- ".join(findings[:20])
            + "\nBuild with the slug as the base path, for example: npm run build -- --base=/"
            + slug + "/",
        )
    symlinks = find_symlinks(source_dir)
    if symlinks:
        raise ChannelError(
            "symbolic links are not published because they can resolve outside the prototype:\n- "
            + "\n- ".join(symlinks[:20])
            + "\nReplace them with real files or copy the target content into the prototype.",
        )
    gitleaks_scan(source_dir, run=run)

    repo_dir = resolve_repo_dir(config, args.repo_dir)
    archive_dir = repo_dir / "prototypes" / slug
    site_dir = archive_dir / "site"
    published_at = now or datetime.now(timezone.utc)
    if args.dry_run:
        out("dry run: no files were written, no clone was made and no AWS calls were made")
        out("dry run: the published-slug collision check is skipped until the archive clone exists")
        for step in publish_steps(config, slug, source_dir, site_dir, False):
            out(f"  - {step}")
        return {"slug": slug, "url": public_url(config, slug), "dryRun": True}

    ensure_archive_repo(repo_dir, config, run=run)
    with channel_lock(repo_dir):
        registry = load_registry(repo_dir)
        known = registry["prototypes"].get(slug)
        if known and not args.update:
            raise ChannelError(
                f"{slug} is already published ({known['url']}); choose another slug or pass --update to replace it",
            )
        assert_account(config, run=run)
        assert_archive_clean(repo_dir, slug, run=run)
        title = args.title or (known or {}).get("title") or slug
        registry["prototypes"][slug] = entry_for(slug, title, config, published_at, git_author(run))

        try:
            if archive_dir.exists():
                shutil.rmtree(archive_dir)
            shutil.copytree(source_dir, site_dir, ignore=ignore_publish_paths, symlinks=True)
            if args.source:
                source_snapshot = Path(args.source).expanduser().resolve()
                if not source_snapshot.is_dir():
                    raise ChannelError(f"--source is not a directory: {source_snapshot}")
                gitleaks_scan(source_snapshot, run=run)
                shutil.copytree(source_snapshot, archive_dir / "source", ignore=ignore_publish_paths, symlinks=True)

            # Re-check the bytes that actually ship: the source tree could change
            # between the checks above and this copy.
            copied_symlinks = find_symlinks(site_dir)
            copied_refs = find_root_absolute_refs(site_dir, slug)
            if copied_symlinks or copied_refs:
                raise ChannelError(
                    "the copied artifact failed the publish checks (symlinks or root-absolute paths):\n- "
                    + "\n- ".join((copied_symlinks + copied_refs)[:20]),
                )
            gitleaks_scan(site_dir, run=run)
        except ChannelError:
            shutil.rmtree(archive_dir, ignore_errors=True)
            raise

        save_registry(repo_dir, registry)
        commit_archive(repo_dir, slug, f"chore: publish prototype {slug}", run=run)

        try:
            sync_commands(config, slug, site_dir, run=run)
            reason = verifier(public_url(config, slug))
        except ChannelError:
            rollback_registry(repo_dir, slug, known, run=run, out=out)
            raise
        if reason:
            rollback_registry(repo_dir, slug, known, run=run, out=out)
            raise ChannelError(f"published and invalidated, but live verification failed: {reason}")
    out(f"Published {public_url(config, slug)} (expires {registry['prototypes'][slug]['expiresAt']})")
    return registry["prototypes"][slug]


def commit_archive(repo_dir: Path, slug: str, message: str, run=run_command) -> None:
    assert_archive_clean(repo_dir, slug, run=run)
    paths = [path for path in (f"prototypes/{slug}", "prototypes.json") if (repo_dir / path).exists()]
    git(repo_dir, "add", "--", *paths, run=run)
    if git(repo_dir, "status", "--porcelain", run=run).strip():
        git(repo_dir, "commit", "-m", message, run=run)
    git(repo_dir, "push", run=run)


def assert_archive_clean(repo_dir: Path, slug: str, run=run_command) -> None:
    """Refuse to mix unrelated work into a publish or unpublish commit."""
    allowed = {f"prototypes/{slug}", "prototypes.json"}
    dirty = [
        line for line in git(repo_dir, "status", "--porcelain", "--untracked-files=all", run=run).splitlines()
        if line[3:].strip() not in allowed and not line[3:].strip().startswith(f"prototypes/{slug}/")
    ]
    if dirty:
        raise ChannelError(
            "the archive clone has unrelated changes; commit or discard them before publishing:\n- "
            + "\n- ".join(dirty[:20]),
        )


def rollback_registry(repo_dir: Path, slug: str, known, run=run_command, out=print) -> None:
    """Keep the registry honest when a publish fails after the archive commit."""
    try:
        registry = load_registry(repo_dir)
        if known is None:
            registry["prototypes"].pop(slug, None)
        else:
            registry["prototypes"][slug] = known
        save_registry(repo_dir, registry)
        commit_archive(repo_dir, slug, f"chore: roll back prototype {slug} registry entry", run=run)
        out(
            f"the registry entry for {slug} was rolled back; the archive copy and the S3 prefix may be "
            f"out of step until the next `publish --update` succeeds",
        )
    except ChannelError as error:
        out(f"warning: could not roll back the registry entry for {slug}: {error}; run `publish --update` once the channel is healthy")


def git_author(run=run_command) -> str:
    try:
        name = run(["git", "config", "user.name"]).strip()
    except ChannelError:
        name = ""
    return name or os.environ.get("USER") or "unknown"


def unpublish(args, config: dict, run=run_command, out=print) -> None:
    repo_dir = resolve_repo_dir(config, args.repo_dir)
    validate_slug(args.slug)
    registry = load_registry(repo_dir)
    if args.slug not in registry["prototypes"]:
        raise ChannelError(f"{args.slug} is not in the {config['archiveRepository']} registry")
    if args.dry_run:
        out(f"dry run: would delete s3://{config['bucket']}/prototypes/{args.slug}/ and invalidate /{args.slug}/*")
        out(f"dry run: would keep prototypes/{args.slug} in the archive and remove its registry entry")
        return
    with channel_lock(repo_dir):
        assert_account(config, run=run)
        assert_archive_clean(repo_dir, args.slug, run=run)
        aws(config, ["s3", "rm", "--recursive", f"s3://{config['bucket']}/prototypes/{args.slug}/"], run=run)
        aws(config, ["cloudfront", "create-invalidation", "--distribution-id", config["distributionId"], "--paths", f"/{args.slug}/*"], run=run)
        del registry["prototypes"][args.slug]
        save_registry(repo_dir, registry)
        commit_archive(repo_dir, args.slug, f"chore: unpublish prototype {args.slug}", run=run)
    out(f"Unpublished {public_url(config, args.slug)}; the archived source stays at prototypes/{args.slug}")


def list_prototypes(args, config: dict, out=print, now=None) -> list[dict]:
    repo_dir = resolve_repo_dir(config, args.repo_dir)
    registry = load_registry(repo_dir)
    moment = now or datetime.now(timezone.utc)
    rows = []
    for slug, entry in sorted(registry["prototypes"].items()):
        expires_at = datetime.fromisoformat(entry["expiresAt"])
        status = "expired" if expires_at < moment else "active"
        rows.append({**entry, "slug": slug, "status": status})
    if not rows:
        out(f"no prototypes are published in {config['archiveRepository']}")
        return rows
    for row in rows:
        out(f"{row['slug']:<40} {row['status']:<8} expires {row['expiresAt'][:10]}  {row['url']}")
    return rows


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="private channel config path")
    parser.add_argument("--repo-dir", help="local archive repository clone")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish", help="publish a built static directory")
    publish_parser.add_argument("directory", help="directory containing index.html and assets")
    publish_parser.add_argument("--slug", help="exact URL slug; defaults to <directory>-<4 random characters>")
    publish_parser.add_argument("--title", help="human title shown by list")
    publish_parser.add_argument("--source", help="project directory to archive alongside the built output")
    publish_parser.add_argument("--update", action="store_true", help="replace an existing slug instead of refusing")
    publish_parser.add_argument("--dry-run", action="store_true", help="validate and print the plan only")

    subparsers.add_parser("list", help="list published prototypes")

    unpublish_parser = subparsers.add_parser("unpublish", help="delete a published slug from the channel")
    unpublish_parser.add_argument("slug")
    unpublish_parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "publish":
            publish(args, config)
        elif args.command == "list":
            list_prototypes(args, config)
        else:
            unpublish(args, config)
    except ChannelError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
