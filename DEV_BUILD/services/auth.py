"""Password hashing for the web UI's security mode.

PBKDF2-HMAC-SHA256 with a random salt and a real iteration count — stdlib
only (hashlib.pbkdf2_hmac), no new dependency needed. ORIGINAL stored this
password in plaintext in config.yaml (compared with a bare `==`); nothing
here needs the plaintext back once it's been checked, so there's no reason
to keep it around at rest.
"""

import hashlib
import secrets

_ITERATIONS = 100_000


def hash_password(password: str) -> dict:
    """Returns {"salt": hex, "hash": hex} — store both, discard the password."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return {"salt": salt, "hash": digest.hex()}
