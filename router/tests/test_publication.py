"""Public packaging, legacy migration and history-free export boundaries."""
import importlib.util
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod

ROOT = Path(__file__).resolve().parents[1]
FLAG = '_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def index_entry(mode, name, data):
    oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    return f'{mode} {oid} 0\t{name}\0'.encode()


class PublicationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('git'), 'requires Git checkout conversion')
    def test_windows_checkout_preserves_pinned_notice_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            relative = 'router/packaging/RUNTIME-NOTICES.txt'
            notice = root / relative
            notice.parent.mkdir(parents=True)
            notice.write_bytes((ROOT / 'packaging/RUNTIME-NOTICES.txt').read_bytes())
            shutil.copyfile(ROOT.parent / '.gitattributes', root / '.gitattributes')
            env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
            for args in (('init', '-q'), ('add', '.gitattributes', relative),
                         ('checkout-index', '--all', '--prefix=checkout/')):
                subprocess.run(['git', '-c', 'core.autocrlf=true', *args], cwd=root,
                               env=env, check=True, capture_output=True)
            inventory = json.loads((ROOT / 'packaging/runtime-components.json').read_text())
            actual = hashlib.sha256((root / 'checkout' / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, inventory['notice_sha256'])

    def test_hosted_zone_is_supplied_by_the_deployer(self):
        for path in (ROOT / 'infra/feed.yaml', ROOT / 'infra/feed-cert.yaml'):
            parameters = path.read_text().split('Resources:', 1)[0]
            zone = re.search(r'^  HostedZoneId:\n((?:    .*\n|\n)*)', parameters, re.M).group(1)
            self.assertNotIn('Default:', zone)

    def test_runtime_component_notices_are_retained_with_the_application(self):
        release = module('publication_runtime_notices', 'packaging/release.py')
        names = release.bundle_files(ROOT)
        for path in ('packaging/runtime-components.json', 'packaging/RUNTIME-NOTICES.txt'):
            self.assertIn(path, names)
        inventory = json.loads((ROOT / 'packaging/runtime-components.json').read_text())
        notices = (ROOT / inventory['notice_file']).read_bytes()
        self.assertEqual(hashlib.sha256(notices).hexdigest(), inventory['notice_sha256'])
        pins = json.loads((ROOT / 'packaging/runtime.lock').read_text())['targets']
        self.assertEqual({row['install_sha256'] for row in inventory['archives']},
                         {row['sha256'] for row in pins})
        for archive in inventory['archives']:
            self.assertTrue(archive['install_matches_full'])
            for component in archive['native_components']:
                for name in component['notice_sections']:
                    self.assertIn(name, inventory['notice_sections'])
                    self.assertIn(name.encode(), notices)

    def test_bundle_excludes_development_and_newly_added_diagnostics(self):
        release = module('publication_release', 'packaging/release.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tools').mkdir()
            (root / 'tools' / 'probe_secret_reader.py').write_text('do not distribute')
            names = release.bundle_files(root)
            self.assertNotIn('tools/probe_secret_reader.py', names)
        tools = {name for name in release.bundle_files(ROOT) if name.startswith('tools/')}
        self.assertEqual(tools, {'tools/disable.py', 'tools/global_instructions.py',
                             'tools/provision_key.py', 'tools/classify_attachments.py'})

    def test_legacy_flag_removal_preserves_the_original_detach_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'router'
            home.mkdir()
            path = Path(folder) / 'settings.json'
            state = {'port': 1, 'token': 'synthetic-path'}
            original = {'env': {'OTHER': 'keep'}}
            path.write_text(json.dumps(original))
            config = install_mod._claude_config
            receipts = install_mod._codex_config
            config.attach(home, state, receipts, path, env={})
            entry = receipts.read_receipt(home)['clients']['claude']
            snapshot = json.loads(entry['inserted_block'])
            snapshot[FLAG] = None  # only old receipts claimed this key
            entry['inserted_block'] = json.dumps(snapshot)
            receipts.write_client_receipt(home, 'claude', entry)
            doc = json.loads(path.read_text())
            doc['env'][FLAG] = '1'  # emulate the prior installer's setting
            path.write_text(json.dumps(doc))
            config.attach(home, state, receipts, path, env={})
            self.assertNotIn(FLAG, json.loads(path.read_text())['env'])
            config.detach(home, receipts, path, env={})
            self.assertEqual(json.loads(path.read_text()), original)

    def test_hand_managed_first_party_flag_is_not_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({'env': {FLAG: '1'}}))
            before = path.read_bytes()
            with self.assertRaisesRegex(SystemExit, 'managed outside'):
                install_mod._claude_config.merge_env(
                    Path(folder), {'port': 1, 'token': 'synthetic-path'}, path, env={})
            self.assertEqual(path.read_bytes(), before)

    def test_new_receipt_cannot_claim_a_later_manual_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            home, path = Path(folder) / 'router', Path(folder) / 'settings.json'
            home.mkdir()
            state = {'port': 1, 'token': 'synthetic-path'}
            config, receipts = install_mod._claude_config, install_mod._codex_config
            config.attach(home, state, receipts, path, env={})
            doc = json.loads(path.read_text())
            doc['env'][FLAG] = '1'
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(SystemExit, 'managed outside'):
                config.attach(home, state, receipts, path, env={})
            self.assertEqual(json.loads(path.read_text()), doc)

    def test_source_export_never_copies_history_or_untracked_work(self):
        exporter = module('publication_export', 'tools/export_public_source.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'checkout'
            root.mkdir()
            (root / 'a.py').write_text('synthetic source')
            (root / '.git').mkdir()
            (root / '.git' / 'old-history').write_text('private history')
            (root / 'local-notes.txt').write_text('private untracked notes')
            output = Path(folder) / 'export'
            with mock.patch.object(exporter.subprocess, 'check_output',
                                   return_value=index_entry('100644', 'a.py', b'synthetic source')):
                archive = exporter.export(root, output)
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.getnames(), ['a.py'])
                self.assertEqual(tar.extractfile('a.py').read(), b'synthetic source')
            inventory = json.loads((output / 'inventory.json').read_text())
            self.assertFalse(inventory['contains_git_history'])
            self.assertEqual(set(inventory['files']), {'a.py'})

    def test_source_export_preserves_executable_hook_permissions(self):
        exporter = module('publication_export_modes', 'tools/export_public_source.py')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'checkout'
            root.mkdir()
            hook = root / 'pre-commit'
            hook.write_text('#!/bin/sh\nexit 0\n')
            output = Path(folder) / 'export'
            with mock.patch.object(exporter.subprocess, 'check_output',
                                   return_value=index_entry('100755', 'pre-commit', hook.read_bytes())):
                archive = exporter.export(root, output)
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.getmember('pre-commit').mode, 0o755)
            if os.name != 'nt':
                self.assertEqual((output / 'source/pre-commit').stat().st_mode & 0o777, 0o755)

    def test_source_export_refuses_bytes_not_in_reviewed_index(self):
        exporter = module('publication_export_unstaged', 'tools/export_public_source.py')
        with tempfile.TemporaryDirectory() as folder:
            root, output = Path(folder) / 'checkout', Path(folder) / 'export'
            root.mkdir()
            (root / 'a.py').write_bytes(b'unreviewed working content')
            with mock.patch.object(exporter.subprocess, 'check_output',
                                   return_value=index_entry('100644', 'a.py', b'reviewed source')):
                with self.assertRaisesRegex(SystemExit, 'reviewed index'):
                    exporter.export(root, output)
            self.assertFalse(output.exists())

    def test_source_export_refuses_a_private_index_path(self):
        exporter = module('publication_export_private', 'tools/export_public_source.py')
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(exporter.subprocess, 'check_output', return_value=b'100644 ' + b'0' * 40 + b' 0\tplans/private.md\0'):
                with self.assertRaisesRegex(SystemExit, 'private path'):
                    exporter.export(Path(folder), Path(folder).parent / 'unused-export')
