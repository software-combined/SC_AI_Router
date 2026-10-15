"""Which clients this install serves, and attaching them to a current install.

Split from the installer entry point, which sits at its recorded line ceiling
(Plan 166). A plain re-run stops before the client stage, so an explicit
attachment request has to be honoured here or it silently does nothing until
the next release. Runs on the installer's Python 3.9: no router imports, and
every collaborator arrives as an argument. `client_dialog` owns how a person
is asked, `codex_switch_config` which Codex block an attach writes and
`codex_switch_app` whether the Switch Codex app goes with it; this module
owns what the answer attaches, and loads those siblings so the entry point
keeps loading one module per concern.
"""
import importlib.util
import os
import time
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_' + name, Path(__file__).resolve().parent / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_dialog = _load('client_dialog')
_switch = _load('codex_switch_config')
_app = _load('codex_switch_app')

_RESTART = {'Codex': 'quit and reopen Codex',
            'Claude Code': 'restart Claude Code',
            'Claude desktop': 'quit and reopen Claude'}


maybe_ask = _dialog.maybe_ask
refuse_switched = _switch.refuse_switched


def validate(args):
    """Reject contradictory explicit choices before creating any state."""
    if args.client == 'none' and (args.desktop or args.clients not in (None, 'none')):
        raise SystemExit('--client none conflicts with client attachments')
    if (args.claude_mode is not None and args.anthropic_mode is not None
            and args.claude_mode != args.anthropic_mode):
        raise SystemExit('--claude-mode conflicts with --anthropic-mode')


def resolve(args, home, state, receipts, write_state, repair=False):
    """Explicit additions, then attached clients, saved choice, and legacy Codex."""
    validate(args)
    choices = ('codex', 'claude', 'both', 'none')
    maybe_ask(args, home, attached=(any_attached(home, receipts)
              or state.get('clients') in choices or state.get('client') == 'none'))
    validate(args)
    try:
        attached = receipts.read_receipt(home).get('clients', {})
    except (OSError, ValueError):
        if not repair or any((args.client, args.clients, args.desktop, args.choose_clients,
                              args.openai_mode, args.claude_mode, args.anthropic_mode)):
            raise SystemExit('client receipts are unreadable; repair them before continuing')
        # The service-only repair leaves unreadable client settings and receipts alone.
        attached = {}
    explicit = args.clients is not None or args.client is not None or args.desktop
    client = (args.client or 'codex') if explicit else state.get('client', 'codex')
    if client not in ('codex', 'none'):
        raise SystemExit('client must be codex or none')
    if explicit:
        clients = args.clients or ('none' if client == 'none' or args.desktop else 'codex')
    else:
        if attached:
            names = [name for name in ('codex', 'claude') if name in attached]
            clients = 'both' if len(names) == 2 else names[0] if names else 'none'
        else:
            clients = state.get('clients')
            if clients not in choices:
                clients = 'none' if client == 'none' else 'codex'
    if clients not in choices:
        raise SystemExit('clients must be codex, claude, both, or none')
    claude_mode = args.claude_mode or args.anthropic_mode or state.get(
        'anthropic_mode', state.get('claude_mode', 'subscription'))
    mode = args.openai_mode or state.get('openai_mode') or receipts.default_mode()
    if claude_mode not in ('subscription', 'none') or mode not in ('subscription', 'none'):
        raise SystemExit('openai_mode and claude_mode must be subscription or none')
    updated = dict(state, claude_mode=claude_mode, openai_mode=mode)
    if state.get('client', 'codex') != client:
        updated['client'] = client
    if not (getattr(args, 'client_choice_cancelled', False)
            or (args.choose_clients and args.clients is None)):
        updated['clients'] = clients
    if (args.claude_mode is not None or args.anthropic_mode is not None
            or args.clients in ('claude', 'both') or args.desktop):
        updated['anthropic_mode'] = claude_mode
    elif ('anthropic_mode' not in state
          and mode != state.get('openai_mode', 'subscription')
          and any(name in attached for name in ('claude', 'claude-desktop'))):
        # Legacy Claude shares OpenAI's mode until an independent choice is saved.
        claude_mode = state.get('openai_mode', 'subscription')
        updated.update(claude_mode=claude_mode, anthropic_mode=claude_mode)
    if updated != state and not getattr(args, 'client_choice_cancelled', False):
        write_state(home, updated)
        state.update(updated)
    return client, clients, claude_mode, mode


def any_attached(home, receipts):
    """True when any client is attached, or when the receipt is unreadable.

    An unreadable receipt is not evidence of a fresh host, and the --setup
    repair owns recovering it, so it reads as attached: this gate must never
    attach on top of state it cannot read, and it must not crash on it. The
    error contract matches claude_config.refresh_snapshot: a receipt the
    process cannot even open reads as attached too. Later eager reads
    elsewhere are unchanged.
    """
    try:
        return bool(receipts.read_receipt(home).get('clients'))
    except (OSError, ValueError):
        return True


def _connected(names):
    """One client-aware closing line; never names a client that is not served."""
    return '%s connected; %s to use the router.' % (
        ', '.join(names), ' and '.join(_RESTART[name] for name in names))


def attach_codex(home, state, mode, codex_config, previous=None,
                 static_catalogue=False, python=None):
    """Write the Codex provider block and receipt; returns the config path.

    Shared with the full install path so a current install and a fresh one
    write the same block, the same before-image and the same receipt. The
    block is the variant the receipt records, so an update never switches
    Codex to or from the router's own provider. Given the router's `python`,
    the Switch Codex app is then built, refreshed or removed to match.
    """
    if previous is None:
        previous = codex_config.codex_attachment(home)
    config_path = Path.home() / '.codex' / 'config.toml'
    block = _switch.build(home, state, mode, static_catalogue, _switch.recorded(previous))
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
    block, before, desktop, reviewer = codex_config.attach_config(
        config_path, block, previous)
    codex_config.write_receipt(home, config_path, block, rules_receipt, mode, before,
                               desktop=desktop, variant=previous.get('variant'),
                               reviewer=reviewer)
    if python:
        _app.sync(home, python)
    return config_path


def attach_desktop_only(args, home, state, codex, desktop, saved=None, python=None):
    """Attach the Claude desktop profile alone, detaching nothing else.

    `--clients none` selects no terminal client, so with `--desktop` the
    desktop profile is the whole attachment. `--client none` promises to
    leave every client setting untouched and keeps refusing the pair.
    """
    if args.client == 'none':
        raise SystemExit('--desktop conflicts with --client none')
    desktop.attach(home, state, codex, saved, python=python, refresh=bool(saved))


def none_outcome(args, desktop=False):
    """The closing line for the branch that attaches no terminal client."""
    if args.desktop or desktop:
        return 'Claude desktop connected'
    if getattr(args, 'client_choice_cancelled', False):
        return 'no client attached'
    return 'service-only, no client changes'


def attach_current(args, home, *, codex, desktop, claude, write_state, resolve,
                   ensure_state, python, ready):
    """Attach what the flags ask for without re-extracting the release.

    Additive by design: it attaches the selected clients and detaches nothing.
    A bare re-run never reaches here (the caller keeps its old no-op), and
    `--clients none --desktop` means the Claude desktop profile alone.
    """
    if args.dry_run:
        print('would connect the selected clients to the installed router')
        return 0
    state = ensure_state(home)
    previous = state.copy()
    _, clients, claude_mode, mode = resolve(args, home, state)
    if args.choose_clients and args.clients is None:
        # The chooser was asked for but could not ask (no dialog tool, or an
        # unattended run): attach nothing rather than guessing.
        ready(home, state, previous, python, only_if_changed=True)
        return 0
    if clients == 'none':
        if not args.desktop:
            ready(home, state, previous, python, only_if_changed=True)
            if not getattr(args, 'client_choice_cancelled', False):
                print('nothing to attach: --clients none attaches no client')
            return 0
        ready(home, state, previous, python)
        return desktop.attach_current(args, codex, write_state, python=python)
    if claude_mode == 'none' and clients in ('claude', 'both'):
        write_state(home, previous)
        raise SystemExit('claude_mode is none: re-run with --claude-mode subscription '
                         'to attach Claude Code, or select --clients codex')
    ready(home, state, previous, python)
    names = []
    if clients in ('codex', 'both'):
        attach_codex(home, state, mode, codex,
                     static_catalogue=args.static_catalogue, python=python)
        names.append('Codex')
    if clients in ('claude', 'both'):
        claude(home, state, python=python)
        names.append('Claude Code')
    if args.desktop:
        desktop.attach_current(args, codex, write_state, python=python)
        names.append('Claude desktop')
    print(_connected(names))
    return 0
