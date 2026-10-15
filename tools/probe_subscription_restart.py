"""Offline subscription restart regressions; no credentials or provider calls."""
import argparse
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='retired; always refused')
    args = parser.parse_args(argv)
    if args.live:
        parser.error('Live probes are retired; run the offline command without --live.')
    return subprocess.call([sys.executable, '-m', 'unittest',
                            'tests.test_subscription_restart'],
                           cwd=Path(__file__).resolve().parents[1])


if __name__ == '__main__':
    raise SystemExit(main())
