"""Detached Ed25519 feed signatures with only hashlib (RFC 8032, SHA-512).

The release tool signs the exact latest.json bytes; the installer verifies
them before trusting anything inside (version, URL, checksum, serial). A
checksum inside a compromised feed stops corruption, not a bucket takeover,
so this signature is the publisher-authentication step. The router request
path never imports this module.
"""
import hashlib
import json
import os

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P


def _hint(data):
    return int.from_bytes(hashlib.sha512(data).digest(), 'little') % L


def _x_recover(y):
    xx = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P:
        x = x * pow(2, (P - 1) // 4, P) % P
    if (x * x - xx) % P:
        raise ValueError('no square root')
    return x if x & 1 == 0 else P - x


def _decode(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, 'little') & ((1 << 255) - 1)
    if y >= P:
        return None
    try:
        x = _x_recover(y)
    except ValueError:
        return None
    if x & 1 != data[31] >> 7:
        x = P - x
    if (-x * x + y * y - 1 - D * x * x * y * y) % P:
        return None
    return (x, y, 1, x * y % P)


def _add(p, q):
    (x1, y1, z1, t1), (x2, y2, z2, t2) = p, q
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * D * t2 % P
    d = z1 * 2 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % P, g * h % P, f * g % P, e * h % P


def _mult(p, n):
    q = (0, 1, 1, 0)
    while n:
        if n & 1:
            q = _add(q, p)
        p = _add(p, p)
        n >>= 1
    return q


def _encode(p):
    x, y, z, _t = p
    inv = pow(z, P - 2, P)
    return ((y * inv % P) | ((x * inv % P & 1) << 255)).to_bytes(32, 'little')


_GY = 4 * pow(5, P - 2, P) % P
_GX = _x_recover(_GY)
if _GX & 1:
    _GX = P - _GX
G = (_GX, _GY, 1, _GX * _GY % P)


def _scalar(seed):
    a = int.from_bytes(hashlib.sha512(seed).digest()[:32], 'little')
    return (a & ~((1 << 255) | 7)) | (1 << 254)


def public_key_hex(seed_hex):
    """Release-side public key for a 32-byte hex seed."""
    return _encode(_mult(G, _scalar(bytes.fromhex(seed_hex)))).hex()


def generate_keypair():
    """One release signing key. The seed file is secret; the hex public key
    is compiled into FEED_PUBLIC_KEY."""
    seed = os.urandom(32).hex()
    return seed, public_key_hex(seed)


def sign_hex(seed_hex, message):
    """Deterministic detached signature (hex) over the exact message bytes."""
    seed = bytes.fromhex(seed_hex)
    prefix = hashlib.sha512(seed).digest()[32:]
    encoded_a = _encode(_mult(G, _scalar(seed)))
    nonce = _hint(prefix + message)
    commitment = _encode(_mult(G, nonce))
    proof = (nonce + _hint(commitment + encoded_a + message) * _scalar(seed)) % L
    return (commitment + proof.to_bytes(32, 'little')).hex()


def verify_hex(pub_hex, message, sig_hex):
    """True only when the 64-byte hex signature authenticates the message."""
    try:
        pub, sig = bytes.fromhex(pub_hex), bytes.fromhex(sig_hex)
    except ValueError:
        return False
    if len(pub) != 32 or len(sig) != 64 or sig[63] & 0x80:
        return False
    a = _decode(pub)
    r = _decode(sig[:32])
    if a is None or r is None:
        return False
    left = _mult(G, int.from_bytes(sig[32:], 'little'))
    right = _add(r, _mult(a, _hint(sig[:32] + pub + message)))
    return _encode(left) == _encode(right)


# Release public key, compiled in. Empty refuses every feed; never accept
# an unsigned feed.
FEED_PUBLIC_KEY = '8e5a2ef7fc48913e65fc02329d9ffae43261abacc4d14c9aeef266f4ca4665a7'


def trusted_keys():
    """Compiled public keys; rotation adds a key, never a flag day."""
    keys = [k for k in FEED_PUBLIC_KEY.replace(',', ' ').split() if k]
    if not keys:
        raise SystemExit('no feed signing key configured; refusing unsigned feed')
    return keys


def trusted_key():
    return trusted_keys()[0]


def checked_feed(body, sig):
    """Verify exact feed bytes against a detached signature; return the doc."""
    try:
        sig_text = sig.decode('ascii').strip()
    except (UnicodeDecodeError, AttributeError):
        raise SystemExit('feed signature is not hex')
    if not any(verify_hex(key, body, sig_text) for key in trusted_keys()):
        raise SystemExit('feed signature rejected')
    return json.loads(body.decode())


def beta_feed_url(stable_url):
    """Beta feed on the same origin: <origin>/beta/latest.json. No GitHub API
    call; anonymous fetches work on the release CDN like stable does."""
    scheme, _, rest = stable_url.partition('://')
    host, _, _ = rest.partition('/')
    if not scheme or (not host and scheme != 'file'):
        raise SystemExit(f'cannot derive beta feed from {stable_url}')
    return f'{scheme}://{host}/beta/latest.json'
