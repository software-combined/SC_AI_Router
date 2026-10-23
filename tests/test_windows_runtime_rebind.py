"""Changing retained Python updates only owned task actions and rolls back as a group."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module
from tests import test_native_resources as native_fixtures
from tests.test_windows_backend import USER, backend, service

OLD, NEW = r'C:\retained-old\pythonw.exe', r'C:\retained-new\pythonw.exe'
NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
NAMES = (backend.ROUTER_TASK, backend.UPDATE_TASK, backend.EXPRESS_TASK)


class Scheduler:
    def __init__(self, home):
        self.rows, self.calls, self.bad_readback = {}, [], None
        for index, name in enumerate(NAMES):
            xml = (backend.render_router_xml(OLD, home, USER) if index == 0 else
                   backend.render_update_xml(OLD, home) if index == 1 else
                   backend.render_express_xml(OLD, home))
            doc = ET.fromstring(xml)
            ET.SubElement(doc, '{%s}Data' % NS['t']).text = 'retained annotation'
            xml = ET.tostring(doc, encoding='unicode')
            self.rows[name] = dict(xml=xml, executable=OLD, enabled=index != 1,
                                   pending=index == 2, state=3, instances=[])

    def __call__(self, command, **kwargs):
        request = json.loads(kwargs['input'])
        name = request['name'].removesuffix('-' + USER)
        operation = request['operation']
        self.calls.append((name, operation))
        row = self.rows[name]
        if operation == 'rebind':
            doc = ET.fromstring(row['xml'])
            doc.find('t:Actions/t:Exec/t:Command', NS).text = request['executable']
            row['xml'], row['executable'] = ET.tostring(doc, encoding='unicode'), request['executable']
        elif operation in ('register', 'restore'):
            row['xml'] = request['xml']
            if operation == 'register':  # Normal registration rewrites task data.
                doc = ET.fromstring(row['xml'])
                doc.find('t:Data', NS).text = 'codex-router-installer:pending-activation' if row['pending'] else ''
                row['xml'] = ET.tostring(doc, encoding='unicode')
            row['executable'] = ET.fromstring(row['xml']).find('t:Actions/t:Exec/t:Command', NS).text
        answer = dict(row, kind='present')
        if operation == 'query' and self.bad_readback == name and row['executable'] == NEW:
            answer['executable'], self.bad_readback = OLD, None
        return SimpleNamespace(returncode=0, stdout=json.dumps(answer), stderr='')


class RuntimeRebindTests(unittest.TestCase):
    def test_unicode_executable_and_snapshot_survive_the_process_transport(self):
        expected = dict(kind='present', executable='C:\\Élise\\pythonw.exe',
            state=3, enabled=False, pending=True, instances=[], xml='<Data>é &amp; 漢字</Data>')
        raw = json.dumps(expected, ensure_ascii=False).encode('utf-8')
        def pipe(command, **kwargs):
            return SimpleNamespace(returncode=0,
                stdout=raw.decode(kwargs.get('encoding') or 'cp1252'), stderr='')
        actual = backend._tasks.invoke(pipe, USER, 'fixture', 'arguments', 'snapshot')
        self.assertEqual(actual, expected)

    def test_new_runtime_replaces_all_three_paths_preserving_definitions_and_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            scheduler = Scheduler(home)
            before = {name: dict(row) for name, row in scheduler.rows.items()}
            obj = backend.Backend(service, scheduler, query=lambda _: {'user': USER})
            self.assertTrue(obj.rebind_runtime(NEW, home))
            for name, row in scheduler.rows.items():
                self.assertEqual(row['executable'], NEW)
                self.assertEqual((row['enabled'], row['pending']),
                                 (before[name]['enabled'], before[name]['pending']))
                actual, original = ET.fromstring(row['xml']), ET.fromstring(before[name]['xml'])
                original.find('t:Actions/t:Exec/t:Command', NS).text = NEW
                self.assertEqual(ET.tostring(actual), ET.tostring(original))
            self.assertFalse(obj.rebind_runtime(NEW, home))

    def test_failed_exact_readback_restores_every_prior_definition(self):
        with tempfile.TemporaryDirectory() as temporary:
            home, scheduler = Path(temporary), Scheduler(Path(temporary))
            before = {name: dict(row) for name, row in scheduler.rows.items()}
            scheduler.bad_readback = backend.UPDATE_TASK
            obj = backend.Backend(service, scheduler, query=lambda _: {'user': USER})
            with self.assertRaises(SystemExit):
                obj.rebind_runtime(NEW, home)
            self.assertEqual(scheduler.rows, before)
            self.assertTrue(any(operation == 'restore' for _, operation in scheduler.calls))

    def test_read_only_runtime_checks_do_not_snapshot_or_rewrite_tasks(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            scheduler = Scheduler(home)
            before = {name: dict(row) for name, row in scheduler.rows.items()}
            obj = backend.Backend(service, scheduler, query=lambda _: {'user': USER})
            self.assertTrue(obj.runtime_matches(OLD, home))
            self.assertFalse(obj.runtime_matches(NEW, home))
            self.assertEqual(scheduler.rows, before)
            self.assertTrue(all(operation == 'query' for _, operation in scheduler.calls))

    def test_native_delivery_rebinds_only_after_the_verified_pointer_advances(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = native_fixtures.NativeResourcesTests().fixture(Path(temporary))
            original, observed = owner.load, []
            def install(home, permanent, python):
                (home / 'setup-current').write_text(permanent.name)
            def rebind(home):
                resources = owner.current(home)
                doc = module('native_payload').metadata(resources)
                observed.append(str(resources / 'runtime' / doc['runtime_exec']))
                return 'ready'
            def load(name):
                if name == 'native_shortcuts':
                    return SimpleNamespace(install=install)
                if name == 'runtime_rebind':
                    return SimpleNamespace(reconcile=rebind)
                return original(name)
            with mock.patch.object(owner, 'load', side_effect=load):
                self.assertTrue(owner.deliver(home, latest,
                    'https://dist.softwarecombined.com/stable/latest.json', lambda _: data))
            self.assertEqual(len(observed), 1)
            self.assertIn(str(home / 'setup'), observed[0])

    def test_reconcile_rejects_old_resources_and_records_retryable_backend_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home = module('runtime_rebind'), Path(temporary)
            original = owner.load
            (home / 'current').write_text('1.3.14.204')
            (home / 'releases/1.3.14.204').mkdir(parents=True)
            (home / 'mixed-router-state.json').write_text('{}')
            doc = dict(version='1.3.13.203', runtime_exec='pythonw.exe', menu_sha256='a' * 64)
            platforms, adapter = mock.Mock(), mock.Mock()
            platforms.select.return_value = adapter
            svc = original('service')
            svc.load = mock.Mock(return_value=platforms)
            def load(name):
                return dict(service=svc,
                    native_resources=SimpleNamespace(current=lambda _: home / 'setup/new'),
                    native_payload=SimpleNamespace(metadata=lambda _: doc)).get(name) or original(name)
            with mock.patch.object(owner.sys, 'platform', 'win32'), \
                    mock.patch.object(owner, 'load', side_effect=load):
                self.assertEqual(owner.reconcile(home), 'deferred')
                platforms.select.assert_not_called()
                doc['version'] = '1.3.14.204'
                before = (home / 'mixed-router-state.json').read_bytes()
                for matches, outcome in ((True, 'ready'), (False, 'repairable')):
                    adapter.runtime_matches.return_value = matches
                    self.assertEqual(owner.reconcile(home, apply=False), outcome)
                adapter.rebind_runtime.assert_not_called()
                self.assertEqual((home / 'mixed-router-state.json').read_bytes(), before)
                adapter.rebind_runtime.side_effect = SystemExit('synthetic readback failed')
                self.assertEqual(owner.reconcile(home), 'failed')
                adapter.rebind_runtime.assert_called_once_with(str(home / 'setup/new/runtime/pythonw.exe'), home)
                state = json.loads((home / 'mixed-router-state.json').read_text())
                self.assertEqual(state['component_repairs']['scheduler'], 'failed')
                adapter.rebind_runtime.side_effect = None
                self.assertEqual(owner.reconcile(home), 'ready')
                state = json.loads((home / 'mixed-router-state.json').read_text())
                self.assertEqual(state['component_repairs']['scheduler'], 'ready')


if __name__ == '__main__':
    unittest.main()
