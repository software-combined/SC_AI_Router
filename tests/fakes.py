"""Recording fake upstream for handler characterisation tests.

Never opens a network connection. Patch target is
http.client.HTTPSConnection as used by ai_router.router.
"""
import http.client
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace
from unittest import mock

def install_payloads(version):
    rules = Path(__file__).resolve().parents[1] / 'tools' / 'global_instructions.py'
    return {'packaging/VERSION': (version + '\n').encode(),
            'packaging/router_launch.py': b'# launcher\n',
            'packaging/update_launch.py': b"# update launcher '--express-only'\n",
            'packaging/install.py': b'# installer stub\n',
            'tools/global_instructions.py': rules.read_bytes()}


class LaunchdDomain:
    """Stateful stand-in for a launchd user domain.

    The previous fake answered every `launchctl` call with rc 0, including
    `print` for labels that had just been booted out. That hid the defect this
    class exists to reproduce: `bootout` returns before the job leaves the
    domain, so an immediate `bootstrap` fails and the label ends up loaded
    nowhere. Tests drive `loaded` and `program` to model a real machine.
    """

    DEFAULT_PROGRAM = '/opt/homebrew/bin/python3.14'

    def __init__(self):
        self.reset()

    def reset(self, program=None, bootstrap_failures=0, unload_lag=0,
              unloaded=(), commands=None):
        # Labels start loaded: an upgrade runs against a live service.
        self.unloaded = set(unloaded)
        express = 'com.local.codex-mixed-model-router.update.express'
        if not commands or express not in commands:
            self.unloaded.add(express)  # Legacy hosts have no Express job yet.
        self.program = program or self.DEFAULT_PROGRAM
        # What launchd has *loaded*, per label. Recorded at bootstrap from the
        # plist as it read at that moment, so rewriting the file afterwards
        # does not change it -- the staleness that let the updater keep
        # invoking a pruned release's installer.
        self.commands = dict(commands or {})
        self.bootstrap_failures = bootstrap_failures
        self.unload_lag = unload_lag
        self._lag_left = {}
        return self

    @staticmethod
    def _label(spec):
        # 'gui/501/com.local.x' -> 'com.local.x'; a plist path -> its stem.
        tail = spec.rsplit('/', 1)[-1]
        return tail[:-len('.plist')] if tail.endswith('.plist') else tail

    def loaded(self, label):
        return label not in self.unloaded

    def __call__(self, cmd, **kwargs):
        ok = SimpleNamespace(returncode=0, stdout='', stderr='')
        if cmd[:1] != ['launchctl']:
            return None
        verb = cmd[1] if len(cmd) > 1 else ''
        if verb == 'bootout':
            label = self._label(cmd[2])
            # bootout reports success while teardown is still in progress.
            self._lag_left[label] = self.unload_lag
            if self.unload_lag == 0:
                self.unloaded.add(label)
            return ok
        if verb == 'bootstrap':
            label = self._label(cmd[-1])
            if self.bootstrap_failures > 0:
                self.bootstrap_failures -= 1
                return SimpleNamespace(returncode=5, stdout='',
                                       stderr='Bootstrap failed: 5: Input/output error')
            self.unloaded.discard(label)
            try:
                doc = plistlib.loads(Path(cmd[-1]).read_bytes())
                self.commands[label] = list(doc['ProgramArguments'])
            except (OSError, ValueError, KeyError, TypeError):
                self.commands.pop(label, None)
            return ok
        if verb == 'print':
            label = self._label(cmd[2])
            left = self._lag_left.get(label)
            if left:
                self._lag_left[label] = left - 1
                if self._lag_left[label] == 0:
                    self.unloaded.add(label)
            if not self.loaded(label):
                return SimpleNamespace(returncode=1, stdout='',
                                       stderr='Could not find service')
            argv = self.commands.get(label)
            if not argv:
                # launchd reports a bare program with no arguments block.
                return SimpleNamespace(
                    returncode=0, stderr='',
                    stdout=f'\tstate = running\n\tprogram = {self.program}\n')
            block = ''.join(f'\t\t{token}\n' for token in argv)
            return SimpleNamespace(
                returncode=0, stderr='',
                stdout=(f'\tstate = running\n\tprogram = {argv[0]}\n'
                        f'\targuments = {{\n{block}\t}}\n'))
        return ok


LAUNCHD = LaunchdDomain()


def launchd_in_sync(home, label, update_label):
    """Stage launchd as already running what an install would render.

    Without this a label that starts loaded reports a bare program, which is
    correctly read as "the loaded command is not the one we want" and sends
    the installer down the reload path. Tests that exercise the in-place
    handover have to say what launchd actually has loaded.
    """
    program = LaunchdDomain.DEFAULT_PROGRAM
    return LAUNCHD.reset(program=program, commands={
        label: [program, str(Path(home) / 'router_launch.py')],
        update_label: [program, str(Path(home) / 'update_launch.py')],
        update_label + '.express': [program, str(Path(home) / 'express_launch.py')]})


class FakeUpstream:
    def __init__(self, status, body_bytes, headers=()):
        self.status = status
        self._buf = body_bytes
        self._headers = list(headers)
        self._pos = 0

    def getheaders(self):
        return list(self._headers)

    def getheader(self, name, default=None):
        return next((v for k, v in self._headers if k.lower() == name.lower()), default)

    def read(self, amt=None):
        if amt is None:
            amt = len(self._buf) - self._pos
        data = self._buf[self._pos:self._pos + amt]
        self._pos += len(data)
        return data

    def read1(self, count):
        return self.read(count)

    def __iter__(self):
        return iter(self._buf.splitlines(keepends=True))


def install_fake(test, responder):
    """Patch HTTPSConnection; record (host, method, path, body, headers)."""
    # A fake upstream answers from stubs, so process-local refusal verdicts
    # cached against the real upstream no longer apply; drop them with the
    # patch (and on cleanup) so stubbed responses are actually dispatched.
    from ai_router import upstream as _upstream
    _upstream.clear_refusals()
    test.addCleanup(_upstream.clear_refusals)
    recorded = []

    class FakeConn:
        def __init__(self, host, *args, **kwargs):
            self._host = host

        def connect(self):
            # Mirrors HTTPSConnection.connect(): establishes the upstream
            # transport before request upload. Kept explicit so phase
            # attribution can time connection separately from send.
            pass

        def request(self, method, path, body=None, headers=None):
            recorded.append((self._host, method, path, body, headers))

        def getresponse(self):
            return responder()

        def close(self):
            pass

    patcher = mock.patch.object(http.client, 'HTTPSConnection', FakeConn)
    test.addCleanup(patcher.stop)
    patcher.start()
    return recorded


def static_fetch(latest, blob):
    """Fake fetcher serving a feed doc and a bundle."""
    body = json.dumps(latest).encode()

    def fake_fetch(url):
        return body if url.endswith('.json') else blob

    return fake_fetch
