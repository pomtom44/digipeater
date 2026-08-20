"""Password hashing for the web UI's security mode, using PBKDF2-HMAC-SHA256."""

import hashlib
import secrets

_ITERATIONS = 100_000


def hash_password(password: str) -> dict:
    """Returns {"salt": hex, "hash": hex}; store both, discard the password."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return {"salt": salt, "hash": digest.hex()}


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Verifies a password against a stored salt and hash, using constant-time comparison."""
    if not salt or not expected_hash:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return secrets.compare_digest(digest.hex(), expected_hash)
