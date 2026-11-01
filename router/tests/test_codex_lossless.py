"""Preference and reviewer edits preserve unrelated bytes on every client newline style."""
import unittest

from tests.install_fixtures import install_mod

owner = install_mod._codex_config


class CodexLosslessTests(unittest.TestCase):
    def test_preference_update_and_restore_preserve_unrelated_bytes_and_comments(self):
        for ending in ('\n', '\r\n'):
            with self.subTest(ending=repr(ending)):
                prefix = '# Person note' + ending + 'person_setting = "\\u00e9"' + ending
                suffix = 'person_window = "wide"' + ending + '[features]' + ending + 'example = true'
                before = (prefix + '[desktop]' + ending + '  ' + owner.QUEUE_KEY
                          + ' = "queue"   # keep queue note' + ending
                          + suffix)
                changed, record = owner.desktop_preferences(before)
                self.assertTrue(changed.startswith(prefix))
                self.assertIn('person_window = "wide"' + ending, changed)
                self.assertTrue(changed.endswith('[features]' + ending + 'example = true'))
                self.assertIn('   # keep queue note' + ending, changed)
                self.assertEqual(owner.desktop_preferences(changed)[0], changed)
                restored = owner.restore_desktop(changed, record)
                self.assertEqual(restored, before)

    def test_mixed_newlines_and_unterminated_user_line_survive_value_replacement(self):
        text = ('person = true\r\n[desktop]\n' + owner.QUEUE_KEY
                + '="steer" # saved note\r\n' + owner.EFFORTS_KEY
                + ' = ["low", "medium", "high", "xhigh", "max", "persistent"]\n'
                + 'person_window = "wide"')
        changed, record = owner.desktop_preferences(text)
        self.assertEqual(changed, text)
        self.assertEqual(owner.restore_desktop(changed, record), text)

    def test_new_owned_lines_do_not_rewrite_existing_user_lines(self):
        text = 'person = true\r\n[desktop]\r\nperson_window = "wide"\r\n'
        changed, record = owner.desktop_preferences(text)
        self.assertTrue(changed.startswith(text))
        self.assertEqual(owner.restore_desktop(changed, record), text)

    def test_reviewer_restore_inserts_only_recorded_lines(self):
        text = '# note\r\nperson = true\r\n[features]\r\nexample = true'
        recorded = 'model_provider = "prior" # previous choice'
        restored = owner.restore_reviewer(text, {'removed': [recorded]})
        self.assertEqual(restored, text.replace('[features]', recorded + '\r\n[features]'))
        self.assertEqual(owner.restore_reviewer(restored, {'removed': [recorded]}), restored)

    def test_appended_preferences_restore_an_unterminated_user_line_and_existing_empty_table(self):
        for text in ('person = true', '[desktop]', '[desktop]\r\n# keep note'):
            with self.subTest(text=text):
                changed, record = owner.desktop_preferences(text)
                changed_again, retained = owner.desktop_preferences(changed, record['previous'], record)
                self.assertEqual(changed_again, changed)
                self.assertEqual(owner.restore_desktop(changed_again, retained), text)

    def test_unproven_empty_table_and_later_user_newline_are_preserved(self):
        changed, record = owner.desktop_preferences('person = true')
        changed += 'later = true\n'
        self.assertTrue(owner.restore_desktop(changed, record).endswith('later = true\n'))
        changed, record = owner.desktop_preferences('[desktop]\n')
        record.pop('created', None)
        self.assertEqual(owner.restore_desktop(changed, record), '[desktop]\n')
