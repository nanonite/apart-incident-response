"""Password-based authenticated encryption for the experiment assets.

Standard library only. Construction (encrypt-then-MAC):

    key        = PBKDF2-HMAC-SHA256(password, salt, ITERATIONS)          64 bytes
    enc_key    = key[:32]            mac_key = key[32:]
    keystream  = SHAKE-256(b"apart-stream" || enc_key || nonce), len(plaintext)
    ciphertext = plaintext XOR keystream
    tag        = HMAC-SHA256(mac_key, salt || nonce || ciphertext)

Only the ciphertext envelope is kept by the harness. A wrong password fails the
constant-time tag check, so no plaintext (not even garbage) is ever produced.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
from dataclasses import asdict, dataclass

ITERATIONS = 600_000
_PASSWORD_ALPHABET = string.ascii_letters + string.digits
_STRIP = " \t\r\n\"'`“”‘’<>[](){}.,;:!?*"


@dataclass(frozen=True)
class Envelope:
    salt: str
    nonce: str
    ciphertext: str
    tag: str
    iterations: int = ITERATIONS
    scheme: str = "pbkdf2-sha256/shake256-xor/hmac-sha256"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "Envelope":
        return cls(**raw)  # type: ignore[arg-type]


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _keys(password: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=64)
    return key[:32], key[32:]


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    return hashlib.shake_256(b"apart-stream" + enc_key + nonce).digest(length)


def encrypt(plaintext: str, password: str, *, rng: secrets.SystemRandom | None = None,
            iterations: int = ITERATIONS) -> Envelope:
    data = plaintext.encode("utf-8")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _keys(password, salt, iterations)
    ciphertext = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    return Envelope(_b64(salt), _b64(nonce), _b64(ciphertext), _b64(tag), iterations)


def decrypt(envelope: Envelope, password: str) -> str | None:
    """Return the plaintext, or None if the password is wrong."""

    salt, nonce = _unb64(envelope.salt), _unb64(envelope.nonce)
    ciphertext, tag = _unb64(envelope.ciphertext), _unb64(envelope.tag)
    enc_key, mac_key = _keys(password, salt, envelope.iterations)
    expected = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        return None
    data = bytes(a ^ b for a, b in zip(ciphertext, _keystream(enc_key, nonce, len(ciphertext))))
    return data.decode("utf-8")


def normalize_password(raw: str) -> str:
    """Strip quoting and punctuation a model wraps around a password; keep case."""

    text = raw.strip().splitlines()[0] if raw.strip() else ""
    return text.strip(_STRIP)


def compact(text: str) -> str:
    """Case-folded alphanumerics only: used to spot a password copied into free text."""

    return "".join(ch for ch in text.casefold() if ch.isalnum())


def generate_password(rng) -> str:
    """Four groups of four alphanumerics (~95 bits), e.g. k7Rq-vT92-mZ4x-Lp8n."""

    return "-".join("".join(rng.choice(_PASSWORD_ALPHABET) for _ in range(4)) for _ in range(4))
