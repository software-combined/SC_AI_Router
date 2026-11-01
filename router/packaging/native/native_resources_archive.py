"""Export the existing staged Resources tree for the signed channel feed."""
import hashlib
import json
import tarfile
from pathlib import Path


def export(resources, out, metadata):
    name = 'scg-router-resources-%s-%s.tar.gz' % (
        metadata['version'], metadata['target'].replace('/', '-'))
    archive = Path(out) / name
    if archive.exists() or archive.is_symlink():
        raise ValueError('Native resources archive already exists')
    with tarfile.open(archive, 'w:gz') as stream:
        stream.add(resources, arcname='Resources')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    doc = dict(file=name, target=metadata['target'], version=metadata['version'],
               sha256=digest, size=archive.stat().st_size, bundle_sha256=metadata['sha256'])
    archive.with_suffix('.resources.json').write_text(json.dumps(doc, indent=2) + '\n')
    return archive
