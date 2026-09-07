"""Offline checks for synthetic probe media (Plan 044 test plan)."""
import io
import struct
import unittest
import wave
import zlib
from tools.probe_media import red_png, silent_wav, PNG_SIGNATURE


class ProbeMediaTests(unittest.TestCase):
    def test_png_signature_and_red_pixels(self):
        blob = red_png()
        self.assertTrue(blob.startswith(PNG_SIGNATURE + b'\x00\x00\x00\rIHDR'))
        pos = len(PNG_SIGNATURE)
        width, height, depth, color = struct.unpack('>IIBB', blob[pos + 8:pos + 18])
        self.assertEqual((width, height, depth, color), (2, 2, 8, 2))
        at = blob.index(b'IDAT')
        length = struct.unpack('>I', blob[at - 4:at])[0]
        raw = zlib.decompress(blob[at + 4:at + 4 + length])
        self.assertEqual(raw, (b'\x00' + b'\xff\x00\x00' * 2) * 2)

    def test_wav_silence_header(self):
        blob = silent_wav()
        with wave.open(io.BytesIO(blob), 'rb') as stream:
            self.assertEqual(stream.getnchannels(), 1)
            self.assertEqual(stream.getsampwidth(), 2)
            self.assertEqual(stream.getframerate(), 8000)
            self.assertEqual(stream.getnframes(), 2400)
            self.assertEqual(set(stream.readframes(2400)), {0})


if __name__ == '__main__':
    unittest.main()
