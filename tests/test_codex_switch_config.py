"""Switch Codex blocks: the three variants, receipt truth, updates and refusals.

The receipt records which variant the managed block is, every attach rebuilds
that one, `switch` changes it with the config and receipt kept in step, and
detach, uninstall, service-only and rollback refuse while Codex is switched.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, _static_fetch, install_mod
from tests.test_install_config import _fake_write_catalogue, _install

# The instance the installer's attach path uses.
switch = install_mod._client_choice._switch
DISABLE = Path(__file__).resolve().parents[1] / 'tools' / 'disable.py'
STATE = {'port': 4321, 'token': 'tok'}
URL = 'http://127.0.0.1:4321/tok/backend-api/codex'
BEGIN, END = '# BEGIN local mixed model picker\n', '# END local mixed model picker\n'
SEEDED = 'model = "deepseek/deepseek-v4.1-flash"\nmodel_reasoning_effort = "max"\n'
# The managed approvals reviewer the default block carries (develop #347).
REVIEWER = 'approvals_reviewer = "user"\n'
PROVIDER = {'name': 'SC router', 'base_url': URL, 'wire_api': 'responses'}
OWNER = ('\nowner_setting = 1\n[model_providers.other]\nname = "x"\n'
         '[desktop]\nfollowUpQueueMode = "steer"\n')


class VariantBlockTests(unittest.TestCase):
    def test_default_is_todays_block_byte_for_byte(self):
        # Never-switched installs and older Codex builds must see no change.
        cases = {
            ('subscription', False): (BEGIN + f'openai_base_url = "{URL}"\n'
                                      + REVIEWER + END),
            ('subscription', True): (BEGIN + f'openai_base_url = "{URL}"\n'
                                     'model_catalog_json = "/r/mixed-models.json"\n'
                                     + REVIEWER + END),
            ('none', False): (BEGIN + 'model_provider = "scg_router"\n'
                              'model_catalog_json = "/r/mixed-models.json"\n'
                              'approvals_reviewer = "user"\n[model_providers.scg_router]\n'
                              f'name = "SC router"\nbase_url = "{URL}"\n'
                              'wire_api = "responses"\n' + END),
        }
        for (mode, static), want in cases.items():
            with self.subTest(mode=mode, static=static):
                self.assertEqual(switch.build('/r', STATE, mode, static, 'default'), want)

    def test_each_variant_is_valid_toml_with_exactly_its_keys(self):
        want = {
            'default': {'openai_base_url': URL, 'approvals_reviewer': 'user'},
            'switched': {
                'openai_base_url': URL, 'model_provider': 'scg_router',
                'model_catalog_json': '/r/routed-models.json', 'approvals_reviewer': 'user',
                'model_providers': {'scg_router': dict(
                    PROVIDER, requires_openai_auth=False,
                    http_headers={'x-scg-codex-route': 'routed'})}},
            'switched_back': {
                'openai_base_url': URL, 'approvals_reviewer': 'user',
                'model_providers': {'scg_router': dict(PROVIDER, requires_openai_auth=True)}},
        }
        for variant, keys in want.items():
            with self.subTest(variant=variant):
                block = switch.build('/r', STATE, 'subscription', False, variant)
                self.assertTrue(block.startswith(BEGIN) and block.endswith(END))
                self.assertEqual(tomllib.loads(block), keys)
                # Root keys only: the owner's own keys and tables that follow
                # the block still parse where the owner put them.
                merged = tomllib.loads(block + OWNER)
                self.assertEqual(merged['owner_setting'], 1)
                self.assertEqual(merged['model_providers'].get('other'), {'name': 'x'})

    def test_switched_back_without_a_subscription_keeps_one_provider(self):
        # That block already defines scg_router with sign-in off; a second
        # definition would make the whole config unreadable.
        block = switch.build('/r', STATE, 'none', False, 'switched_back')
        self.assertEqual(block, switch.build('/r', STATE, 'none', False, 'default'))
        self.assertEqual(tomllib.loads(block)['model_providers']['scg_router']['base_url'], URL)

    def test_router_owned_names_match_their_owners(self):
        from ai_router import codex_route, routed_models
        self.assertEqual(switch.HEADER, codex_route.HEADER)
        self.assertEqual(switch.ROUTED_LIST, routed_models.NAME)


class ReceiptTests(unittest.TestCase):
    def test_variant_round_trips_through_the_receipt(self):
        codex = switch._codex
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertIsNone(switch.current(home))
            codex.write_receipt(home, '/c/config.toml', 'block', None, 'subscription', '')
            self.assertNotIn('variant', codex.codex_attachment(home))
            self.assertEqual(switch.current(home), 'default')
            for variant in ('switched', 'switched_back'):
                codex.write_receipt(home, '/c/config.toml', 'block', None, 'subscription',
                                    '', variant=variant)
                self.assertEqual(codex.codex_attachment(home)['variant'], variant)
                self.assertEqual(switch.current(home), variant)
            codex.write_client_receipt(home, 'codex', dict(
                codex.codex_attachment(home), variant='sideways'))
            with self.assertRaisesRegex(SystemExit, 'changed by hand'):
                switch.current(home)


def _receipt(home):
    return (home / 'activation.json').read_text()


def _entry(home):
    return json.loads(_receipt(home))['clients']['codex']


@unix_only
class SwitchFlowTests(unittest.TestCase):
    def _attached(self, tmp, *versions):
        home = Path(tmp) / 'home'
        for version in versions or ('1.0.0',):
            config, _, _, _ = _install(self, tmp, home, version)
        return home, config

    def test_never_switched_updates_keep_todays_block_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, config = self._attached(tmp, '1.0.0', '1.0.1')
            state = json.loads((home / 'mixed-router-state.json').read_text())
            url = 'http://127.0.0.1:%s/%s/backend-api/codex' % (state['port'], state['token'])
            entry = _entry(home)
            self.assertNotIn('variant', entry)
            self.assertEqual(entry['inserted_block'],
                             BEGIN + f'openai_base_url = "{url}"\n' + REVIEWER + SEEDED + END)
            self.assertTrue(config.read_text().startswith(entry['inserted_block']))

    def test_every_variant_keeps_one_reviewer_line_and_the_owners_for_detach(self):
        # Attach moves the owner's own line into the receipt, so each block
        # must carry the managed one: no line at all could leave Codex on an
        # automatic reviewer the switched route refuses.
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
            config.parent.mkdir(parents=True)
            config.write_text('approvals_reviewer = "auto_review"\n')
            home, config = self._attached(tmp)
            moved = {'removed': ['approvals_reviewer = "auto_review"']}
            for variant in ('switched', 'switched_back', 'switched'):
                with self.subTest(variant=variant):
                    switch.switch(home, variant)
                    lines = [line for line in config.read_text().splitlines()
                             if line.startswith('approvals_reviewer')]
                    self.assertEqual(lines, ['approvals_reviewer = "user"'])
                    self.assertEqual(_entry(home)['reviewer'], moved)

    def test_updates_keep_switched_and_switched_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, config = self._attached(tmp)
            for variant, version in (('switched', '1.0.1'), ('switched_back', '1.0.2')):
                with self.subTest(variant=variant):
                    switch.switch(home, variant)
                    switched = config.read_text()
                    _install(self, tmp, home, version)
                    self.assertEqual(config.read_text(), switched)
                    self.assertEqual(_entry(home)['variant'], variant)
                    self.assertIn(_entry(home)['inserted_block'], switched)
                    # The owner's model pick rides through the switch and the update.
                    self.assertEqual(tomllib.loads(switched)['model'],
                                     'deepseek/deepseek-v4.1-flash')
            # The hand-edit rule holds for a switched variant too.
            edited = config.read_text().replace('openai_base_url', 'openai_base_url_edited')
            config.write_text(edited)
            with self.assertRaisesRegex(SystemExit, 'edited by hand'):
                _install(self, tmp, home, '1.0.3')
            self.assertEqual(config.read_text(), edited)

    def test_switch_writes_block_and_receipt_together_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, config = self._attached(tmp)
            before, receipt = config.read_text(), _receipt(home)
            with mock.patch.object(switch._codex, 'write_client_receipt',
                                   side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    switch.switch(home, 'switched')
            self.assertEqual(config.read_text(), before)
            self.assertEqual(_receipt(home), receipt)
            switch.switch(home, 'switched')
            doc = tomllib.loads(config.read_text())
            self.assertEqual(doc['model_provider'], 'scg_router')
            self.assertEqual(doc['desktop']['followUpQueueMode'], 'steer')
            self.assertEqual(_entry(home)['variant'], 'switched')
            self.assertEqual(config.read_text().count(_entry(home)['inserted_block']), 1)
            self.assertEqual(switch.current(home), 'switched')

    def test_switch_refuses_hand_edits_and_unattached_homes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, config = self._attached(tmp)
            original, receipt = config.read_text(), _receipt(home)
            for label, text in (
                    ('edited', original.replace('openai_base_url', 'openai_base_url_edited')),
                    ('removed', 'owner_setting = 1\n'),
                    ('doubled', original + original)):
                with self.subTest(label):
                    config.write_text(text)
                    with self.assertRaisesRegex(SystemExit, 'changed by hand'):
                        switch.switch(home, 'switched')
                    self.assertEqual(config.read_text(), text)
                    self.assertEqual(_receipt(home), receipt)
            with self.assertRaises(ValueError):
                switch.switch(home, 'default')
            with self.assertRaisesRegex(SystemExit, 'not connected'):
                switch.switch(Path(tmp) / 'elsewhere', 'switched')


def _real_remover(cmd, **kwargs):
    """Run the real tools/disable.py for the installer; fake everything else."""
    if len(cmd) > 1 and Path(cmd[1]).name == 'disable.py':
        proc = subprocess.run(cmd, capture_output=True, text=True, env=kwargs.get('env'))
        return SimpleNamespace(returncode=proc.returncode, stdout=proc.stdout,
                               stderr=proc.stderr)
    return _ok_run(cmd, **kwargs)


@unix_only
class SwitchedRefusalTests(unittest.TestCase):
    def test_detach_uninstall_service_only_and_rollback_refuse_while_switched(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            fakehome = {'HOME': str(Path(tmp) / 'fakehome')}
            _install(self, tmp, home, '1.0.0')
            config, _, _, _ = _install(self, tmp, home, '1.0.1')
            switch.switch(home, 'switched')
            switched, receipt = config.read_text(), _receipt(home)
            remover = subprocess.run(
                [sys.executable, str(DISABLE)], capture_output=True, text=True,
                env=dict(os.environ, ROUTER_HOME=str(home), ROUTER_RESTORE_ONLY='1'))
            self.assertNotEqual(remover.returncode, 0)
            self.assertIn(switch.SWITCHED_REFUSAL, remover.stderr)
            calls = []

            def recording(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=recording)
            with mock.patch.dict(os.environ, fakehome):
                with self.assertRaisesRegex(SystemExit, 'Open Switch Codex'):
                    install_mod.do_uninstall(
                        install_mod.build_parser().parse_args(['--home', str(home)]))
                with self.assertRaisesRegex(SystemExit, 'Open Switch Codex'):
                    install_mod.do_install(install_mod.build_parser().parse_args(
                        ['--home', str(home), '--version', '1.0.0']))
            self.assertFalse([cmd for cmd in calls if 'disable.py' in ' '.join(cmd)
                              or 'bootout' in cmd or 'kill' in cmd], calls)
            self.assertEqual(install_mod.current_version(home), '1.0.1')
            # Service-only reaches the real remover, which refuses the detach.
            blob, latest = _craft_bundle('1.0.2')
            _patch_attrs(self, run=_real_remover, self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home), '--clients', 'none'])
            out = io.StringIO()
            with mock.patch.dict(os.environ, dict(fakehome, OPENROUTER_API_KEY='k',
                                                  ROUTER_NO_KEY_WINDOW='1')):
                with self.assertRaisesRegex(SystemExit, 'refusing the client change'):
                    with contextlib.redirect_stdout(out):
                        install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            self.assertIn(switch.SWITCHED_REFUSAL, out.getvalue())
            self.assertEqual(config.read_text(), switched)
            self.assertEqual(_receipt(home), receipt)
            # Once switched back, the same remover detaches as before.
            switch.switch(home, 'switched_back')
            block = _entry(home)['inserted_block']
            remover = subprocess.run(
                [sys.executable, str(DISABLE)], capture_output=True, text=True,
                env=dict(os.environ, ROUTER_HOME=str(home), ROUTER_RESTORE_ONLY='1'))
            self.assertEqual(remover.returncode, 0, remover.stderr)
            self.assertNotIn(block, config.read_text())

    def test_an_unreadable_receipt_never_blocks_a_rollback(self):
        # Rollback is the recovery path and never read the receipt before.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0')
            switch.switch(home, 'switched')
            (home / 'activation.json').write_text('{not json')
            self.assertIsNone(switch.refuse_switched(home))


if __name__ == '__main__':
    unittest.main()
