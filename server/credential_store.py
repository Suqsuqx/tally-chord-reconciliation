"""Envelope-style encryption helper for merchant provider credentials."""
import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialStoreError(RuntimeError):
    pass


def _key():
    encoded = os.getenv("TALLY_CREDENTIAL_ENCRYPTION_KEY", "")
    try:
        key = base64.urlsafe_b64decode(encoded.encode())
    except (ValueError, TypeError) as exc:
        raise CredentialStoreError("Credential encryption is unavailable") from exc
    if len(key) != 32:
        raise CredentialStoreError("Credential encryption is unavailable")
    return key


def key_version():
    version = os.getenv("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", "v1")
    if not version or len(version) > 40:
        raise CredentialStoreError("Credential encryption version is invalid")
    return version


def encrypt_credentials(value, associated_data):
    if not isinstance(value, dict) or not isinstance(associated_data, str):
        raise CredentialStoreError("Invalid credential payload")
    nonce = os.urandom(12)
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ciphertext = AESGCM(_key()).encrypt(nonce, raw, associated_data.encode())
    return base64.urlsafe_b64encode(nonce + ciphertext).decode(), key_version()


def decrypt_credentials(ciphertext, stored_key_version, associated_data):
    if stored_key_version != key_version():
        raise CredentialStoreError("Credential key version is unavailable")
    try:
        packed = base64.urlsafe_b64decode(ciphertext.encode())
        raw = AESGCM(_key()).decrypt(packed[:12], packed[12:], associated_data.encode())
        value = json.loads(raw)
    except Exception as exc:
        raise CredentialStoreError("Credential decryption failed") from exc
    if not isinstance(value, dict):
        raise CredentialStoreError("Credential payload is invalid")
    return value
