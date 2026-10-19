"""
cryptography and replay protection for meshage
"""
import os
import time
from typing import Optional, Union
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.message import Message


class CryptoError(Exception):
    pass


class WrongKeyError(CryptoError):
    pass


class TamperedMessageError(CryptoError):
    pass


class ReplayError(CryptoError):
    pass


def generate_key() -> bytes:
    # generate a random 256-bit AES key
    return AESGCM.generate_key(bit_length=256)


def load_key(key_path: str = "config/secret.key") -> bytes:
    # load key from file or create one if missing
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return bytes.fromhex(content)

    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    key = generate_key()
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(key.hex())
    return key


def get_aad(message: Message) -> bytes:
    # bind immutable headers to the authentication tag
    return f"{message.id}:{message.src}:{message.dst}:{message.timestamp}".encode("utf-8")


def encrypt_payload(message: Message, key: Union[bytes, str]) -> Message:
    # encrypt payload with AES-GCM
    if isinstance(key, str):
        key = bytes.fromhex(key)

    # 12-byte standard nonce for AES-GCM
    nonce_bytes = os.urandom(12)
    message.nonce = nonce_bytes.hex()
    aad = get_aad(message)

    aes = AESGCM(key)
    ciphertext = aes.encrypt(nonce_bytes, message.payload.encode("utf-8"), aad)
    message.payload = ciphertext.hex()
    return message


def decrypt_payload(message: Message, key: Union[bytes, str]) -> str:
    # decrypt AES-GCM payload and verify authentication tag
    if isinstance(key, str):
        key = bytes.fromhex(key)

    if not message.nonce:
        raise CryptoError("Message is missing nonce")

    try:
        nonce_bytes = bytes.fromhex(message.nonce)
        ciphertext_bytes = bytes.fromhex(message.payload)
    except ValueError as e:
        raise TamperedMessageError("Invalid hex encoding in message") from e

    aad = get_aad(message)
    aes = AESGCM(key)

    try:
        plaintext_bytes = aes.decrypt(nonce_bytes, ciphertext_bytes, aad)
        return plaintext_bytes.decode("utf-8")
    except InvalidTag as e:
        raise TamperedMessageError("Decryption failed: wrong key or message was tampered with") from e


class ReplayProtection:
    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self.seen_ids = set()
        self.seen_nonces = set()

    def check_and_record(self, message: Message, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.time()

        # reject already seen message id or nonce
        if message.id in self.seen_ids or (message.nonce and message.nonce in self.seen_nonces):
            raise ReplayError("Blocked: message was already seen")

        # reject timestamp outside allowed time window
        if abs(now - message.timestamp) > self.window_seconds:
            raise ReplayError(f"Blocked: timestamp outside {self.window_seconds}s window")

        self.seen_ids.add(message.id)
        if message.nonce:
            self.seen_nonces.add(message.nonce)
        return True
