"""Update tasks catch missed runs and sign-in without enabling a saved Off choice."""
import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from tests.test_windows_backend import USER, PY, ROOT, backend, service, _backend
from tests.test_windows_runtime_rebind import OLD, NEW, NAMES, NS, Scheduler


def policy(xml):
    root = ET.fromstring(xml)
    return (root.findtext('t:Settings/t:StartWhenAvailable', namespaces=NS),
            root.findtext('t:Triggers/t:LogonTrigger/t:UserId', namespaces=NS))


def legacy(home):
    scheduler = Scheduler(home)
    for name, row in scheduler.rows.items():
        if name == NAMES[0]:
            continue
        root = ET.fromstring(row['xml'])
        triggers, settings = root.find('t:Triggers', NS), root.find('t:Settings', NS)
        for item in list(triggers):
            if item.tag.endswith('LogonTrigger'):
                triggers.remove(item)
        for item in list(settings):
            if item.tag.endswith('StartWhenAvailable'):
                settings.remove(item)
        row['xml'] = ET.tostring(root, encoding='unicode')
    return scheduler


class WindowsUpdatePolicyTests(unittest.TestCase):
    def test_install_registers_both_updaters_with_catchup_and_scoped_signin(self):
        with tempfile.TemporaryDirectory() as temporary:
            home, state = Path(temporary), {}
            obj = _backend(state)
            (home / 'express_launch.py').touch()
            with mock.patch.object(service, 'wait_version', return_value=True):
                obj.install(PY, home, {}, ROOT, None)
            for name in NAMES[1:]:
                self.assertEqual(policy(state['xml_' + name]), ('true', USER))

    def test_existing_definitions_gain_policy_and_preserve_disabled_and_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            scheduler = legacy(home)
            before = copy.deepcopy(scheduler.rows)
            obj = backend.Backend(service, scheduler, query=lambda _: {'user': USER})
            self.assertTrue(obj.rebind_runtime(NEW, home))
            for name in NAMES:
                self.assertEqual((scheduler.rows[name]['enabled'], scheduler.rows[name]['pending']),
                                 (before[name]['enabled'], before[name]['pending']))
                self.assertEqual(scheduler.rows[name]['executable'], NEW)
            for name in NAMES[1:]:
                self.assertEqual(policy(scheduler.rows[name]['xml']), ('true', USER))
            self.assertFalse(obj.rebind_runtime(NEW, home))

    def test_read_only_check_detects_missing_policy_even_when_runtime_is_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            scheduler = legacy(home)
            obj = backend.Backend(service, scheduler, query=lambda _: {'user': USER})
            self.assertFalse(obj.runtime_matches(OLD, home))
            self.assertFalse(any(operation != 'query' for _, operation in scheduler.calls))

    def test_failed_policy_readback_restores_all_three_prior_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            scheduler = legacy(home)
            before = copy.deepcopy(scheduler.rows)
            failed = []
            def transport(command, **kwargs):
                result = scheduler(command, **kwargs)
                request, reply = json.loads(kwargs['input']), json.loads(result.stdout)
                if (request['operation'] == 'query' and request['name'].startswith(NAMES[2])
                        and reply['executable'] == NEW and not failed):
                    reply['catchup'] = False
                    failed.append(True)
                result.stdout = json.dumps(reply)
                return result
            obj = backend.Backend(service, transport, query=lambda _: {'user': USER})
            with self.assertRaises(SystemExit):
                obj.rebind_runtime(NEW, home)
            self.assertEqual(scheduler.rows, before)
