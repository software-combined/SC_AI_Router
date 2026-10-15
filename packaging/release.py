"""Build a deterministic release bundle. Usage: python3 packaging/release.py --out dist [--build N] [--sha SHA] [--channel NAME] [--url-base URL] [--gen-key FILE]"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

_feed_verify_spec = importlib.util.spec_from_file_location(
    'router_feed_verify', Path(__file__).resolve().parent / 'feed_verify.py')
feed_verify = importlib.util.module_from_spec(_feed_verify_spec)
_feed_verify_spec.loader.exec_module(feed_verify)

MIN_PYTHON = '3.14'
REPO = 'software-combined/SC_AI_Router'


# Single release inventory (Plan 123): every non-globbed bundle member lives
# here. tests/test_packaging.py derives its expected bundle from
# bundle_files() and keeps an explicit required-files assertion, so a member
# dropped from this list still fails the gate.
PACKAGING_FILES = (
    'packaging/VERSION', 'packaging/install.py', 'packaging/bundle.py',
    'packaging/launchd.py',
    'packaging/router_launch.py', 'packaging/service.py',
    'packaging/feed.py', 'packaging/feed_verify.py',
    'packaging/download_auth.py', 'packaging/download_oauth.py',
    'packaging/download_session.py',
    'packaging/atomic_write.py',
    'packaging/notice.py', 'packaging/notice_text.py',
    # Plan 179: the router carries the agent skills, so a machine needs no
    # git account and no marketplace command to receive them.
    'packaging/agent_skills.py',
    'packaging/assets/router-icon.png',
    'packaging/systemd.py', 'packaging/update_launch.py',
    'packaging/task_launch.py',
    'packaging/updater.py', 'packaging/codex_config.py',
    'packaging/codex_switch_config.py', 'packaging/codex_switch_offer.py',
    'packaging/codex_desktop_switch.py', 'packaging/codex_config_proof.py',
    'packaging/codex_switch_app.py', 'packaging/codex_switch_launch.py',
    'packaging/claude_config.py',
    'packaging/claude_desktop_config.py',
    'packaging/claude_desktop_policy.py',
    'packaging/claude_desktop_platform.py',
    'packaging/desktop_linux.py',
    'packaging/claude_desktop_switch.py',
    'packaging/claude_profile_rules.py',
    'packaging/claude_profile_identity.py',
    'packaging/claude_profile_records.py',
    'packaging/claude_profile_publish.py',
    'packaging/claude_profile_transaction.py',
    'packaging/claude_profile_history.py',
    'packaging/claude_profile_bundle.py',
    'packaging/claude_profile_sync.py',
    'packaging/claude_profile_ledger.py',
    'packaging/claude_profile_hook.py',
    'packaging/claude_profile_launch.py',
    'packaging/client_choice.py',
    'packaging/client_dialog.py',
    'packaging/diagnostics.py', 'packaging/provider_keys.py',
    'packaging/operator_surface.py',
    'packaging/runtime.lock', 'packaging/runtime_lock.py', 'packaging/runtime-notices.json',
    'packaging/runtime-components.json', 'packaging/RUNTIME-NOTICES.txt',
    'packaging/platforms/__init__.py',
    'packaging/platforms/darwin.py', 'packaging/platforms/linux.py',
    'packaging/platforms/windows.py',
    'packaging/install.sh', 'packaging/install.ps1',
    # Every installed release is a copy of the software delivered to a
    # user, so the licence and notices travel with it (Apache-2.0).
    'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md',
)


# Installed operator helpers only. Development probes, capture utilities and
# publication tools belong to a source checkout, never an end-user release.
OPERATOR_TOOLS = ('disable.py', 'global_instructions.py', 'provision_key.py')


def bundle_files(root):
    return (
        sorted(p.relative_to(root).as_posix() for p in (root / 'ai_router').rglob('*.py'))
        + sorted(p.relative_to(root).as_posix() for p in (root / 'ai_router').glob('*.txt'))
        + sorted(p.relative_to(root).as_posix() for p in (root / 'ai_router').glob('*.json'))
        + ['tools/' + name for name in OPERATOR_TOOLS]
        # Plan 134: an installed host had no documentation at all. The README
        # and the markdown docs travel with the release so an operator reads
        # the same page the repository shows.
        + sorted(p.relative_to(root).as_posix() for p in (root / 'docs').rglob('*.md'))
        + ['README.md', 'SECURITY.md']
        + plugin_files(root)
        + list(PACKAGING_FILES)
    )


def plugin_files(root):
    """Plan 179: both plugin manifests and every skill file, per plugin.

    The git updater's own scripts deliberately stay out: the router is the
    delivery channel, so a shipped plugin never carries a second updater.
    """
    plugins = root / 'plugins'
    if not plugins.is_dir():
        return []
    wanted = []
    for plugin in sorted(p for p in plugins.iterdir() if p.is_dir()):
        for manifest in ('.codex-plugin/plugin.json', '.claude-plugin/plugin.json'):
            if (plugin / manifest).is_file():
                wanted.append((plugin / manifest).relative_to(root).as_posix())
        prefix = plugin.relative_to(root).as_posix() + '/'
        for path in sorted(plugin.rglob('*')):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or '__pycache__' in path.parts or rel.endswith('.pyc'):
                continue
            # A shipped skill reads, links and runs more than skills/: the
            # review gate reads references/ and runs scripts/setup.py. Only the
            # git updater is withheld, because the router is the channel now.
            if rel.startswith(prefix + 'scripts/') and path.name != 'setup.py':
                continue
            wanted.append(rel)
    return wanted


def semantic_version(base_version):
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', base_version):
        raise SystemExit(f'packaging/VERSION {base_version} is not semantic versioning')
    return base_version


def release_tag(tag, base_version):
    """Express is urgency on the existing channel, never a version suffix."""
    semantic_version(base_version)
    match = re.fullmatch(rf'v{re.escape(base_version)}(-beta)?(-express)?', tag)
    if not match:
        raise SystemExit(
            f'tag {tag} does not match the release version for packaging/VERSION {base_version}')
    return ('beta' if match[1] else 'stable'), bool(match[2])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--build', type=int, default=0)
    parser.add_argument('--sha', default='')
    parser.add_argument('--channel', choices=('stable', 'beta'))
    parser.add_argument('--tag', help='Validated release tag, including optional -beta and -express.')
    parser.add_argument('--url-base')
    parser.add_argument('--gen-key', metavar='OUT',
                        help='write a fresh 32-byte hex release signing seed (owner-only file) and exit')
    parser.add_argument('--sign', metavar='SEEDFILE',
                        help='retired: signing moved to tools/publish_feed.py --sign, which signs the served bytes')
    args = parser.parse_args(argv)
    if args.gen_key:
        out = Path(args.gen_key)
        try:
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise SystemExit(f'refusing to overwrite release seed {out}')
        with os.fdopen(fd, 'w') as stream:
            stream.write(feed_verify.generate_keypair()[0] + '\n')
        print(f'wrote release signing seed to {out}; compile its public key into feed_verify.FEED_PUBLIC_KEY')
        return
    root = Path(__file__).resolve().parents[1]
    # The runtime lock must validate before any bundle ships: a broken pin
    # table must never reach a release artifact.
    _lock_spec = importlib.util.spec_from_file_location(
        'router_runtime_lock', root / 'packaging' / 'runtime_lock.py')
    _lock_mod = importlib.util.module_from_spec(_lock_spec)
    _lock_spec.loader.exec_module(_lock_mod)
    _lock_mod.validate(_lock_mod.load())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_version = semantic_version(
        (root / 'packaging' / 'VERSION').read_text().strip())
    channel, express = release_tag(args.tag, base_version) if args.tag else (args.channel or 'stable', False)
    if args.channel and args.channel != channel:
        raise SystemExit('--channel does not match release tag')
    args.channel = channel
    if args.build < 0:
        raise SystemExit('--build must be >= 0')
    version = f'{base_version}.{args.build}'
    names = bundle_files(root)
    # Stamp the composed version into the bundled marker so installed
    # releases report what the updater compares (current_version, /health).
    payloads = {name: (version + '\n').encode() if name == 'packaging/VERSION'
                else (root / name).read_bytes() for name in names}
    manifest_files = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    manifest = {'version': version, 'files': manifest_files,
                'codex_tested': 'unknown', 'min_python': MIN_PYTHON,
                'git_sha': args.sha, 'channel': args.channel}
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name in names + ['MANIFEST.json']:
            data = (json.dumps(manifest, indent=2) + '\n').encode() if name == 'MANIFEST.json' else payloads[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    tarball = gzip.compress(tar_buffer.getvalue(), mtime=0)
    tarball_name = f'ai-router-{version}.tar.gz'
    (out_dir / tarball_name).write_bytes(tarball)
    tag = args.tag or f'v{base_version}' + ('-beta' if args.channel == 'beta' else '')
    base = args.url_base or f'https://github.com/{REPO}/releases/download/{tag}'
    latest = {'version': version, 'url': f'{base}/{tarball_name}',
              'sha256': hashlib.sha256(tarball).hexdigest(), 'min_python': MIN_PYTHON,
              'serial': args.build, 'channel': channel, 'express': express,
              'models_url': f'https://dist.softwarecombined.com/{channel}/models.json',
              'published': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    (out_dir / 'latest.json').write_text(json.dumps(latest, indent=2) + '\n')
    # The bootstrap resolves its runtime from this table, never from a
    # hardcoded filename: pins land only through reviewed lock changes.
    _lock_doc = _lock_mod.load()
    _lock_table = {e['os'] + '/' + e['cpu']: {
        'mirror': e['mirror'], 'sha256': e['sha256'], 'exec': e['exec']}
        for e in _lock_doc['targets']}
    (out_dir / 'runtimes.json').write_text(json.dumps(
        {'cpython': _lock_doc['cpython'], 'targets': _lock_table},
        indent=2) + '\n')
    if args.sign:
        raise SystemExit('release --sign is retired: sign the served bytes with tools/publish_feed.py --sign')
    print(f'built {tarball_name} {latest["sha256"][:12]}')


if __name__ == '__main__':
    main()
