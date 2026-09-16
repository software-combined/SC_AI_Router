"""The client contract (Plan 155): one table, two projections, fail closed.

`clients/registry.py` is the only owner of who sees what. These checks keep
its rows honest against the protocol table the router actually dispatches on,
prove both projections read the table rather than a literal, and prove every
consumer refuses an unknown client.
"""
import subprocess
import sys
import unittest
from unittest import mock

from ai_router import clients, provider_defs, protocols, registry
from ai_router.clients import registry as client_table
from ai_router.clients import roster
from tests.install_fixtures import install_mod


def _served_protocols():
    """Protocol names the request path dispatches on, in table order."""
    return tuple(dict.fromkeys(entry['policy'].name for entry in protocols.TABLE))


class ClientContractTests(unittest.TestCase):
    def test_every_row_has_a_protocol_the_router_serves(self):
        served = _served_protocols()
        for defn in client_table.CLIENTS:
            with self.subTest(client=defn.id):
                self.assertIn(defn.protocol, served)

    def test_every_served_protocol_has_a_client(self):
        claimed = {defn.protocol for defn in client_table.CLIENTS}
        for name in _served_protocols():
            with self.subTest(protocol=name):
                self.assertIn(name, claimed)

    def test_the_table_names_the_provider_defs_constants(self):
        names = {defn.protocol for defn in client_table.CLIENTS}
        self.assertLessEqual(names, {provider_defs.RESPONSES, provider_defs.MESSAGES})

    def test_the_roster_leaf_matches_the_table(self):
        self.assertEqual(tuple(d.id for d in client_table.CLIENTS), roster.CLIENT_IDS)
        self.assertIn(roster.DEFAULT_CLIENT, roster.CLIENT_IDS)

    def test_both_projections_resolve_every_row(self):
        row = registry.MODELS[0]
        for defn in client_table.CLIENTS:
            with self.subTest(client=defn.id):
                self.assertIsInstance(clients.visible_for(row, defn.id), bool)
                self.assertIsInstance(defn.discovery_visible(row), bool)

    def test_a_synthetic_third_client_is_covered(self):
        # A temp row proves the checks above read the table rather than a
        # literal list, the way tests/test_domain_boundaries.py proves its
        # detector is not vacuous.
        extra = client_table.ClientDef(
            id='cursor', label='Cursor', protocol=provider_defs.RESPONSES,
            picker_visible=lambda model, include_twins=False: True,
            discovery_visible=lambda model: True)
        saved = (client_table.CLIENTS, client_table.BY_ID)
        self.addCleanup(setattr, client_table, 'CLIENTS', saved[0])
        self.addCleanup(setattr, client_table, 'BY_ID', saved[1])
        client_table.CLIENTS = saved[0] + (extra,)
        client_table.BY_ID = {c.id: c for c in client_table.CLIENTS}
        self.assertEqual(client_table.client_ids(),
                         ('codex', 'claude', 'cursor'))
        self.assertIn('cursor', clients.client_ids())
        self.assertTrue(clients.visible_for(registry.MODELS[0], 'cursor'))

    def test_unknown_client_fails_closed_everywhere(self):
        with self.assertRaises(ValueError):
            clients.visible_for(registry.MODELS[0], 'nope')
        with self.assertRaises(ValueError):
            clients.models_for(registry.MODELS, 'nope')
        self.assertIsNone(client_table.get('nope'))
        proc = subprocess.run(
            [sys.executable, '-m', 'ai_router.catalogue', '--client', 'nope',
             '--check', 'x'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn('usage:', proc.stderr + proc.stdout)

    def test_the_installer_options_are_derived_and_unchanged(self):
        # The option strings are a user-facing contract: recipients' scripts
        # and the plugin manifests depend on them, so they must not move. The
        # derivation is proven by widening the roster leaf and watching the
        # option list follow it.
        roster_mod = install_mod._client_roster

        def choices(module):
            parser = module.build_parser()
            return {action.dest: tuple(action.choices)
                    for action in parser._actions
                    if action.dest in ('client', 'clients')}

        self.assertEqual(choices(install_mod),
                         {'client': ('codex', 'none'),
                          'clients': ('codex', 'claude', 'both')})
        with mock.patch.object(roster_mod, 'CLIENT_IDS',
                               roster_mod.CLIENT_IDS + ('cursor',)):
            self.assertEqual(choices(install_mod)['clients'],
                             ('codex', 'claude', 'cursor', 'both'))


if __name__ == '__main__':
    unittest.main()
