"""A cached channel response cannot conceal an incomplete or parked update."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod_factory


class CacheRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.install = install_mod_factory()
        self.updater = self.install._updater
        self.state = dict(port=1, token='synthetic', last_error='installer_failed',
                          update_failures={'1.3.2.185': 3})
        self.save()
        (self.home / 'releases' / '1.2.6.174').mkdir(parents=True)
        (self.home / 'current').write_text('1.2.6.174')
        (self.home / 'channel').write_text('beta')
        (self.home / 'update-etag').write_text('cached')
        self.feed = 'file:///beta/latest.json'
        (self.home / 'feed').write_text(self.feed)
        self.args = self.install.build_parser().parse_args(
            ['--home', str(self.home), '--feed', self.feed])
        for obj, name, value in ((self.install._svc, 'health', None),
                (self.updater._models, 'refresh', None),
                (self.updater._resources, 'ready', True),
                (self.updater._resources, 'deliver', True)):
            patcher = mock.patch.object(obj, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self):
        (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))

    def run_update(self, read):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = self.install.do_update(self.args, _read_feed=read,
                _fetch=lambda url: b'', _sleep=lambda _: None,
                _announce=lambda *_: None)
        return rc, output.getvalue()

    def test_failed_parked_release_requires_full_metadata_after_a_304(self):
        calls = []
        latest = dict(version='1.3.2.185', url='file:///bundle.tar.gz')
        def read(feed, etag):
            calls.append(etag)
            return ((304, b'', 'cached') if len(calls) == 1 else
                    (200, json.dumps(latest).encode(), 'cached'))
        rc, output = self.run_update(read)
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [None, None])
        self.assertIn('skipping 1.3.2.185', output)
        self.assertNotIn('up to date', output)
        self.assertEqual(state['last_error'], 'installer_failed')
        self.assertEqual(state['update_failures'], {'1.3.2.185': 3})
        self.assertEqual(state['latest_verified']['version'], '1.3.2.185')
        self.assertTrue(state['last_successful_check_at'].endswith('Z'))

    def test_an_unbound_repeated_304_is_a_failure_not_currentness(self):
        with self.assertRaisesRegex(SystemExit, 'cached'):
            self.run_update(lambda *_: (304, b'', 'cached'))
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.assertEqual(state['last_error'], 'feed_invalid')
        self.assertNotIn('last_successful_check_at', state)

    def test_a_valid_304_records_success_without_rewriting_other_components(self):
        self.state = dict(port=1, token='synthetic')
        self.updater._status.verified(self.state, {'version': '1.2.6.174'},
                                     self.feed, 'beta', 'cached')
        self.save()
        seen = []
        def read(feed, etag):
            seen.append(etag)
            return 304, b'', 'changed-header-without-new-metadata'
        rc, output = self.run_update(read)
        self.assertEqual((rc, seen), (0, ['cached']))
        self.assertIn('up to date', output)
        doc = self.install._diag._status_document(self.home)
        self.assertEqual(doc['update']['latest_known_version'], '1.2.6.174')
        self.assertIsNotNone(doc['update']['last_successful_check_at'])
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.assertEqual(state['latest_verified']['etag'], 'cached')

    def test_current_metadata_cannot_clear_an_unrepaired_attachment_failure(self):
        latest = dict(version='1.2.6.174', url='file:///bundle.tar.gz')
        self.state['component_repairs'] = {'controls': 'failed'}
        self.save()
        rc, output = self.run_update(lambda *_: (200, json.dumps(latest).encode(), 'new'))
        self.assertEqual(rc, 0)
        self.assertNotIn('up to date', output)
        doc = self.install._diag._status_document(self.home)
        self.assertEqual(doc['update']['last_error'], 'installer_failed')
        self.assertEqual(doc['update']['component_repairs']['controls'], 'failed')
        self.assertEqual(doc['update']['required_action'], 'repair')

    def test_check_only_rejects_a_304_without_writing_anything(self):
        self.args.json = True
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(SystemExit, 'cached'):
            self.install.do_check_update(self.args,
                _read_feed=lambda *_: (304, b'', 'cached'), _sleep=lambda _: None)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_wrong_channel_and_source_hide_previous_verified_facts(self):
        self.updater._status.verified(self.state, {'version': '1.3.2.185'},
                                     self.feed, 'beta', 'cached')
        self.save()
        (self.home / 'channel').write_text('stable')
        doc = self.install._diag._status_document(self.home)
        self.assertIsNone(doc['update']['latest_known_version'])
        self.assertIsNone(doc['update']['last_successful_check_at'])

    def test_another_channels_parked_release_cannot_change_the_success_message(self):
        self.state = dict(update_failures={'1.3.2.185': 3}, update_failure_context={
            '1.3.2.185': dict(channel='stable', source=self.updater._status.source(self.feed))})
        self.save()
        latest = dict(version='1.2.6.174', url='file:///bundle.tar.gz')
        rc, output = self.run_update(lambda *_: (200, json.dumps(latest).encode(), 'cached'))
        self.assertEqual(rc, 0)
        self.assertIn('up to date', output)
        self.assertEqual(self.install._diag._status_document(self.home)['update']['failures'], {})

    def test_rollback_during_a_cached_request_refetches_the_channel_document(self):
        (self.home / 'releases/1.3.1.184').mkdir()
        (self.home / 'current').write_text('1.3.1.184')
        self.state = {}
        self.updater._status.verified(self.state, {'version': '1.3.1.184'},
                                     self.feed, 'beta', 'cached')
        self.save()
        seen = []
        latest = dict(version='1.3.1.184', url='file:///bundle.tar.gz',
                      sha256=hashlib.sha256(b'').hexdigest())
        def read(feed, etag):
            seen.append(etag)
            if len(seen) == 1:
                (self.home / 'current').write_text('1.2.6.174')
                return 304, b'', 'cached'
            return 200, json.dumps(latest).encode(), 'cached'
        with mock.patch.object(self.install._svc, 'safe_extract',
                side_effect=SystemExit('synthetic omitted bundle')), self.assertRaises(SystemExit):
            self.run_update(read)
        self.assertEqual(seen, ['cached', None])
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.assertEqual(state['latest_verified']['version'], '1.3.1.184')
        self.assertIsNone(self.updater._status.cache_tag(state, '1.2.6.174', self.feed, 'beta', 'cached'))

    def test_readonly_action_uses_fresh_metadata_and_preserves_repair_precedence(self):
        self.args.json = True
        for saved, latest, pending, action in (
                ('1.3.2.185', '1.2.6.174', False, None),
                ('1.2.6.174', '1.3.2.185', False, 'update'),
                ('1.2.6.174', '1.3.2.185', True, 'repair')):
            with self.subTest(saved=saved, latest=latest, pending=pending):
                self.state = dict(installation_repair_required=pending)
                self.updater._status.verified(self.state, {'version': saved}, self.feed, 'beta', 'cached')
                self.save()
                before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.install.do_check_update(self.args, _read_feed=lambda *_:
                        (200, json.dumps(dict(version=latest, url='file:///bundle.tar.gz')).encode(), None))
                self.assertEqual(json.loads(output.getvalue())['required_action'], action)
                self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
