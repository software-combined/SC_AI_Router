"""Detached Ed25519 feed signatures (Plan 047 A3): stdlib verifier, release
signing, installer enforcement, beta origin derivation. No network: feeds and
signatures are bytes, keys are ephemeral, fetches are injected."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_router import feed_verify
from tests.test_release import _release_mod

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
        self.assertFalse(feed_verify.verify_hex(pub, b'feed-bytes', sig[:-2] + '00'))
        other = feed_verify.generate_keypair()[1]
        self.assertFalse(feed_verify.verify_hex(other, b'feed-bytes', sig))

    def test_malformed_inputs_are_false(self):
        seed, pub = feed_verify.generate_keypair()
        sig = feed_verify.sign_hex(seed, b'm')
        for bad_pub, bad_sig in (('zz', sig), (pub, 'zz'), (pub, sig[:-2]),
                                 (pub, 'ff' + sig[2:]), ('00' * 32, sig)):
            self.assertFalse(feed_verify.verify_hex(bad_pub, b'm', bad_sig))


class FeedGateTests(unittest.TestCase):
    def test_no_key_refuses_everything(self):
        with mock.patch.object(feed_verify, 'FEED_PUBLIC_KEY', ''):
            with self.assertRaises(SystemExit):
                feed_verify.load_signed_feed('file:///latest.json', lambda url: b'{}')

    def test_missing_signature_refuses(self):
        _, pub = feed_verify.generate_keypair()
        with mock.patch.object(feed_verify, 'FEED_PUBLIC_KEY', pub):
            def fetch(url):
                if url.endswith('.sig'):
                    raise OSError('404')
                return b'{"version": "1.0.0"}'
            with self.assertRaises(SystemExit):
                feed_verify.load_signed_feed('file:///latest.json', fetch)

    def test_tampered_body_or_sig_rejected(self):
        seed, pub = feed_verify.generate_keypair()
        body = b'{"version": "1.0.0", "serial": 3}'
        sig = feed_verify.sign_hex(seed, body).encode()
        with mock.patch.object(feed_verify, 'FEED_PUBLIC_KEY', pub):
            good = feed_verify.load_signed_feed(
                'file:///latest.json',
                lambda url: sig if url.endswith('.sig') else body)
            self.assertEqual(good['serial'], 3)
            with self.assertRaises(SystemExit):
                feed_verify.load_signed_feed(
                    'file:///latest.json',
                    lambda url: sig if url.endswith('.sig') else body + b' ')
            with self.assertRaises(SystemExit):
                feed_verify.load_signed_feed(
                    'file:///latest.json',
                    lambda url: b'00' + sig[2:] if url.endswith('.sig') else body)

    def test_beta_uses_origin_without_api(self):
        self.assertEqual(feed_verify.beta_feed_url('https://cdn.example/stable/latest.json'),
                         'https://cdn.example/beta/latest.json')
        self.assertEqual(feed_verify.beta_feed_url('file:///stable/latest.json'),
                         'file:///beta/latest.json')
        with self.assertRaises(SystemExit):
            feed_verify.beta_feed_url('not-a-url')

    def test_release_signs_verifiable_sidecar(self):
        release_mod = _release_mod()
        seed, pub = feed_verify.generate_keypair()
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / 'seed'
            release_mod.main(['--out', tmp, '--build', '7'])
            with self.assertRaises(SystemExit):
                release_mod.main(['--out', tmp, '--sign', str(key_file)])
            key_file.write_text(seed + '\n')
            release_mod.main(['--out', tmp, '--build', '7', '--sign', str(key_file)])
            body = (Path(tmp) / 'latest.json').read_bytes()
            sig = (Path(tmp) / 'latest.json.sig').read_text()
            with mock.patch.object(feed_verify, 'FEED_PUBLIC_KEY', pub):
                self.assertEqual(feed_verify.checked_feed(body, sig.encode())['serial'], 7)

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
