"""Print non-secret runner inputs for the bounded diagnostic CI comparison."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import ssl
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop-target', choices=('darwin/arm64', 'darwin/x86_64',
                        'windows/x86_64', 'linux/arm64', 'linux/x86_64'))
    args = parser.parse_args()

    def git(revision):
        return subprocess.check_output(['git', 'rev-parse', revision], cwd=ROOT,
                                       text=True).strip()

    def version(command):
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT,
                                       timeout=15).strip()

    packages = {}
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        packages[name.lower().replace('_', '-')] = metadata.version(name)
    compilers = {}
    if sys.platform == 'darwin':
        compilers['swift'] = version(['xcrun', 'swiftc', '--version'])
    elif sys.platform == 'win32':
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        compilers['csharp_sha256'] = hashlib.sha256(compiler.read_bytes()).hexdigest()
    elif args.desktop_target:
        compilers['rust'] = version(['rustup', 'run', '1.90.0', 'rustc', '--version', '--verbose'])
    shells = {}
    if sys.platform == 'win32':
        for shell in ('powershell', 'pwsh'):
            shells[shell] = version([shell, '-NoProfile', '-NonInteractive', '-Command',
                                     '$PSVersionTable.PSVersion.ToString()'])
    elif shutil.which('pwsh'):
        shells['pwsh'] = version(['pwsh', '-NoProfile', '-NonInteractive', '-Command',
                                 '$PSVersionTable.PSVersion.ToString()'])
    bundle = ssl.get_default_verify_paths().cafile
    bundle_hash = hashlib.sha256(Path(bundle).read_bytes()).hexdigest() if bundle else None
    context = ssl.create_default_context()
    certificates = sorted(context.get_ca_certs(binary_form=True))
    loaded_hash = hashlib.sha256(b''.join(certificates)).hexdigest()
    result = dict(commit=git('HEAD'), tree=git('HEAD^{tree}'), python=sys.version,
                  architecture=platform.machine(), platform=platform.platform(),
                  cpus=os.cpu_count(), openssl=ssl.OPENSSL_VERSION,
                  image=os.environ.get('ImageOS'), image_version=os.environ.get('ImageVersion'),
                  packages=packages, compilers=compilers, shells=shells,
                  ca_bundle_sha256=bundle_hash,
                  loaded_ca_sha256=loaded_hash, loaded_ca_count=len(certificates))
    print('CI environment: ' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
