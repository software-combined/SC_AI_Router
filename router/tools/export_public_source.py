"""Export the reviewed index's current files without private Git history.

Stage intended files first. This command verifies working bytes against the index;
it creates no commit, remote, tag or publication. Scan the resulting snapshot
and archive before publishing source or rewriting shared history.
"""
import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_PARTS = {'.git', 'plans', 'TO MONITOR', '__pycache__', '.aws'}


def export(root, output):
    output = Path(output).resolve()
    if output.exists():
        raise SystemExit('refusing to overwrite an existing public source export')
    if output == root or root in output.parents:
        raise SystemExit('source export must be outside the checkout')
    index = subprocess.check_output(
        ['git', 'ls-files', '--stage', '-z'], cwd=root).decode().split('\0')
    entries = {}
    for record in filter(None, index):
        header, name = record.split('\t', 1)
        mode, oid, stage = header.split()
        if stage != '0' or mode not in ('100644', '100755'):
            raise SystemExit('source index must contain resolved regular files: ' + name)
        entries[name] = (int(mode, 8) & 0o777, oid)
    payloads, modes = {}, {}
    for name, (mode, oid) in sorted(entries.items()):
        path = root / name
        if PRIVATE_PARTS.intersection(Path(name).parts):
            raise SystemExit('private path in source index: ' + name)
        if path.is_symlink() or not path.is_file():
            raise SystemExit('source member is missing or is a symlink: ' + name)
        data = path.read_bytes()
        blob = b'blob ' + str(len(data)).encode() + b'\0' + data
        if hashlib.sha1(blob).hexdigest() != oid:
            raise SystemExit('source bytes differ from the reviewed index: ' + name)
        payloads[name] = data
        modes[name] = mode
    output.mkdir(parents=True)
    snapshot = output / 'source'
    snapshot.mkdir()
    hashes = {}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name, data in payloads.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(modes[name])
            hashes[name] = hashlib.sha256(data).hexdigest()
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(data), 0
            info.mode = modes[name]
            tar.addfile(info, io.BytesIO(data))
    archive = output / 'public-source.tar.gz'
    archive.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))
    (output / 'inventory.json').write_text(json.dumps({
        'contains_git_history': False, 'files': hashes, 'modes': modes,
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    }, indent=2) + '\n')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(export(ROOT, args.out))


if __name__ == '__main__':
    main()
