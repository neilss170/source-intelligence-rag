import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # argon2id with the library's current recommended cost

#: Verified against when an email is unknown, so a login for a missing
#: account takes as long as one with a wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(
            password_hash
        )
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> bytes:
    """What is stored for a session token: a leaked table cannot be replayed."""
    return hashlib.sha256(token.encode()).digest()


def tokens_match(expected: str, given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(expected.encode(), given.encode())
