import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# AES-256-GCM encryption for PII (phone numbers) at rest.
# Format: base64(iv):base64(authTag):base64(ciphertext)
# Must stay byte-for-byte compatible with frontend/src/lib/crypto.ts, which
# encrypts phone numbers before they're written to the same Postgres row.


def _get_key() -> bytes:
    hex_key = os.getenv("PHONE_ENCRYPTION_KEY")
    if not hex_key or len(hex_key) != 64:
        raise ValueError(
            "PHONE_ENCRYPTION_KEY must be set to a 64-character hex string (32 bytes). "
            "Generate one with: openssl rand -hex 32"
        )
    return bytes.fromhex(hex_key)


def encrypt_phone(phone: str) -> str:
    key = _get_key()
    iv = os.urandom(12)
    aesgcm = AESGCM(key)
    combined = aesgcm.encrypt(iv, phone.encode("utf-8"), None)
    ciphertext, tag = combined[:-16], combined[-16:]
    return ":".join(
        base64.b64encode(part).decode("ascii") for part in (iv, tag, ciphertext)
    )


def decrypt_phone(value: str) -> str:
    """
    Decrypts a phone number encrypted by encrypt_phone (or the frontend's
    encryptPhone). Returns the input unchanged if it doesn't look like
    ciphertext (e.g. legacy plaintext rows written before encryption was
    introduced), so existing data doesn't break.
    """
    parts = value.split(":")
    if len(parts) != 3:
        return value

    try:
        iv, tag, ciphertext = (base64.b64decode(p) for p in parts)
        aesgcm = AESGCM(_get_key())
        plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
        return plaintext.decode("utf-8")
    except Exception:
        return value
