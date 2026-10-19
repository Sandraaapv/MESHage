"""
unit tests for core/crypto.py
"""
import copy
import os
import sys
import time
import unittest

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.crypto import (
    CryptoError,
    TamperedMessageError,
    ReplayError,
    generate_key,
    load_key,
    encrypt_payload,
    decrypt_payload,
    ReplayProtection,
)
from core.message import Message


class TestCrypto(unittest.TestCase):
    def setUp(self):
        self.key = generate_key()
        self.test_payload = "confidential mesh chat 123"
        self.msg = Message(
            src="NodeA",
            dst="NodeB",
            payload=self.test_payload,
            ttl=5,
        )

    def test_successful_decrypt_at_destination(self):
        # encrypt payload
        encrypted = encrypt_payload(copy.deepcopy(self.msg), self.key)

        # verify headers are readable in plaintext
        self.assertEqual(encrypted.src, "NodeA")
        self.assertEqual(encrypted.dst, "NodeB")
        self.assertEqual(encrypted.ttl, 5)
        self.assertTrue(len(encrypted.nonce) > 0)
        self.assertNotEqual(encrypted.payload, self.test_payload)

        # decrypt at destination
        decrypted_text = decrypt_payload(encrypted, self.key)
        self.assertEqual(decrypted_text, self.test_payload)

    def test_failure_wrong_key(self):
        encrypted = encrypt_payload(copy.deepcopy(self.msg), self.key)
        wrong_key = generate_key()

        with self.assertRaises(CryptoError):
            decrypt_payload(encrypted, wrong_key)

    def test_tampered_message_rejected(self):
        encrypted = encrypt_payload(copy.deepcopy(self.msg), self.key)

        # 1. tamper with ciphertext payload
        tampered_payload = copy.deepcopy(encrypted)
        ct_bytes = bytearray(bytes.fromhex(tampered_payload.payload))
        ct_bytes[0] ^= 0xFF
        tampered_payload.payload = ct_bytes.hex()

        with self.assertRaises(TamperedMessageError):
            decrypt_payload(tampered_payload, self.key)

        # 2. tamper with src header
        tampered_src = copy.deepcopy(encrypted)
        tampered_src.src = "Attacker"
        with self.assertRaises(TamperedMessageError):
            decrypt_payload(tampered_src, self.key)

        # 3. tamper with dst header
        tampered_dst = copy.deepcopy(encrypted)
        tampered_dst.dst = "NodeC"
        with self.assertRaises(TamperedMessageError):
            decrypt_payload(tampered_dst, self.key)

        # 4. tamper with message id header
        tampered_id = copy.deepcopy(encrypted)
        tampered_id.id = "fake-uuid-1234"
        with self.assertRaises(TamperedMessageError):
            decrypt_payload(tampered_id, self.key)

    def test_replayed_message_rejected(self):
        guard = ReplayProtection(window_seconds=30.0)
        encrypted = encrypt_payload(copy.deepcopy(self.msg), self.key)

        # first reception: accepted
        self.assertTrue(guard.check_and_record(encrypted, current_time=encrypted.timestamp))

        # replayed reception (same ID): rejected
        with self.assertRaises(ReplayError):
            guard.check_and_record(encrypted, current_time=encrypted.timestamp)

        # old timestamp outside window: rejected
        old_msg = Message(
            src="NodeA",
            dst="NodeB",
            payload="old message",
            timestamp=time.time() - 100.0,
        )
        encrypted_old = encrypt_payload(old_msg, self.key)
        with self.assertRaises(ReplayError):
            guard.check_and_record(encrypted_old, current_time=time.time())

    def test_relay_cannot_read_payload_and_forwards(self):
        # relay node forwards message without decrypting payload
        from core.router import FloodingRouter

        secret_text = "patient vital signs: stable"
        msg = Message(src="NodeA", dst="NodeC", payload=secret_text, ttl=5)
        encrypted = encrypt_payload(msg, self.key)

        # relay node B receives packet
        relay = FloodingRouter("NodeB", neighbors=["NodeA", "NodeC"])
        out_hops = relay.handle(encrypted, from_node="NodeA")

        # relay forwards packet to NodeC
        self.assertIn("NodeC", out_hops)
        self.assertIn("NodeB", encrypted.path)
        self.assertEqual(encrypted.ttl, 4)

        # relay cannot read payload with a wrong key
        relay_fake_key = generate_key()
        with self.assertRaises(CryptoError):
            decrypt_payload(encrypted, relay_fake_key)

        # destination NodeC receives and decrypts successfully
        destination_text = decrypt_payload(encrypted, self.key)
        self.assertEqual(destination_text, secret_text)


if __name__ == "__main__":
    unittest.main()
