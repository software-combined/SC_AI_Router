"""Lossless ownership proof covers ambiguous JSON and interrupted restoration."""
import unittest

from tests.test_native_setup import module

owned = module('owned_json')


class OwnedJsonTests(unittest.TestCase):
    def test_unrelated_members_and_formatting_survive_removing_owned_values(self):
        before = ('{\r\n "env" : { "A": "router", "keep": [1,  2], '
                  '"B":"owned", "escaped\\u005fkey": "\\u00e9" },\r\n'
                  ' "tools": {"enabled": false}\r\n}\r\n')
        after = owned.restore(before, ('env',), {'A': 'router', 'B': 'owned'},
                              {'A': None, 'B': None})
        self.assertEqual(after, ('{\r\n "env" : { "keep": [1,  2], '
                                 '"escaped\\u005fkey": "\\u00e9" },\r\n'
                                 ' "tools": {"enabled": false}\r\n}\r\n'))

    def test_every_removal_run_keeps_a_valid_object(self):
        # First, last, adjacent, separated and all members exercise comma ownership.
        import itertools
        before = '{ "A": 1, "B": 2, "C": 3, "D": 4 }\n'
        for count in range(1, 5):
            for selected in itertools.combinations('ABCD', count):
                with self.subTest(selected=selected):
                    written = {key: 'ABCD'.index(key) + 1 for key in selected}
                    after = owned.restore(before, (), written, dict.fromkeys(selected))
                    self.assertEqual(owned.document(after),
                                     {key: value for key, value in owned.document(before).items()
                                      if key not in selected})

    def test_restores_only_recorded_values_and_can_retry_partial_restoration(self):
        before = '{"A":"router","B":"original","keep" : true}\n'
        written = {'A': 'router', 'B': 'router'}
        previous = {'A': 'original', 'B': 'original'}
        after = owned.restore(before, (), written, previous)
        self.assertEqual(after, '{"A":"original","B":"original","keep" : true}\n')
        self.assertEqual(owned.restore(after, (), written, previous), after)
        absent = '{ "keep" : [] }'
        self.assertEqual(owned.restore(absent, ('env',), {'A': 'router'}, {'A': None}), absent)

    def test_changed_connection_or_null_is_not_absence(self):
        for before in ('{"A":"user"}', '{"A":null}', '{}'):
            with self.subTest(before=before), self.assertRaisesRegex(owned.Conflict, 'connection_changed'):
                owned.restore(before, (), {'A': 'router'}, {'A': 'previous'})
        with self.assertRaisesRegex(owned.Conflict, 'connection_changed'):
            owned.restore('{"A":null}', (), {'A': 'router'}, {'A': None})

    def test_duplicate_keys_include_escaped_spellings_and_nested_objects(self):
        for before in ('{"A":1,"A":2}', '{"A":1,"\\u0041":2}',
                       '{"env":{"A":1,"A":1}}'):
            with self.subTest(before=before), self.assertRaisesRegex(owned.Conflict, 'duplicate_keys'):
                owned.restore(before, (), {'A': 1}, {'A': None})

    def test_unsupported_json_and_scope_refuse(self):
        for before in ('[]', 'null', '{bad', '{"env":null}', '{"env":[]}', '{"env":{"A":NaN}}'):
            with self.subTest(before=before), self.assertRaises(owned.Conflict):
                owned.restore(before, ('env',), {'A': 1}, {'A': None})

    def test_damaged_snapshot_never_grants_empty_restore_authority(self):
        for value in (None, '{}', '[]', '{broken', '{"A":null,"A":null}'):
            with self.subTest(value=value), self.assertRaisesRegex(owned.Conflict, 'damaged_receipt'):
                owned.snapshot(value, ('A',))
        self.assertEqual(owned.snapshot('{"A":null}', ('A',)), {'A': None})

    def test_callback_removal_preserves_surviving_items_and_can_retry(self):
        for items in ('1, {"owned":true},  [2,  3]',
                      '{"owned":true},  [2,  3]',
                      '[2,  3], {"owned":true}', '{"owned":true}'):
            with self.subTest(items=items):
                before = '{\r\n "hooks" : {"SessionStart": [' + items + ']}, "keep" : "\\u00e9"\r\n}\r\n'
                after = owned.remove_item(before, ('hooks', 'SessionStart'), {'owned': True})
                self.assertNotIn('owned', after)
                self.assertIn('"keep" : "\\u00e9"\r\n}\r\n', after)
                if '[2,  3]' in before:
                    self.assertIn('[2,  3]', after)
                self.assertEqual(owned.remove_item(after, ('hooks', 'SessionStart'), {'owned': True}), after)
        self.assertEqual(owned.remove_item('{}', ('hooks', 'SessionStart'), {}), '{}')

    def test_duplicate_callback_is_ambiguous(self):
        with self.assertRaisesRegex(owned.Conflict, 'ambiguous_callback'):
            owned.remove_item('{"hooks":{"SessionStart":[{},{}]}}', ('hooks', 'SessionStart'), {})
