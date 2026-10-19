"""
demonstration of message capture, replay attack, and replay protection
"""
import copy
import os
import sys

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.crypto import (
    CryptoError,
    ReplayError,
    TamperedMessageError,
    generate_key,
    encrypt_payload,
    decrypt_payload,
    ReplayProtection,
)
from core.message import Message


def main():
    print("=== MESHage Security & Replay Attack Demo ===")

    # 1. shared key and recipient replay guard
    shared_key = generate_key()
    node_b_replay_guard = ReplayProtection(window_seconds=30.0)

    # 2. Node A creates and encrypts a message for Node B
    print("\n1. Node A creates and encrypts a private message for Node B:")
    original_text = "transfer $50 to Alice"
    msg = Message(src="NodeA", dst="NodeB", payload=original_text, ttl=5)
    encrypted_msg = encrypt_payload(msg, shared_key)

    print(f"   [Node A] Plaintext:  '{original_text}'")
    print(f"   [Node A] Ciphertext: {encrypted_msg.payload[:32]}... (AES-GCM)")
    print(f"   [Node A] Nonce:      {encrypted_msg.nonce}")
    print(f"   [Node A] Message ID: {encrypted_msg.id}")

    # 3. Node B receives the legitimate message
    print("\n2. Node B receives the message over the mesh:")
    node_b_replay_guard.check_and_record(encrypted_msg)
    decrypted_text = decrypt_payload(encrypted_msg, shared_key)
    print(f"   [Node B] Verification passed. Decrypted: '{decrypted_text}'")

    # 4. Attacker captures the in-flight packet and attempts to replay it
    print("\n3. Attacker captures packet and attempts to replay it to Node B:")
    captured_packet = copy.deepcopy(encrypted_msg)
    print(f"   [Attacker] Re-broadcasting captured packet (id={captured_packet.id})...")

    try:
        node_b_replay_guard.check_and_record(captured_packet)
        decrypted_replay = decrypt_payload(captured_packet, shared_key)
        print(f"   [Node B] Warning: Replay accepted! Content: '{decrypted_replay}'")
    except ReplayError as e:
        print(f"   [Node B] {e}")
        print("Blocked")

    # 5. Attacker tries to modify timestamp or headers to bypass replay window
    print("\n4. Attacker tampers with packet ID and nonce to bypass replay cache:")
    tampered_packet = copy.deepcopy(encrypted_msg)
    tampered_packet.id = "spoofed-new-id-999"
    tampered_packet.nonce = os.urandom(12).hex()

    try:
        node_b_replay_guard.check_and_record(tampered_packet)
        decrypt_payload(tampered_packet, shared_key)
        print("   [Node B] Warning: Tampered message accepted!")
    except (TamperedMessageError, CryptoError) as e:
        print(f"   [Node B] Decryption failed: {e}")
        print("Blocked")


if __name__ == "__main__":
    main()
