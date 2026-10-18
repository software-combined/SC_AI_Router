"""Compile real platform dialog scripts without opening a window."""
import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_native_setup import module


class NativeWarningSyntaxTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'native AppleScript compiler')
    def test_repair_and_later_labels_compile_with_the_product_icon(self):
        platform = module('claude_desktop_platform')
        script = platform.dialog_script('Updates need repair.', True, ('Repair now', 'Later'))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'warning.scpt'
            subprocess.run(['/usr/bin/osacompile', '-o', str(output), '-e', script],
                           check=True, capture_output=True, text=True, timeout=30)
            self.assertTrue(output.is_file())

    @unittest.skipUnless(sys.platform == 'win32', 'native PowerShell parser')
    def test_repair_and_later_labels_parse_without_showing_a_dialog(self):
        platform = module('claude_desktop_platform')
        script = platform._windows_dialog('Updates need repair.', True, ('Repair now', 'Later'))
        encoded = base64.b64encode(script.encode()).decode()
        command = ("$ErrorActionPreference='Stop';$source=[Text.Encoding]::UTF8.GetString("
                   "[Convert]::FromBase64String('%s'));[void][scriptblock]::Create($source)" % encoded)
        subprocess.run(['powershell', '-NoProfile', '-Command', command],
                       check=True, capture_output=True, text=True, timeout=30)
