"""Build one offline status page from project records. Uses only the standard library."""
import argparse
import base64
from datetime import datetime, timezone
import json
import mimetypes
from pathlib import Path
import re
import tempfile


ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'status'


def build(data_path, output_path):
    data_path, output_path = Path(data_path).resolve(), Path(output_path).resolve()
    if data_path == output_path:
        raise ValueError('The page must not replace its source records')
    data = json.loads(data_path.read_text(encoding='utf-8'))
    if data.get('schemaVersion') != 1 or not isinstance(data.get('features'), list):
        raise ValueError('Expected tracker records with schemaVersion 1')
    project = data.get('project')
    if not isinstance(project, dict) or not project.get('title'):
        raise ValueError('Record the project title')
    if 'template' in project and not isinstance(project['template'], bool):
        raise ValueError('Template mode must be true or false')
    if not project.get('template') and any(f.get('sample') or str(f.get('title', '')).startswith('[Example:') for f in data['features']):
        raise ValueError('Replace example records before reporting real work')
    images = {}
    for feature in data['features']:
        for shot in feature.get('screenshots', []):
            name = shot.get('src', '')
            if not re.fullmatch(r'(?:img|screenshots)/[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp)', name, re.I):
                raise ValueError('Screenshots must be local PNG, JPEG or WebP files in img/ or screenshots/')
            path = (data_path.parent / name).resolve()
            if not path.is_relative_to(data_path.parent):
                raise ValueError('A screenshot must stay within the project output folder')
            mime = mimetypes.guess_type(name)[0]
            images[name] = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
    payload = {'records': data, 'images': images, 'generatedAt': datetime.now(timezone.utc).isoformat()}
    packed = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).replace('<', '\\u003c')
    model = re.sub(r'^export ', '', (ASSETS / 'delivery-model.mjs').read_text(encoding='utf-8'), flags=re.M)
    app = re.sub(r'^import[^\n]+\n', '', (ASSETS / 'delivery.js').read_text(encoding='utf-8'))
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    replacements = {
        '<!--STATUS_STYLE-->': '<style>' + (ASSETS / 'delivery.css').read_text(encoding='utf-8') + '</style>',
        '<!--STATUS_DATA-->': '<script id="status-data" type="application/json">' + packed + '</script>',
        '<!--STATUS_SCRIPT-->': '<script type="module">' + model + '\n' + app + '</script>',
    }
    for marker, value in replacements.items():
        if html.count(marker) != 1:
            raise ValueError('The bundled template is incomplete')
        html = html.replace(marker, value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete page; interrupted builds retain the last usable copy.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output_path.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
            tmp.write(html)
        temporary.replace(output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path, help='Project tracker JSON')
    parser.add_argument('--output', required=True, type=Path, help='Offline HTML page')
    args = parser.parse_args()
    print(build(args.data, args.output))


if __name__ == '__main__':
    main()
