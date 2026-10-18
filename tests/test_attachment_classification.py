"""Sharing the ownership result never shares settings, paths or credentials."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

from tests.test_native_setup import module

spec = importlib.util.spec_from_file_location('classify_attachments',
    Path(__file__).resolve().parents[1] / 'tools/classify_attachments.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class AttachmentClassificationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_removal_recovery import RemovalRecoveryTests
        self.rig = RemovalRecoveryTests()
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)

    def test_owned_report_is_redacted_and_read_only(self):
        paths = (self.rig.config, self.rig.settings, self.rig.home / 'activation.json')
        before = [path.read_bytes() for path in paths]
        result = report.classify(self.rig.home)
        self.assertEqual(result, {'schema': 1, 'receipt': 'readable', 'clients': {
            'codex': {'classification': 'owned'}, 'claude': {'classification': 'owned'}}})
        for private in (str(self.rig.home), 'synthetic-test', 'person_setting', '127.0.0.1'):
            self.assertNotIn(private, json.dumps(result))
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_connection_and_toml_conflicts_have_specific_redacted_reasons(self):
        before = self.rig.config.read_text()
        for changed, reason in ((before.replace('127.0.0.1:1234', '127.0.0.1:9999'), 'connection_changed'),
            (before.replace(self.rig.owner.END, 'openai_base_url="private-value"\n' + self.rig.owner.END), 'invalid_toml')):
            with self.subTest(reason=reason):
                self.rig.config.write_text(changed)
                result = report.classify(self.rig.home)
                self.assertEqual(result['clients']['codex'], dict(classification='conflict', reason=reason))
                self.assertEqual(self.rig.config.read_text(), changed)
                self.assertNotIn('private-value', json.dumps(result))

    def test_bridge_reports_only_the_static_conflict_reason(self):
        owner = self.rig.owner
        removal = module('client_removal')
        self.rig.config.write_text(self.rig.config.read_text().replace('127.0.0.1:1234', '127.0.0.1:9999'))
        with mock.patch.object(report, '_load', side_effect=lambda name:
                owner if name == 'codex_config' else removal), \
                mock.patch.object(owner._owned, 'HAS_TOML', False), \
                mock.patch.object(owner._owned, 'parser_python', return_value=report.sys.executable):
            result = report.classify(self.rig.home)
        self.assertEqual(result['clients']['codex']['reason'], 'connection_changed')

    def test_damaged_nested_receipt_is_a_conflict_without_any_change(self):
        doc = self.rig.owner.read_receipt(self.rig.home)
        doc['clients']['codex']['reviewer'] = ['damaged']
        (self.rig.home / 'activation.json').write_text(json.dumps(doc))
        before = self.rig.config.read_bytes()
        result = report.classify(self.rig.home)
        self.assertEqual(result['clients']['codex'], dict(classification='conflict', reason='damaged_receipt'))
        self.assertEqual(self.rig.config.read_bytes(), before)

    def test_malformed_restore_evidence_refuses_before_repair_writes(self):
        entry = self.rig.owner.read_receipt(self.rig.home)['clients']['codex']
        before = self.rig.config.read_bytes()
        block = entry['inserted_block'].replace('1234', '4567')
        for field, value in (('reviewer', {'removed': ['one\ntwo']}),
                             ('desktop', {'written': []}),
                             ('desktop', {'written': {'person_window': 'router'}})):
            with self.subTest(field=field, value=value):
                damaged = dict(entry, **{field: value})
                with self.assertRaisesRegex(SystemExit, 'damaged_receipt'):
                    self.rig.owner.attach_config(self.rig.config, block, damaged)
                self.assertEqual(self.rig.config.read_bytes(), before)

    def test_missing_receipt_creates_nothing(self):
        home = self.rig.home / 'absent'
        self.assertEqual(report.classify(home), dict(schema=1, receipt='missing', clients={}))
        self.assertFalse(home.exists())

    def test_empty_or_unexpected_verifier_reply_never_counts_as_validation(self):
        from types import SimpleNamespace
        owned = self.rig.owner._owned
        for value in ('', '[]', '{"unexpected":"private"}'):
            with self.subTest(value=value), mock.patch.object(owned, 'HAS_TOML', False), \
                    mock.patch.object(owned, 'parser_python', return_value='managed-python'), \
                    mock.patch.object(owned, 'run', return_value=SimpleNamespace(returncode=0, stdout=value)), \
                    self.assertRaisesRegex(SystemExit, 'parser_failed'):
                owned.inspect('invalid TOML')
