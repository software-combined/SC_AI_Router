"""Detached repair prompts; verified update facts remain owned by update_status.

The small warning receipt records presentation time only. It never rewrites
Router state, so a dialog cannot race an installer or clear another warning.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load

RECEIPT = 'update-warning.json'
INTERVAL = 24 * 60 * 60
COMPONENT_LABELS = dict(controller='Automatic updates', updater_launcher='Automatic updates',
    scheduler='Scheduled checks', assistants='Assistant connections',
    controls='Router controls', controls_launchers='Router controls')


def snapshot(home):
    return load('diagnostics')._status_document(home)


def message(doc):
    labels = {'codex': 'Codex', 'claude': 'Claude Code', 'claude-desktop': 'Claude desktop'}
    names = ', '.join(labels[key] for key in labels if key in doc.get('clients', {}))
    facts, status = doc['update'], load('update_status')
    failed = status.components(facts)
    reasons = dict.fromkeys(COMPONENT_LABELS[key] + ' need repair.'
        for key in COMPONENT_LABELS if failed.get(key) == 'failed')
    reason = ' '.join(reasons) or (
        'The last setup or repair did not finish.' if facts.get('installation_repair_required') else
        'Router missed its scheduled checks.' if facts.get('missed_scheduled_checks') else
        'The last update check could not finish.')
    return ('Router updates for %s need attention.\n%s\n\nRunning version: %s\n'
            'Latest known version for %s: %s\nLast successful check: %s\n\n'
            'Finish active work before choosing Repair now. You can choose Later '
            'and open SCG Router when you are ready.' % (names or 'your assistants', reason,
            doc.get('running_version') or 'Unknown',
            'beta' if doc.get('channel') == 'beta' else 'stable',
            facts.get('latest_known_version') or 'Unknown',
            status.display_time(facts.get('last_successful_check_at'))))


def repair(home, run=subprocess.run):
    controller = load('native_controller').installer(home)
    if controller is None:
        raise ValueError('The verified maintenance controller is unavailable')
    feed = load('feed').FEED_URL.replace('/stable/', '/' + load('update_status').channel(home) + '/')
    run([sys.executable, str(controller), '--home', str(home), '--feed', feed,
         '--python', sys.executable, '--repair'], check=True, timeout=900,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))


def due(home, facts, now):
    if not facts.get('offer_repair'):
        return False
    try:
        previous = load('update_status').seconds(json.loads(
            (home / RECEIPT).read_text()).get('last_prompted_at'))
    except (OSError, ValueError, AttributeError):
        previous = None
    return previous is None or now - previous >= INTERVAL


def show(home, now=None):
    """Only a displayed dialog consumes the daily allowance. Missing GUI stays pending."""
    if os.environ.get('ROUTER_NO_NOTICE') == '1':
        return
    home = Path(home)
    with load('service').install_lock(home, '.update-warning.lock') as held:
        if not held:
            return
        doc = snapshot(home)
        now = time.time() if now is None else now
        if not due(home, doc.get('update', {}), now):
            return
        answer = load('native_dialog').confirm_result(message(doc), home,
                                                       labels=('Repair now', 'Later'))
        if answer is None:
            load('update_reconcile').log(home, 'update_warning', 'dialog_unconfirmed')
            return
        try:
            load('atomic_write').replace_json(home / RECEIPT, dict(
                last_prompted_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))))
        except OSError as exc:
            load('update_reconcile').log(home, 'update_warning', 'receipt_write_failed',
                error=type(exc).__name__, winerror=getattr(exc, 'winerror', None))
            return
        facts, status = doc['update'], load('update_status')
        load('update_reconcile').log(home, 'update_warning', 'presented',
            action='repair' if answer is True else 'later',
            components=sorted(key for key, value in status.components(facts).items() if value == 'failed'),
            error=facts.get('last_error') if facts.get('last_error') in status.ERROR_CODES else None,
            installation_pending=facts.get('installation_repair_required') is True,
            checks_missed=facts.get('missed_scheduled_checks') is True)
        if answer is not True or not snapshot(home).get('update', {}).get('offer_repair'):
            return
    try:
        repair(home)
    except (Exception, SystemExit):
        load('native_dialog').message('Repair could not finish. Open SCG Router and choose Update or repair.')


def offer(home):
    """Best effort and detached: notification failure never blocks an update."""
    try:
        if os.environ.get('ROUTER_NO_NOTICE') == '1':
            return
        home, service, status = Path(home), load('service'), load('update_status')
        facts = status.summary(service._state.read(service._state.path(home)),
            service.current_version(home), service.channel_feed(home), status.channel(home))
        if not due(home, facts, time.time()):
            return
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--home', str(home)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS}
               if os.name == 'nt' else {'start_new_session': True}))
    except (Exception, SystemExit):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        show(args.home)
    except (Exception, SystemExit):
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
