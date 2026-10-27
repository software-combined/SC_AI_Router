"""Owned task recovery preserves definitions and never claims failed readback."""
from copy import deepcopy
import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from tests.test_windows_backend import backend, service, USER
from tests.windows_native_fixture import cleanup

NS = '{http://schemas.microsoft.com/windows/2004/02/mit/task}'
OLD, NEW = r'C:\old\pythonw.exe', r'C:\new\pythonw.exe'


class TaskTable:
    def __init__(self, home):
        self.rows, self.writes = {}, []
        self.fail_readback = False
        for index, name in enumerate(backend._tasks.NAMES):
            xml = (backend.render_router_xml(OLD, home, USER) if index == 0 else
                   backend.render_update_xml(OLD, home, USER))
            root = ET.fromstring(xml)
            ET.SubElement(root.find(NS + 'Settings'), NS + 'Enabled').text = 'false' if index == 1 else 'true'
            ET.SubElement(root, NS + 'Data').text = ('codex-router-installer:pending-activation'
                                                    if index == 2 else 'retained task annotation')
            self.rows[False, name] = self.definition(ET.tostring(root, encoding='unicode'))

    @staticmethod
    def definition(xml, active=False):
        root = ET.fromstring(xml)
        enabled = root.findtext(NS + 'Settings/' + NS + 'Enabled', 'true') == 'true'
        return dict(xml=xml, enabled=enabled,
                    pending=root.findtext(NS + 'Data') == 'codex-router-installer:pending-activation',
                    executable=root.findtext(NS + 'Actions/' + NS + 'Exec/' + NS + 'Command'),
                    state=4 if active else 3 if enabled else 1, instances=['running'] if active else [],
                    catchup=True, signin=True)

    def call(self, name, home, operation='query', *, legacy=False, xml=None, **_):
        key = legacy, name
        row = self.rows.get(key)
        if operation in ('restore', 'delete', 'run', 'stop', 'disable'):
            self.writes.append((operation, key))
        if operation == 'restore':
            self.rows[key] = self.definition(xml, bool(row and row['instances']))
        elif operation == 'delete':
            self.rows.pop(key, None)
        elif operation == 'run':
            self.rows[key].update(enabled=True, state=4, instances=['running'])
        elif operation == 'stop':
            self.rows[key].update(state=3 if row['enabled'] else 1, instances=[])
        elif operation == 'disable':
            root = ET.fromstring(row['xml'])
            root.find(NS + 'Settings/' + NS + 'Enabled').text = 'false'
            root.find(NS + 'Data').text = ''
            self.rows[key] = self.definition(ET.tostring(root, encoding='unicode'), bool(row['instances']))
        result = deepcopy(self.rows.get(key))
        if self.fail_readback and operation == 'snapshot' and self.writes:
            result['executable'] = r'C:\wrong\pythonw.exe'
        return result


class TaskCohortTests(unittest.TestCase):
    def fixture(self, home):
        table = TaskTable(home)
        owner = backend.Backend(service, mock.Mock(), query=lambda _: {'user': USER})
        owner._task_state = table.call
        return owner, table

    def test_deleted_definitions_are_recreated_with_flags_and_annotations(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            owner, table = self.fixture(home)
            before = deepcopy(table.rows)
            saved = owner.snapshot_cohort(home)
            self.assertFalse(table.writes)
            table.rows.clear()
            owner.restore_cohort(home, saved)
            self.assertEqual(table.rows, before)

    def test_retained_running_router_restarts_without_losing_disabled_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            owner, table = self.fixture(home)
            root = ET.fromstring(table.rows[False, backend.ROUTER_TASK]['xml'])
            root.find(NS + 'Settings/' + NS + 'Enabled').text = 'false'
            table.rows[False, backend.ROUTER_TASK] = table.definition(ET.tostring(root, encoding='unicode'), True)
            saved = owner.snapshot_cohort(home)
            table.rows.clear()
            owner.restore_cohort(home, saved)
            row = table.rows[False, backend.ROUTER_TASK]
            self.assertFalse(row['enabled'])
            self.assertEqual(row['instances'], ['running'])

    def test_runtime_advance_preserves_flags_triggers_and_rejects_failed_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            owner, table = self.fixture(home)
            saved = owner.snapshot_cohort(home)
            owner.preserve_cohort(home, saved, NEW.replace('pythonw.exe', 'python.exe'))
            for name, before in saved['current'].items():
                after = table.rows[False, name]
                self.assertEqual(after['executable'], NEW)
                self.assertEqual((after['enabled'], after['pending']), (before['enabled'], before['pending']))
                self.assertEqual(ET.tostring(ET.fromstring(after['xml']).find(NS + 'Triggers')),
                                 ET.tostring(ET.fromstring(before['xml']).find(NS + 'Triggers')))
            table.fail_readback = True
            with self.assertRaisesRegex(ValueError, 'readback'):
                owner.restore_cohort(home, saved)

    def test_malformed_recovery_record_refuses_before_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, table = self.fixture(Path(temporary))
            saved = owner.snapshot_cohort(Path(temporary))
            saved['current'][backend.UPDATE_TASK]['enabled'] = 'false'
            with self.assertRaises(ValueError):
                owner.restore_cohort(Path(temporary), saved)
            self.assertFalse(table.writes)

    def test_new_running_task_is_not_deleted_or_killed_before_exit_is_verified(self):
        for name in backend._tasks.NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                owner, table = self.fixture(home)
                row = table.rows.pop((False, name))
                saved = owner.snapshot_cohort(home)
                table.rows[False, name] = table.definition(row['xml'], active=True)
                with mock.patch.object(owner, '_wait_stopped', return_value=False), \
                        mock.patch.object(owner, '_stop_task') as stop:
                    with self.assertRaisesRegex(ValueError, 'still running'):
                        owner.restore_cohort(home, saved)
                    stop.assert_not_called()
                self.assertIn((False, name), table.rows)
                self.assertFalse(any(operation == 'delete' for operation, _ in table.writes))


@unittest.skipUnless(os.name == 'nt', 'native Windows owned-task recovery')
class NativeTaskRestoreTests(unittest.TestCase):
    def test_missing_task_restore_checks_owner_before_recreating_definition(self):
        owner = backend.Backend(service, subprocess.run)
        sid = owner._identity()
        name = 'SCG-CI-' + uuid.uuid4().hex + '-' + sid
        with tempfile.TemporaryDirectory(prefix='cohort é ') as temporary:
            home = Path(temporary)
            xml = backend.render_router_xml(sys.executable, home, sid)
            xml = re.sub(r'<Triggers>.*?</Triggers>', '<Triggers/>', xml, flags=re.S)
            args = backend._arguments(home, 'router_launch.py', backend.ROUTER_LOG)
            def call(operation='query', definition=None):
                return backend._tasks.invoke(owner._call, sid, name, args, operation, definition)
            try:
                call('register', xml)
                before = call('snapshot')
                call('delete')
                foreign = before['xml'].replace('codex-router-installer', 'foreign-application')
                with self.assertRaises(backend._tasks.OwnershipError):
                    call('restore', foreign)
                self.assertIsNone(call())
                call('restore', before['xml'])
                after = call('snapshot')
                self.assertEqual(after['xml'], before['xml'])
                self.assertEqual((after['enabled'], after['pending']), (False, True))
            finally:
                cleanup(owner._call, [name])


if __name__ == '__main__':
    unittest.main()
