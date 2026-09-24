"""The update dialog lists each new model once and is silent otherwise.

These checks run the real updater and notice modules against a real router
over loopback. Only the desktop dialog is faked, and a dialog counts once it
is actually spawned.
"""
import contextlib
import json
import unittest
from dataclasses import replace
from unittest import mock

from ai_router import catalogue, model_prompt
from ai_router.credentials import Credentials
from ai_router.registry import MODELS, by_slug
from tests.harness import start_server, tmp_home
from tests.install_fixtures import install_mod


def _models(*numbers):
    """Registry rows plus one synthetic visible row per number."""
    return tuple(MODELS) + tuple(
        replace(by_slug('z-ai/glm-5.3-flash'), slug=f'openrouter/acme-model-{n}',
                display_name=f'Acme: Model {n} · OpenRouter') for n in numbers)


class DialogOnceTests(unittest.TestCase):
    def setUp(self):
        self.home = tmp_home(self)
        state = {'port': 0, 'token': 'test-token', 'openai_models': []}
        server = start_server(state, credentials=Credentials(state, self.home, env={}))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.state = dict(state, port=server.server_port, clients='codex')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))
        model_prompt.pending(self.home)  # seed today's rows
        self.notice = install_mod._svc.notice
        self.dialogs = []

    @contextlib.contextmanager
    def _desktop(self, models, tool=True, still_open=False):
        """The router serves `models`; each spawned dialog records its names.

        `still_open` keeps the last dialog on screen, so a new one would stack.
        """
        def command(version, **kwargs):
            return ['fake-dialog', kwargs['names']] if tool else None

        def spawn(cmd):
            self.dialogs.append(cmd[1])
            return 4321
        with mock.patch.object(catalogue, 'MODELS', models), \
                mock.patch.object(self.notice, 'dialog_command', command), \
                mock.patch.object(self.notice, '_spawn', spawn), \
                mock.patch.object(self.notice, '_dialog_up', return_value=True), \
                mock.patch.object(self.notice, '_pid_alive', lambda pid: still_open):
            yield

    def _install(self, previous, version, models):
        """The new release's installer stages its notice, then shows it."""
        with self._desktop(models):
            self.notice.record(self.home, previous, version, 'codex')
            self.notice.show_pending(self.home)

    def _check(self, version, models, **desktop):
        """The updater's pass after an install, or a check that installs nothing."""
        updater = install_mod._updater
        with self._desktop(models, **desktop), mock.patch.object(
                updater._svc, 'current_version', return_value=version):
            updater._announce_new_models(self.home, self.state)

    def test_the_updater_lists_new_models_once(self):
        first, later = _models(1, 2, 3, 4), _models(1, 2, 3, 4, 5)
        self._check('1.0.1', first, tool=False)  # nothing shown: stays pending
        self._check('1.0.1', first)
        self._check('1.0.2', first)  # a later update with nothing new
        self._check('1.0.2', first)  # a check that installs nothing
        self._check('1.0.3', later)  # a genuinely new model
        self._check('1.0.4', later)
        self.assertEqual(self.dialogs, [
            ['Acme: Model 1', 'Acme: Model 2', 'Acme: Model 3', '+1 more'],
            ['Acme: Model 5']])

    def test_a_model_that_arrives_while_a_dialog_is_open_is_listed_later(self):
        self._check('1.0.1', _models(1))
        self._check('1.0.2', _models(1, 2), still_open=True)  # never stacked
        self._check('1.0.2', _models(1, 2))  # the first dialog was closed
        self._check('1.0.3', _models(1, 2))
        self.assertEqual(self.dialogs, [['Acme: Model 1'], ['Acme: Model 2']])

    def test_an_update_without_a_new_model_shows_nothing(self):
        models = _models(1)
        self._install('1.0.0', '1.0.1', models)  # this release adds a model
        self._check('1.0.1', models)
        # No picker file here, so the installer stages its notice anyway.
        self._install('1.0.1', '1.0.2', models)
        self._check('1.0.2', models)
        self.assertEqual(self.dialogs, [['Acme: Model 1']])

    def test_models_a_dialog_listed_before_this_fix_are_not_listed_again(self):
        (self.home / 'update-notice.json').write_text(json.dumps(
            {'version': '1.0.1', 'shown': True, 'names': ['Acme: Model 1']}))
        with self._desktop(_models(1)):  # still waiting at the router
            self.notice.show_pending(self.home)  # the next installer, nothing staged
        self._check('1.0.2', _models(1))
        self.assertEqual(self.dialogs, [])


if __name__ == '__main__':
    unittest.main()
