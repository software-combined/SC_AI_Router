"""Work-account setup; the Hub owns identity, company policy and key issuance."""
import importlib.util
import json
import subprocess
import uuid
from pathlib import Path

from . import key_dialog

MANUAL = object()
CANCELLED = object()
CHOICES = (('work', 'Sign in with my work account'), ('key', 'Use my own key'))


class SignInFailed(RuntimeError):
    """Fixed text only; upstream responses can contain credentials."""


def _load(name):
    path = Path(__file__).resolve().parents[1] / 'packaging' / (name + '.py')
    spec = importlib.util.spec_from_file_location('router_work_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration():
    """Public deployment settings ship inside the verified Router release."""
    try:
        config = json.loads(Path(__file__).with_name('work-account.json').read_text())
        for name in ('tenant_id', 'client_id'):
            if str(uuid.UUID(config[name])) != config[name]:
                raise ValueError()
        scope_id, scope = config['scope'].removeprefix('api://').split('/')
        uuid.UUID(scope_id)
        if (not config['scope'].startswith('api://') or scope != 'Router.Provision'
                or config['provision_url'] != 'https://hub.softwarecombined.com/api/v1/router/provision'):
            raise ValueError()
        return config
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SignInFailed('Work account setup needs IT attention.') from None


def provision(config=None, authorize=None, post=None):
    """Return the personal inference key in memory; never save OAuth tokens."""
    config = configuration() if config is None else config
    oauth = _load('download_oauth')
    try:
        session = (authorize or oauth.authorize)(config)
        body = (post or oauth.post)(config['provision_url'], b'{"confirm":true}',
            {'Authorization': 'Bearer ' + session['access_token'],
             'Content-Type': 'application/json'})
        data = body['data']
        key = data['key']
        if (not isinstance(key, str) or not key.startswith('sk-or-')
                or not 30 <= len(key) <= 256
                or any(ord(char) < 33 or ord(char) > 126 for char in key)
                or data['monthlyLimitUsd'] != 50 or data['limitReset'] != 'monthly'
                or not isinstance(data['keyHash'], str) or not data['keyHash']):
            raise ValueError()
        uuid.UUID(data['workspaceId'])
        if not isinstance(data['companyId'], str) or not data['companyId']:
            raise ValueError()
        return key
    except oauth.SignInRequired as exc:
        message = {409: 'Your work key needs an IT check. Contact Software Combined IT.',
                   429: 'Work key setup is busy. Try again later.',
                   503: 'Work key setup is unavailable. Try again later.'}.get(exc.status)
        if message is None:
            message = ('This work account does not have Router access. Contact IT.'
                       if exc.code == 'access_denied' else
                       'Work account sign-in did not finish. Try again or contact IT.')
        raise SignInFailed(message) from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SignInFailed('Your work key could not be prepared. Try again or contact IT.') from None


def _ask(dialog, tool_path, platform_name, question, items, run):
    result = run(dialog.argv(tool_path, platform_name, question, items),
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 text=True, timeout=key_dialog.TIMEOUT_S)
    if (platform_name.startswith('linux') and result.returncode == 1
            and 'cannot open display' in (result.stderr or '').lower()):
        raise OSError('The setup window has no display.')
    text = (result.stdout or '').strip()
    cancelled = (not text and result.returncode == 0 if platform_name == 'darwin'
                 else result.returncode == (2 if platform_name == 'win32' else 1))
    if cancelled:
        return CANCELLED
    answer = dialog.answer(platform_name, text, items)
    if result.returncode or answer is None:
        raise OSError('The setup window could not finish.')
    return answer


def collect(tool_path, platform_name, clients, run=None, issue=None):
    """Use the shared two-action chooser for sign-in and assistant choices."""
    run = run or subprocess.run
    dialog = _load('client_dialog')
    method = _ask(dialog, tool_path, platform_name, 'How do you want to connect?', CHOICES, run)
    if method is CANCELLED:
        return CANCELLED
    if method == 'key':
        return MANUAL
    fields = {'key': (issue or provision)()}
    for field, question, answers in key_dialog.questions(clients):
        table = key_dialog.STARTERS if field == 'profile' else key_dialog.MODES
        items = tuple((table[label], label) for label in answers)
        value = _ask(dialog, tool_path, platform_name, question, items, run)
        if value is CANCELLED:
            return CANCELLED
        fields[field] = value
    return fields
