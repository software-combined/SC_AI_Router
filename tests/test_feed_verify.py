"""Detached Ed25519 feed signatures (Plan 047 A3): stdlib verifier, release
signing, beta origin derivation. No network: feeds and signatures are bytes,
keys are ephemeral, fetches are injected."""
import importlib.util as _ilu
import tempfile
import unittest
from pathlib import Path
from tests._platform import requires_posix_perms
from unittest import mock

from tests.test_release import _release_mod

_feed_verify_spec = _ilu.spec_from_file_location(
    'router_feed_verify',
    Path(__file__).resolve().parents[1] / 'packaging' / 'feed_verify.py')
feed_verify = _ilu.module_from_spec(_feed_verify_spec)
_feed_verify_spec.loader.exec_module(feed_verify)

# RFC 8032 section 7.1 TEST 1 (empty message). Cross-checked against the
# published vectors after a from-memory transcription failed loudly here:
# never trust a hand-typed curve constant without this test.
RFC_SEED = '9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60'
RFC_PUB = 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'
RFC_SIG = ('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f'
           'b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')


class Ed25519Tests(unittest.TestCase):
    def test_rfc_vector(self):
        self.assertEqual(feed_verify.public_key_hex(RFC_SEED), RFC_PUB)
        self.assertEqual(feed_verify.sign_hex(RFC_SEED, b''), RFC_SIG)
        self.assertTrue(feed_verify.verify_hex(RFC_PUB, b'', RFC_SIG))

    def test_round_trip_and_rejections(self):
        seed, pub = feed_verify.generate_keypair()
        sig = feed_verify.sign_hex(seed, b'feed-bytes')
        self.assertTrue(feed_verify.verify_hex(pub, b'feed-bytes', sig))
        self.assertFalse(feed_verify.verify_hex(pub, b'feed-BYTES', sig))
        # Flip a high bit of S: arithmetic on the scalar, never a small-order
        # tweak. (Zeroing S's low byte only clears its low bits, which the
        # group equation can still satisfy ~1/16 of the time per key.)
        s = int.from_bytes(bytes.fromhex(sig[64:]), 'little')
        bad_s = (s ^ (1 << 250)).to_bytes(32, 'little').hex()
        self.assertFalse(feed_verify.verify_hex(pub, b'feed-bytes', sig[:64] + bad_s))
        other = feed_verify.generate_keypair()[1]
        self.assertFalse(feed_verify.verify_hex(other, b'feed-bytes', sig))

    def test_malformed_inputs_are_false(self):
        seed, pub = feed_verify.generate_keypair()
        sig = feed_verify.sign_hex(seed, b'm')
        # Flip the first byte: forcing it to 'ff' left sig valid 1 run in 256.
        flipped = '%02x' % (int(sig[:2], 16) ^ 0xff) + sig[2:]
        for bad_pub, bad_sig in (('zz', sig), (pub, 'zz'), (pub, sig[:-2]),
                                 (pub, flipped), ('00' * 32, sig)):
            self.assertFalse(feed_verify.verify_hex(bad_pub, b'm', bad_sig))


class FeedGateTests(unittest.TestCase):
    def test_beta_uses_origin_without_api(self):
        self.assertEqual(feed_verify.beta_feed_url('https://cdn.example/stable/latest.json'),
                         'https://cdn.example/beta/latest.json')
        self.assertEqual(feed_verify.beta_feed_url('file:///stable/latest.json'),
                         'file:///beta/latest.json')
        with self.assertRaises(SystemExit):
            feed_verify.beta_feed_url('not-a-url')

    def test_release_sign_flag_is_retired(self):
        release_mod = _release_mod()
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / 'seed'
            key_file.write_text('00' * 32 + '\n')
            with self.assertRaisesRegex(SystemExit, 'retired'):
                release_mod.main(['--out', tmp, '--build', '7', '--sign', str(key_file)])

    def test_checked_feed_rejects_non_json_and_unknown_key(self):
        seed, pub = feed_verify.generate_keypair()
        other = feed_verify.generate_keypair()[1]
        sig = feed_verify.sign_hex(seed, b'not-json{{{')
        with mock.patch.object(feed_verify, 'FEED_PUBLIC_KEY', pub):
            with self.assertRaises((ValueError, SystemExit)):
                feed_verify.checked_feed(b'not-json{{{', sig.encode())
        good = feed_verify.sign_hex(seed, b'{"serial": 7}')
        with mock.patch.object(feed_verify, 'FEED_PUBLIC_KEY', other):
            with self.assertRaises(SystemExit):
                feed_verify.checked_feed(b'{"serial": 7}', good.encode())

    @requires_posix_perms
    def test_gen_key_writes_owner_only_seed(self):
        release_mod = _release_mod()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'seed'
            release_mod.main(['--out', tmp, '--gen-key', str(out)])
            self.assertEqual(oct(out.stat().st_mode & 0o777), '0o600')
            seed = out.read_text().strip()
            pub = feed_verify.public_key_hex(seed)
            self.assertEqual(len(bytes.fromhex(seed)), 32)
            self.assertTrue(feed_verify.verify_hex(
                pub, b'probe', feed_verify.sign_hex(seed, b'probe')))
            with self.assertRaises(SystemExit):
                release_mod.main(['--out', tmp, '--gen-key', str(out)])


if __name__ == '__main__':
    unittest.main()
