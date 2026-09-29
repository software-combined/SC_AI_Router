"""Stable Open Claude and Switch Claude entry point."""
import argparse
import ast
import runpy
import sys
from pathlib import Path


def helper_path(home):
    try:
        name = (home / 'current').read_text(encoding='utf-8').strip().split('/')[-1]
    except (OSError, ValueError):
        raise SystemExit('SCG Router needs setup again before switching Claude.')
    helper = home / 'releases' / name / 'packaging' / 'claude_desktop_switch.py'
    if not name or not helper.is_file():
        raise SystemExit('This SCG Router version does not include Switch Claude.')
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
    helper = helper_path(home)
    if args.action == 'capture':
        helper = helper.with_name('claude_profile_hook.py')
        sys.argv = [str(helper), '--home', str(home)]
    else:
        sys.argv = [str(helper), '--home', str(home), '--action', args.action]
    try:
        runpy.run_path(str(helper), run_name='__main__')
    except Exception:
        raise SystemExit('Claude could not be opened safely. Run SCG Router setup again.') from None


if __name__ == '__main__':
    main()
