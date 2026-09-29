"""Stable Open Claude and Switch Claude entry point."""
import argparse
import ast
import runpy
import subprocess
import sys
from pathlib import Path

BUNDLE_ID = 'com.anthropic.claudefordesktop'


def _release_helper(home):
    try:
        name = (home / 'current').read_text(encoding='utf-8').strip().split('/')[-1]
    except (OSError, ValueError):
        raise SystemExit('SCG Router needs setup again before switching Claude.')
    helper = home / 'releases' / name / 'packaging' / 'claude_desktop_switch.py'
    if not name or not helper.is_file():
        raise SystemExit('This SCG Router version does not include Switch Claude.')
    return helper


def helper_path(home):
    helper = _release_helper(home)
    try:
        tree = ast.parse(helper.read_text(encoding='utf-8'))
        actions = next(ast.literal_eval(node.value) for node in tree.body
                       if isinstance(node, ast.Assign) and any(
                           isinstance(target, ast.Name) and target.id == 'PROFILE_ACTIONS'
                           for target in node.targets))
        if not all(action in actions for action in ('start', 'switch')):
            raise ValueError('missing actions')
        if not helper.with_name('claude_profile_sync.py').is_file():
            raise ValueError('missing sync')
    except (OSError, SyntaxError, ValueError, TypeError, StopIteration):
        raise SystemExit('Update SCG Router before using Open Claude or Switch Claude.') from None
    return helper


def main(argv=None):
    parser = argparse.ArgumentParser(prog='claude_profile_launch.py')
    parser.add_argument('--home', default=str(Path(__file__).resolve().parent))
    parser.add_argument('--action', choices=('start', 'switch', 'capture'),
                        default='switch')
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser()
    try:
        helper = helper_path(home)
        rest = ['--home', str(home), '--action', args.action]
        if args.action == 'capture':
            helper, rest = helper.with_name('claude_profile_hook.py'), ['--home', str(home)]
    except SystemExit:
        # A rollback keeps these launchers, but that release predates task sharing.
        if args.action == 'capture':
            return  # Nothing to capture; never interrupt a Claude Code session.
        if args.action == 'start':
            if sys.platform != 'darwin':
                raise
            subprocess.run(['/usr/bin/open', '-b', BUNDLE_ID], check=False)
            return
        helper, rest = _release_helper(home), ['--home', str(home)]  # Its plain switch.
    sys.argv = [str(helper)] + rest
    try:
        runpy.run_path(str(helper), run_name='__main__')
    except Exception:
        if args.action == 'capture':
            return  # A callback never interrupts a Claude Code session.
        raise SystemExit('Claude could not be opened safely. Run SCG Router setup again.') from None


if __name__ == '__main__':
    main()
