"""Configuration-only repairs use the existing dismissible restart dialog."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_notice import notice_mod as notice


class AttachmentNotices(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.path = self.home / notice.NOTICE_FILE
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        self.enterContext(mock.patch.object(notice._text, 'pending_names', return_value=[]))
        self.enterContext(mock.patch.object(notice._text, 'acknowledge'))

    def test_config_only_notice_offers_restart_and_later_once(self):
        self.assertTrue(notice.record_attachment(self.home, '1.0.0', 'a' * 32))
        command = notice.dialog_command('1.0.0', 'win32', which=lambda _: 'powershell',
                                        attachment=True)
        self.assertIn('was reconnected', command[-1])
        self.assertIn('Quit and reopen', command[-1])
        self.assertIn('Later', command[-1])
        with mock.patch.object(notice, 'dialog_command', return_value=command), \
                mock.patch.object(notice, '_dialog_up', return_value=True):
            spawn = mock.Mock(return_value=42)
            self.assertTrue(notice.show_pending(self.home, spawn=spawn, pid_alive=lambda _: True))
            self.assertFalse(notice.record_attachment(self.home, '1.0.0', 'a' * 32))
            self.assertFalse(notice.show_pending(self.home, spawn=spawn))
            spawn.assert_called_once()
        notice._text.acknowledge.assert_not_called()

    def test_missing_dialog_keeps_reason_pending_and_later_gui_can_show_it(self):
        notice.record_attachment(self.home, '1.0.0', 'a' * 32)
        with mock.patch.object(notice, 'dialog_command', return_value=None):
            self.assertFalse(notice.show_pending(self.home))
        self.assertNotIn('shown', json.loads(self.path.read_text()))
        self.assertFalse(notice.record_attachment(self.home, '1.0.0', 'a' * 32))
        with mock.patch.object(notice, 'dialog_command', return_value=['dialog']), \
                mock.patch.object(notice, '_dialog_up', return_value=True):
            self.assertTrue(notice.show_pending(self.home, spawn=lambda _: 42,
                                               pid_alive=lambda _: True))

    def test_prior_dialog_does_not_consume_an_unshown_repair_reason(self):
        self.path.write_text(json.dumps(dict(version='1.0.0', shown=True, pid=42)))
        notice.record_attachment(self.home, '1.0.0', 'b' * 32)
        with mock.patch.object(notice, 'dialog_command', return_value=['dialog']):
            self.assertFalse(notice.show_pending(self.home, pid_alive=lambda _: True))
        self.assertNotIn('shown', json.loads(self.path.read_text()))


if __name__ == '__main__':
    unittest.main()
