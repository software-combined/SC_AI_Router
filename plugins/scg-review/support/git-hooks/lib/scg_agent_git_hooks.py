#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


HOME = Path.home()
BASE_DIR = HOME / ".config" / "scg-agent-git-hooks"
CONFIG_PATH = BASE_DIR / "config.json"
REVIEW_ROOT = HOME / ".cache" / "scg-agent-git-hooks" / "reviews"
ALLOW_DECISIONS = {"ALL_CLEAR", "PROCEED_WITH_NOTES"}
VALID_DECISIONS = ALLOW_DECISIONS | {"BLOCK"}
STATE_VERSION = 2


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def load_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except FileNotFoundError:
        fail(f"SCG git hook config missing: {CONFIG_PATH}")
    except json.JSONDecodeError as exc:
        fail(f"SCG git hook config is invalid JSON: {CONFIG_PATH}: {exc}")


def git(args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        fail(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


def current_branch() -> str:
    branch = git(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    if branch:
        return branch
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    return branch or "HEAD"


def normalize_decision(raw: str) -> str:
    decision = raw.strip().upper().replace("-", "_").replace(" ", "_")
    if decision not in VALID_DECISIONS:
        fail(f"Invalid decision {raw!r}. Use ALL_CLEAR, PROCEED_WITH_NOTES, or BLOCK.")
    return decision


def repo_info() -> dict[str, Any]:
    root = git(["rev-parse", "--show-toplevel"])
    branch = current_branch()
    tree = git(["write-tree"])
    staged_raw = git(["diff", "--cached", "--name-only", "-z"])
    staged_files = [item for item in staged_raw.split("\0") if item]
    repo_id = hashlib.sha256(root.encode("utf-8")).hexdigest()
    return {
        "repo_root": root,
        "repo_id": repo_id,
        "branch": branch,
        "tree": tree,
        "staged_files": staged_files,
    }


def state_dir(repo_id: str) -> Path:
    return REVIEW_ROOT / repo_id


def state_path(repo_id: str, tree: str) -> Path:
    return state_dir(repo_id) / f"{tree}.review.json"


def required_lanes(config: dict[str, Any]) -> list[str]:
    lanes = config.get("required_lanes")
    if not isinstance(lanes, list) or not lanes:
        fail("SCG git hook config must define a non-empty required_lanes list.")
    normalized = [str(lane).strip() for lane in lanes]
    if any(not lane for lane in normalized) or len(set(normalized)) != len(normalized):
        fail("SCG git hook config required_lanes must contain unique, non-empty names.")
    return normalized


def parse_passes(values: list[str] | None, lanes: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            fail(f"Invalid --pass {raw!r}. Use --pass lane=model.")
        lane, model = (part.strip() for part in raw.split("=", 1))
        if not lane or not model:
            fail(f"Invalid --pass {raw!r}. Lane and model must both be non-empty.")
        if lane not in lanes:
            fail(f"Unknown review lane {lane!r}. Required lanes: {', '.join(lanes)}.")
        if lane in parsed:
            fail(f"Duplicate --pass for review lane {lane!r}.")
        parsed[lane] = model
    missing = [lane for lane in lanes if lane not in parsed]
    if missing:
        fail(f"Missing --pass for required review lane(s): {', '.join(missing)}.")
    return {lane: parsed[lane] for lane in lanes}


def write_state(args: argparse.Namespace) -> None:
    config = load_config()
    lanes = required_lanes(config)
    passes = parse_passes(args.passes, lanes)
    decision = normalize_decision(args.decision)
    info = repo_info()
    now = int(time.time())
    payload = {
        "version": STATE_VERSION,
        "created_at_epoch": now,
        "created_at_utc": dt.datetime.fromtimestamp(now, dt.UTC).isoformat(),
        "repo_root": info["repo_root"],
        "repo_id": info["repo_id"],
        "branch": info["branch"],
        "tree": info["tree"],
        "decision": decision,
        "approved": decision in ALLOW_DECISIONS,
        "passes": passes,
        "runner": (args.runner or "").strip(),
        "agent": (args.agent or "").strip(),
        "staged_files": info["staged_files"],
        "staged_file_count": len(info["staged_files"]),
        "summary": args.summary or "",
    }
    target = state_path(info["repo_id"], info["tree"])
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(target)
    print(f"Recorded {decision} review state:")
    print(f"  repo: {info['repo_root']}")
    print(f"  branch: {info['branch']}")
    print(f"  tree: {info['tree']}")
    print(f"  state: {target}")


def state_is_valid(
    state: dict[str, Any],
    info: dict[str, Any],
    config: dict[str, Any],
    ttl_seconds: int,
) -> tuple[bool, str]:
    if state.get("version") != STATE_VERSION:
        return False, f"state version {state.get('version')!r} is not supported"
    if state.get("repo_root") != info["repo_root"]:
        return False, "repo root mismatch"
    if state.get("repo_id") != info["repo_id"]:
        return False, "repo id mismatch"
    if state.get("branch") != info["branch"]:
        return False, "branch mismatch"
    if state.get("tree") != info["tree"]:
        return False, "tree mismatch"
    if state.get("decision") not in ALLOW_DECISIONS or state.get("approved") is not True:
        return False, f"decision {state.get('decision')!r} is not approved"
    try:
        created_at = int(state.get("created_at_epoch"))
    except (TypeError, ValueError):
        return False, "created_at_epoch missing or invalid"
    if int(time.time()) - created_at > ttl_seconds:
        return False, "review state expired"
    lanes = required_lanes(config)
    raw_passes = state.get("passes")
    if not isinstance(raw_passes, dict):
        return False, "passes missing or invalid"
    recorded = {str(k): str(v).strip() for k, v in raw_passes.items()}
    if set(recorded) != set(lanes):
        return False, "recorded review lanes do not match required lanes"
    if any(not recorded[lane] for lane in lanes):
        return False, "one or more recorded review models are empty"
    return True, "ok"


def load_candidate_states(info: dict[str, Any]) -> list[tuple[Path, dict[str, Any], str]]:
    path = state_path(info["repo_id"], info["tree"])
    if not path.exists():
        return []
    loaded: list[tuple[Path, dict[str, Any], str]] = []
    try:
        loaded.append((path, json.loads(path.read_text()), "loaded"))
    except json.JSONDecodeError as exc:
        loaded.append((path, {}, f"invalid JSON: {exc}"))
    return loaded


def chain_local_hook(hook_name: str, extra_args: list[str]) -> int:
    if os.environ.get("SCG_AGENT_GIT_HOOK_CHAINED") == "1":
        return 0
    common_dir = git(["rev-parse", "--git-common-dir"], check=False)
    if not common_dir:
        return 0
    hook_path = Path(common_dir) / "hooks" / hook_name
    current = Path(sys.argv[0]).resolve()
    if not hook_path.exists() or not os.access(hook_path, os.X_OK):
        return 0
    try:
        if hook_path.resolve() == current:
            return 0
    except FileNotFoundError:
        return 0
    env = dict(os.environ)
    env["SCG_AGENT_GIT_HOOK_CHAINED"] = "1"
    proc = subprocess.run([str(hook_path), *extra_args], env=env)
    return proc.returncode


def required_review_message(info: dict[str, Any], config: dict[str, Any], reasons: list[str]) -> str:
    lines = [
        "SCG pre-commit hook blocked this commit.",
        "",
        f"Repo: {info['repo_root']}",
        f"Branch: {info['branch']}",
        f"Staged tree: {info['tree']}",
        f"Staged files: {len(info['staged_files'])}",
    ]
    if reasons:
        lines.extend(["", "Rejected review state(s):", *[f"- {reason}" for reason in reasons]])
    lines.append("")
    lines.append("Run /pre-commit-review, then record the passing decision and the model chosen for every lane:")
    pass_args = " ".join(f"--pass {lane}=<model>" for lane in required_lanes(config))
    lines.append(
        "  ~/.config/scg-agent-git-hooks/bin/scg-review-state approve "
        f"--decision ALL_CLEAR {pass_args}"
    )
    return "\n".join(lines)


def pre_commit(_: argparse.Namespace) -> None:
    config = load_config()
    info = repo_info()
    required_lanes(config)
    ttl_seconds = int(config.get("review_state_ttl_seconds", 86400))
    states = load_candidate_states(info)
    reasons: list[str] = []
    for path, state, load_status in states:
        if load_status != "loaded":
            reasons.append(f"{path}: {load_status}")
            continue
        valid, reason = state_is_valid(state, info, config, ttl_seconds)
        if valid:
            chained = chain_local_hook("pre-commit", [])
            raise SystemExit(chained)
        reasons.append(f"{path.name}: {reason}")
    fail(required_review_message(info, config, reasons))


def commit_msg(args: argparse.Namespace) -> None:
    msg_path = Path(args.message_file)
    first_line = msg_path.read_text(errors="replace").splitlines()[0].strip()
    allowed_generated = (
        first_line.startswith("Merge ")
        or first_line.startswith("Revert ")
        or first_line == "Initial commit"
    )
    conventional = re.match(r"^(feat|fix|refactor|test|chore|docs): .+", first_line)
    if not (allowed_generated or conventional):
        fail(
            "SCG commit-msg hook blocked this commit.\n"
            "Use '<type>: <short summary>' with type feat, fix, refactor, test, chore, or docs."
        )
    chained = chain_local_hook("commit-msg", [args.message_file])
    raise SystemExit(chained)


def load_gitleaks_pin(config: dict[str, Any]) -> dict[str, Any]:
    pin = config.get("gitleaks")
    if not isinstance(pin, dict):
        fail("SCG git hook config must define a gitleaks pin: {binary, version, sha256}.")
    binary = str(pin.get("binary", "")).strip()
    version = str(pin.get("version", "")).strip()
    sha256 = str(pin.get("sha256", "")).strip().lower()
    if not Path(binary).is_absolute() or not version or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        fail("SCG gitleaks pin needs an absolute binary path, a version, and a 64-hex sha256.")
    return {
        "binary": Path(binary),
        "version": version,
        "sha256": sha256,
        "timeout": int(pin.get("timeout_seconds", 60)),
    }


def scan(_: argparse.Namespace) -> None:
    """Verify the pinned native gitleaks binary, then scan the exact staged tree."""
    config = load_config()
    pin = load_gitleaks_pin(config)
    info = repo_info()
    root = Path(info["repo_root"])
    problems: list[str] = []
    for var in ("GITLEAKS_CONFIG", "GITLEAKS_CONFIG_TOML"):
        if os.environ.get(var):
            problems.append(f"{var} is set; only the pinned adapter configuration is allowed")
    for name in (".gitleaks.toml", ".gitleaksignore"):
        if (root / name).exists() or name in info["staged_files"]:
            problems.append(f"repository supplies {name}; only the pinned adapter configuration is allowed")
    binary: Path = pin["binary"]
    if not binary.is_file() or not os.access(binary, os.X_OK):
        problems.append(f"pinned gitleaks binary is missing or not executable: {binary}")
    else:
        actual = hashlib.sha256(binary.read_bytes()).hexdigest()
        if actual != pin["sha256"]:
            problems.append(
                f"gitleaks binary sha256 {actual[:12]}... does not match the pinned {pin['sha256'][:12]}..."
            )
        try:
            ver = subprocess.run(
                [str(binary), "version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=pin["timeout"],
                check=False,
            )
            reported = (ver.stdout.strip().splitlines() or [""])[-1].strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            reported = f"error: {exc}"
        if reported != pin["version"]:
            problems.append(f"gitleaks reports version {reported!r}; pinned {pin['version']!r}")
    if problems:
        fail("SCG secret scan blocked (zero reviewer calls; decision BLOCK):\n" + "\n".join(f"- {p}" for p in problems))
    cmd = [
        str(binary), "git", "--staged", "--verbose",
        "--gitleaks-ignore-path", os.devnull, "--ignore-gitleaks-allow",
        "--redact=100", "--no-banner", "--no-color",
        "--timeout", str(pin["timeout"]), ".",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=pin["timeout"] + 30, check=False,
        )
    except subprocess.TimeoutExpired:
        fail("SCG secret scan blocked: gitleaks timed out (decision BLOCK).")
    if proc.returncode != 0:
        output = (proc.stdout + proc.stderr).strip()
        fail(
            "SCG secret scan blocked: gitleaks found leaks or failed (secrets redacted by --redact=100).\n"
            + output
            + "\nReport the credential type and file:line only, keep the commit blocked, and rotate the credential."
        )
    print("SCG secret scan passed.")
    print(f"  scanner: {binary} {pin['version']} (sha256 verified)")
    print(f"  staged tree: {info['tree']} ({len(info['staged_files'])} files), no leaks found")


def status(_: argparse.Namespace) -> None:
    config = load_config()
    info = repo_info()
    ttl_seconds = int(config.get("review_state_ttl_seconds", 86400))
    states = load_candidate_states(info)
    print(f"Repo: {info['repo_root']}")
    print(f"Branch: {info['branch']}")
    print(f"Staged tree: {info['tree']}")
    if not states:
        print("Review state: none")
        return
    for path, state, load_status in states:
        if load_status != "loaded":
            print(f"{path}: {load_status}")
            continue
        valid, reason = state_is_valid(state, info, config, ttl_seconds)
        print(f"{path}: {'valid' if valid else 'invalid'} ({reason})")


def main() -> None:
    parser = argparse.ArgumentParser(description="SCG agent Git hook helper")
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("pre-commit")
    pre.set_defaults(func=pre_commit)

    cm = sub.add_parser("commit-msg")
    cm.add_argument("message_file")
    cm.set_defaults(func=commit_msg)

    approve = sub.add_parser("approve")
    approve.add_argument("--decision", default="ALL_CLEAR")
    approve.add_argument("--pass", dest="passes", action="append", metavar="LANE=MODEL")
    approve.add_argument("--runner", help="Informational runner or host name")
    approve.add_argument("--agent", help="Informational main-agent name")
    approve.add_argument("--summary", default="")
    approve.set_defaults(func=write_state)

    sc = sub.add_parser("scan", help="Verify the pinned gitleaks binary and scan the staged tree")
    sc.set_defaults(func=scan)

    st = sub.add_parser("status")
    st.set_defaults(func=status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
