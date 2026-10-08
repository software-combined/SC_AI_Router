"""Refuse a retained-image collision before starting a paid probe."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import probe_media_generation as probe


class MediaProbeOptionsTests(unittest.TestCase):
    def test_existing_output_stops_before_credentials_or_client(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'proof.png'
            output.write_bytes(b'existing proof')
            with mock.patch.object(probe, 'Credentials') as credentials, \
                    mock.patch.object(probe, 'AppServer') as client, \
                    mock.patch.object(probe.transport, 'post_with_phases') as send:
                with self.assertRaises(FileExistsError):
                    probe.probe('openai/gpt-image-2', live=True, live_chat=True,
                                output=output)
                credentials.assert_not_called()
                client.assert_not_called()
                send.assert_not_called()
            self.assertEqual(output.read_bytes(), b'existing proof')
