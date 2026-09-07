"""Synthetic probe media: generated PNG and WAV bytes, no files, no network.

Consumed by the capability-probe flags in tools/probe_codex_runtime.py;
unit-tested offline in tests/test_probe_media.py.
"""
import io
import struct
import wave
import zlib

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def red_png(size=2):
    """Solid-red RGB PNG of size x size pixels."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack(
            '>I', zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + b'\xff\x00\x00' * size for _ in range(size))
    return (PNG_SIGNATURE + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def silent_wav(seconds=0.3, rate=8000):
    """Mono 16-bit silence of the given duration."""
    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b'\x00' * frames * 2)
    return buf.getvalue()
