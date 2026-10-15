"""Validate and stage a release bundle with its pinned private Python runtime."""

import hashlib
import importlib.util
import json
import re
import shutil
import tarfile
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / 'packaging' / 'runtime.lock'
TARGETS = ('darwin/arm64', 'darwin/x86_64', 'windows/x86_64',
           'linux/arm64', 'linux/x86_64')
MAX_BUNDLE_BYTES = 200 * 1024 * 1024
MAX_UNPACKED_BYTES = 600 * 1024 * 1024


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _lock_entry(target, lock_path):
    spec = importlib.util.spec_from_file_location(
        'native_runtime_lock', ROOT / 'packaging' / 'runtime_lock.py')
    lock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lock)
    doc = lock.validate(lock.load(lock_path))
    os_name, cpu = target.split('/')
    entry = lock.select(doc, os_name, cpu)
    if entry is None or not lock.provisionable(entry):
        raise ValueError('target has no pinned runtime: ' + target)
    if not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
        raise ValueError('runtime lock has invalid sha256 for ' + target)
    return entry


def _member_names(tar, *, links, duplicate_files=False):
    """Preflight every path before extraction, including links and duplicates."""
    seen = set()
    total = 0
    for member in tar.getmembers():
        name = member.name
        parts = PurePosixPath(name).parts
        if (not name or not parts or '\\' in name or name.startswith('/')
                or ':' in parts[0] or '..' in parts
                or (name in seen and not (duplicate_files and member.isfile()))):
            raise ValueError('unsafe or duplicate archive path: ' + name)
        seen.add(name)
        total += member.size
        if total > MAX_UNPACKED_BYTES:
            raise ValueError('archive exceeds unpacked size limit')
        if member.isfile() or member.isdir():
            continue
        if links and (member.issym() or member.islnk()):
            link = member.linkname
            if not link or '\\' in link or link.startswith('/'):
                raise ValueError('unsafe archive link: ' + name)
            # data_filter also checks the resolved target at extraction time.
            continue
        raise ValueError('archive has unsupported member: ' + name)
    return seen


def _verify_bundle(bundle, channel):
    if bundle.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError('bundle exceeds compressed size limit')
    with tarfile.open(bundle, 'r:gz') as tar:
        names = _member_names(tar, links=False, duplicate_files=True)
        if sum(member.name == 'MANIFEST.json' for member in tar.getmembers()) != 1:
            raise ValueError('bundle has duplicate MANIFEST.json')
        if any(not member.isfile() for member in tar.getmembers()):
            raise ValueError('bundle must contain regular files only')
        if 'MANIFEST.json' not in names:
            raise ValueError('bundle has no MANIFEST.json')
        try:
            manifest = json.load(tar.extractfile('MANIFEST.json'))
        except (TypeError, ValueError) as exc:
            raise ValueError('bundle manifest is invalid') from exc
        files = manifest.get('files') if isinstance(manifest, dict) else None
        if not isinstance(files, dict) or set(files) != names - {'MANIFEST.json'}:
            raise ValueError('bundle manifest does not cover every member')
        for name, want in files.items():
            if not isinstance(want, str) or not re.fullmatch(r'[0-9a-f]{64}', want):
                raise ValueError('bundle manifest has invalid sha256: ' + name)
        for member in tar.getmembers():
            if member.name == 'MANIFEST.json':
                continue
            got = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            want = files[member.name]
            if got != want:
                raise ValueError('bundle manifest checksum mismatch: ' + member.name)
        version = manifest.get('version')
        if (not isinstance(version, str)
                or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', version)):
            raise ValueError('bundle has invalid version')
        if manifest.get('channel') != channel:
            raise ValueError('bundle channel does not match requested channel')
        required = {'packaging/VERSION', 'packaging/native_setup.py',
                    'packaging/install.py'}
        if not required <= names:
            raise ValueError('bundle lacks native installer entrypoint or marker')
        if tar.extractfile('packaging/VERSION').read().decode().strip() != version:
            raise ValueError('bundle version marker does not match manifest')
    return version


def _download_config(path):
    """The optional public-only bootstrap settings; reject secret-shaped extras."""
    path = Path(path)
    if path.stat().st_size > 8192:
        raise ValueError('download config is too large')
    try:
        doc = json.loads(path.read_text())
    except (UnicodeError, ValueError) as exc:
        raise ValueError('download config is not valid JSON') from exc
    keys = {'version', 'distribution_origin', 'tenant_id', 'client_id',
            'scope', 'exchange_url'}
    if not isinstance(doc, dict) or set(doc) != keys:
        raise ValueError('download config has missing or extra fields')
    if type(doc['version']) is not int or doc['version'] != 1:
        raise ValueError('download config version must be 1')
    if doc['distribution_origin'] != 'https://dist.softwarecombined.com':
        raise ValueError('download config has unexpected distribution origin')
    for key in ('tenant_id', 'client_id'):
        value = doc[key]
        try:
            valid = isinstance(value, str) and str(uuid.UUID(value)) == value
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise ValueError('download config has invalid ' + key)
    if (not isinstance(doc['scope'], str)
            or not re.fullmatch(r'api://[0-9a-f-]{36}/Download\.Read', doc['scope'])):
        raise ValueError('download config has invalid scope')
    resource_id = doc['scope'][6:-len('/Download.Read')]
    try:
        scope_valid = str(uuid.UUID(resource_id)) == resource_id
    except ValueError:
        scope_valid = False
    if not scope_valid:
        raise ValueError('download config has invalid scope resource')
    try:
        if not isinstance(doc['exchange_url'], str):
            raise ValueError('exchange URL must be a string')
        url = urlsplit(doc['exchange_url'])
        port = url.port
    except ValueError as exc:
        raise ValueError('download config has invalid exchange URL') from exc
    host = re.fullmatch(r'[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com',
                        url.hostname or '')
    if (url.scheme != 'https' or not host or url.path != '/download-access'
            or url.query or url.fragment or url.username or url.password
            or port not in (None, 443)):
        raise ValueError('download config has invalid exchange URL')
    return doc


def stage(bundle, runtime, target, channel, resources, *, lock_path=LOCK_PATH,
          download_config=None):
    """Write a new Resources tree; caller owns cleanup on failure."""
    if target not in TARGETS:
        raise ValueError('unsupported target: ' + target)
    if channel not in ('stable', 'beta'):
        raise ValueError('unsupported channel: ' + channel)
    bundle, runtime, resources = Path(bundle), Path(runtime), Path(resources)
    if not bundle.is_file() or not runtime.is_file():
        raise ValueError('bundle and runtime must be local files')
    public_config = (_download_config(download_config)
                     if download_config is not None else None)
    entry = _lock_entry(target, lock_path)
    runtime_sha = sha256_file(runtime)
    if runtime_sha != entry['sha256']:
        raise ValueError('runtime does not match pinned target sha256: ' + target)
    version = _verify_bundle(bundle, channel)
    bundle_sha = sha256_file(bundle)
    resources.mkdir(parents=True, exist_ok=False)
    router = resources / 'router'
    private_runtime = resources / 'runtime'
    payload = resources / 'payload'
    router.mkdir()
    private_runtime.mkdir()
    payload.mkdir()
    with tarfile.open(bundle, 'r:gz') as tar:
        tar.extractall(router, filter='data')
    with tarfile.open(runtime, 'r:gz') as tar:
        _member_names(tar, links=True)
        tar.extractall(private_runtime, filter='data')
    runtime_exec = ('python/pythonw.exe' if target == 'windows/x86_64'
                    else entry['exec'])
    if not (private_runtime / entry['exec']).is_file():
        raise ValueError('pinned runtime interpreter is missing')
    if not (private_runtime / runtime_exec).is_file():
        raise ValueError('private GUI interpreter is missing')
    for licence in entry['licences']:
        if not (private_runtime / licence).is_file():
            raise ValueError('private runtime licence is missing: ' + licence)
    shutil.copyfile(bundle, payload / 'bundle.tar.gz')
    latest = {'version': version, 'url': 'file://bundle.tar.gz',
              'sha256': bundle_sha, 'channel': channel,
              'min_python': '3.14', 'serial': 0}
    (payload / 'latest.json').write_text(json.dumps(latest, indent=2) + '\n')
    metadata = {'version': version, 'channel': channel, 'target': target,
                'sha256': bundle_sha, 'runtime_sha256': runtime_sha,
                'runtime_exec': runtime_exec,
                'native_signature': 'unsigned'}
    (resources / 'installer.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if public_config is not None:
        (resources / 'download-auth.json').write_text(
            json.dumps(public_config, indent=2) + '\n')
    return metadata
