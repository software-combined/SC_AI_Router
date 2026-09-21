"""Which clients this install serves, and attaching them to a current install.

Split from the installer entry point, which sits at its recorded line ceiling
(Plan 166). A plain re-run stops before the client stage, so an explicit
attachment request has to be honoured here or it silently does nothing until
the next release. Runs on the installer's Python 3.9: no router imports, and
every collaborator arrives as an argument.
"""
import os
import time
from pathlib import Path

_RESTART = {'Codex': 'quit and reopen Codex',
            'Claude Code': 'restart Claude Code',
            'Claude desktop': 'quit and reopen Claude'}


def _connected(names):
    """One client-aware closing line; never names a client that is not served."""
    return '%s connected; %s to use the router.' % (
        ', '.join(names), ' and '.join(_RESTART[name] for name in names))


def attach_codex(home, state, mode, codex_config, previous=None):
    """Write the Codex provider block and receipt; returns the config path.

    Shared with the full install path so a current install and a fresh one
    write the same block, the same before-image and the same receipt.
    """
    if previous is None:
        previous = codex_config.codex_attachment(home)
    config_path = Path.home() / '.codex' / 'config.toml'
    block = codex_config.build_block(home, state, mode)
    # Global instructions are install-once via the setup window's starter
    # choice: this installer never writes, rewrites, or re-enforces them.
    rules_receipt = previous.get('global_instructions')
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    (home / f'config-before-{stamp}.toml').write_bytes(
        (config_path.read_text() if config_path.exists() else '').encode())
    try:
        os.chmod(home / f'config-before-{stamp}.toml', 0o600)
    except OSError:
        pass
    block, before, desktop = codex_config.attach_config(config_path, block, previous)
    codex_config.write_receipt(home, config_path, block, rules_receipt, mode, before,
                               desktop=desktop)
    return config_path


def attach_desktop_only(args, home, state, codex, desktop):
    """Attach the Claude desktop profile alone, detaching nothing else.

    `--clients none` selects no terminal client, so with `--desktop` the
    desktop profile is the whole attachment. `--client none` promises to
    leave every client setting untouched and keeps refusing the pair.
    """
    if args.client == 'none':
        raise SystemExit('--desktop conflicts with --client none')
    desktop.attach(home, state, codex)


def attach_current(args, home, *, codex, desktop, claude, write_state, resolve,
                   ensure_state, python):
    """Attach what the flags ask for without re-extracting the release.

    Additive by design: it attaches the selected clients and detaches nothing.
    A bare re-run never reaches here (the caller keeps its old no-op), and
    `--clients none --desktop` means the Claude desktop profile alone.
    """
    if args.dry_run:
        print('would connect the selected clients to the installed router')
        return 0
    state = ensure_state(home)
    _, clients, claude_mode, mode = resolve(args, home, state)
    if clients == 'none':
        if not args.desktop:
            print('nothing to attach: --clients none attaches no client')
            return 0
        return desktop.attach_current(args, codex, write_state)
    if claude_mode == 'none' and clients in ('claude', 'both'):
        raise SystemExit('claude_mode is none: re-run with --claude-mode subscription '
                         'to attach Claude Code, or select --clients codex')
    names = []
    if clients in ('codex', 'both'):
        attach_codex(home, state, mode, codex)
        names.append('Codex')
    if clients in ('claude', 'both'):
        claude(home, state, python=python)
        names.append('Claude Code')
    if args.desktop:
        desktop.attach_current(args, codex, write_state)
        names.append('Claude desktop')
    print(_connected(names))
    return 0
