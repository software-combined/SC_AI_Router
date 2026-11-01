"""Build unsigned desktop installers from a canonical bundle and pinned Python."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging' / 'native'))
import native_build  # noqa: E402
import native_linux_gui  # noqa: E402
import native_stage  # noqa: E402
import native_menu_build  # noqa: E402
import native_resources_archive  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--target', required=True, choices=native_stage.TARGETS)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--channel', required=True, choices=('stable', 'beta'))
    parser.add_argument('--download-config', type=Path,
                        help='public tenant and download exchange settings JSON')
    parser.add_argument('--stage-only', action='store_true',
                        help='validate and stage Resources without platform tools')
    parser.add_argument('--linux-zenity', type=Path,
                        help='Zenity executable to bundle with Linux artifacts')
    parser.add_argument('--linux-appimagetool', type=Path)
    parser.add_argument('--linux-appimagetool-sha256')
    parser.add_argument('--linux-uruntime', type=Path)
    parser.add_argument('--linux-uruntime-sha256')
    parser.add_argument('--windows-iscc', default='ISCC.exe',
                        help='path to the Inno Setup compiler')
    # Accepted for old local scripts; unsigned builds are now the normal path.
    parser.add_argument('--allow-unsigned', action='store_true',
                        help=argparse.SUPPRESS)
    return parser


def _build_requirements(parser, args):
    if args.stage_only:
        return
    if args.target.startswith('linux/'):
        required = ('linux_zenity', 'linux_appimagetool',
                    'linux_appimagetool_sha256', 'linux_uruntime',
                    'linux_uruntime_sha256')
        missing = [name.replace('_', '-') for name in required
                   if not getattr(args, name)]
        if missing:
            parser.error('Linux build requires ' + ', '.join('--' + n for n in missing))


def _stage(args, resources):
    metadata = native_stage.stage(args.bundle, args.runtime, args.target,
                                  args.channel, resources,
                                  download_config=args.download_config)
    if args.target.startswith('linux/') and args.linux_zenity:
        native_linux_gui.bundle(args.linux_zenity, resources, args.target)
        metadata['gui_bundle'] = 'zenity'
        (resources / 'installer.json').write_text(
            json.dumps(metadata, indent=2) + '\n')
    return metadata


def _package(args, resources, metadata):
    target = args.target
    if target.startswith('darwin/'):
        return native_build.mac(resources, args.out, metadata['version'],
                                target.split('/')[1])
    if target == 'windows/x86_64':
        return native_build.windows(resources, args.out, metadata['version'],
                                    iscc=args.windows_iscc)
    return native_build.linux(
        resources, args.out, metadata['version'], target.split('/')[1],
        appimagetool=args.linux_appimagetool,
        appimagetool_sha256=args.linux_appimagetool_sha256,
        uruntime=args.linux_uruntime,
        uruntime_sha256=args.linux_uruntime_sha256)


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    _build_requirements(parser, args)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage_only:
        destination = args.out / 'stage'
        if destination.exists() or destination.is_symlink():
            parser.error('stage already exists: ' + str(destination))
        tmp = Path(tempfile.mkdtemp(prefix='.native-stage-', dir=args.out))
        try:
            metadata = _stage(args, tmp / 'Resources')
            os.replace(tmp, destination)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        print(json.dumps({'resources': str(destination / 'Resources'),
                          **metadata}, sort_keys=True))
        return 0
    with tempfile.TemporaryDirectory(prefix='.native-build-', dir=args.out) as tmp:
        resources = Path(tmp) / 'Resources'
        metadata = _stage(args, resources)
        native_menu_build.build(resources, args.target)
        metadata = json.loads((resources / 'installer.json').read_text())
        artifact = _package(args, resources, metadata)
        native_resources_archive.export(resources, args.out, metadata)
    receipt = native_build.receipt(artifact, metadata)
    print(json.dumps({'artifact': str(artifact), 'receipt': str(receipt),
                      'sha256': native_stage.sha256_file(artifact),
                      'native_signature': 'unsigned'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
