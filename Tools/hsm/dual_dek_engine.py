#!/usr/bin/env python3
"""
DualDekEngine - MAVLink Payload Encryption/Decryption for GCS

Feature 3: Transparent encryption using XChaCha20-Poly1305 (PyNaCl)

Usage:
    from dual_dek_engine import DualDekEngine
    dde = DualDekEngine(my_dek, peer_deks)
    ciphertext = dde.encrypt(payload)
    plaintext = dde.decrypt(src_sysid, ciphertext)

Date: 2026-01-25
"""

import os
from typing import Dict, Optional, Tuple

try:
    import nacl.bindings
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False
    print("WARNING: PyNaCl not available. Install with: pip install pynacl")


# Constants (must match C++ DualDekEngine)
KEY_SIZE = 32
NONCE_SIZE = 24      # XChaCha20-Poly1305
TAG_SIZE = 16
HEADER_SIZE = NONCE_SIZE + TAG_SIZE  # 40 bytes overhead
MAX_PAYLOAD = 255

# Message IDs that should NOT be encrypted
PLAINTEXT_MSGIDS = {
    0,      # HEARTBEAT
    12000,  # HSM_WK_EXCHANGE
    12001,  # HSM_DEK_EXCHANGE
    12002,  # HSM_KEY_ACK
}


class DualDekEngine:
    """
    Dual-DEK encryption engine for MAVLink payloads

    - MY_DEK: Used to encrypt outgoing messages
    - PEER_DEKs: Used to decrypt incoming messages (indexed by sysid)
    """

    def __init__(self, my_dek: bytes = None):
        """
        Initialize the engine

        Args:
            my_dek: Our DEK for encrypting outgoing messages (32 bytes)
        """
        if not NACL_AVAILABLE:
            raise RuntimeError("PyNaCl required for DualDekEngine")

        self._my_dek = my_dek
        self._peer_deks: Dict[int, bytes] = {}  # sysid -> DEK

        # Statistics
        self._stats = {
            'tx_encrypted': 0,
            'tx_plaintext': 0,
            'rx_decrypted': 0,
            'rx_failed': 0,
            'rx_plaintext': 0,
        }

    def set_my_dek(self, dek: bytes):
        """Set our DEK for encryption"""
        if len(dek) != KEY_SIZE:
            raise ValueError(f"DEK must be {KEY_SIZE} bytes")
        self._my_dek = dek

    def set_peer_dek(self, sysid: int, dek: bytes):
        """Set a peer's DEK for decryption"""
        if len(dek) != KEY_SIZE:
            raise ValueError(f"DEK must be {KEY_SIZE} bytes")
        self._peer_deks[sysid] = dek
        print(f"[DDE] Peer DEK set for sysid={sysid}: {dek[:4].hex()}...")

    def get_peer_dek(self, sysid: int) -> Optional[bytes]:
        """Get a peer's DEK"""
        return self._peer_deks.get(sysid)

    def is_ready(self) -> bool:
        """Check if encryption is ready"""
        return self._my_dek is not None

    @staticmethod
    def should_encrypt(msgid: int) -> bool:
        """Check if a message should be encrypted"""
        return msgid not in PLAINTEXT_MSGIDS

    def encrypt(self, plaintext: bytes) -> Optional[bytes]:
        """
        Encrypt a payload for transmission

        Args:
            plaintext: Original payload data

        Returns:
            Encrypted data: nonce(24) + tag(16) + ciphertext(N)
            None if encryption fails
        """
        if self._my_dek is None:
            print("[DDE] Cannot encrypt - MY_DEK not set")
            return None

        if len(plaintext) > MAX_PAYLOAD:
            print(f"[DDE] Payload too large ({len(plaintext)} > {MAX_PAYLOAD})")
            return None

        # Generate random nonce
        nonce = os.urandom(NONCE_SIZE)

        # Encrypt with XChaCha20-Poly1305
        # Returns: ciphertext + tag (tag appended)
        try:
            ciphertext_with_tag = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_encrypt(
                plaintext, None, nonce, self._my_dek
            )

            # Split ciphertext and tag
            ciphertext = ciphertext_with_tag[:-TAG_SIZE]
            tag = ciphertext_with_tag[-TAG_SIZE:]

            # Output format: nonce + tag + ciphertext
            result = nonce + tag + ciphertext

            self._stats['tx_encrypted'] += 1
            return result

        except Exception as e:
            print(f"[DDE] Encryption failed: {e}")
            return None

    def decrypt(self, src_sysid: int, ciphertext: bytes) -> Optional[bytes]:
        """
        Decrypt a payload received from a peer

        Args:
            src_sysid: Source system ID (to lookup peer DEK)
            ciphertext: Encrypted data: nonce(24) + tag(16) + ciphertext(N)

        Returns:
            Decrypted plaintext or None if decryption fails
        """
        if len(ciphertext) <= HEADER_SIZE:
            print(f"[DDE] Ciphertext too short ({len(ciphertext)} <= {HEADER_SIZE})")
            self._stats['rx_failed'] += 1
            return None

        # Get peer's DEK
        peer_dek = self._peer_deks.get(src_sysid)
        if peer_dek is None:
            print(f"[DDE] No DEK for sysid={src_sysid}")
            self._stats['rx_failed'] += 1
            return None

        # Parse format: nonce(24) + tag(16) + ciphertext(N)
        nonce = ciphertext[:NONCE_SIZE]
        tag = ciphertext[NONCE_SIZE:HEADER_SIZE]
        ct = ciphertext[HEADER_SIZE:]

        # Decrypt with XChaCha20-Poly1305
        try:
            # PyNaCl expects ciphertext + tag concatenated
            ciphertext_with_tag = ct + tag

            plaintext = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
                ciphertext_with_tag, None, nonce, peer_dek
            )

            self._stats['rx_decrypted'] += 1
            return plaintext

        except Exception as e:
            print(f"[DDE] Decryption failed for sysid={src_sysid}: {e}")
            self._stats['rx_failed'] += 1
            return None

    def get_stats(self) -> dict:
        """Get statistics"""
        return self._stats.copy()

    def print_status(self):
        """Print status"""
        print("[DDE] STATUS")
        print(f"[DDE]   Ready: {'YES' if self.is_ready() else 'NO'}")
        print(f"[DDE]   Peers with DEK: {list(self._peer_deks.keys())}")
        print(f"[DDE]   TX encrypted: {self._stats['tx_encrypted']}")
        print(f"[DDE]   RX decrypted: {self._stats['rx_decrypted']}")
        print(f"[DDE]   RX failed: {self._stats['rx_failed']}")


# =============================================================================
# TEST
# =============================================================================

def test_dual_dek_engine():
    """Test DualDekEngine encrypt/decrypt roundtrip"""
    print("=" * 50)
    print("  DualDekEngine Test (XChaCha20-Poly1305)")
    print("=" * 50)

    if not NACL_AVAILABLE:
        print("SKIP: PyNaCl not available")
        return False

    # Simulate two parties: Drone (sysid=1) and GCS (sysid=255)
    drone_dek = os.urandom(KEY_SIZE)
    gcs_dek = os.urandom(KEY_SIZE)

    print(f"\n1. Keys generated:")
    print(f"   Drone DEK: {drone_dek[:8].hex()}...")
    print(f"   GCS DEK:   {gcs_dek[:8].hex()}...")

    # Initialize engines
    drone_dde = DualDekEngine(my_dek=drone_dek)
    drone_dde.set_peer_dek(255, gcs_dek)  # Drone knows GCS DEK

    gcs_dde = DualDekEngine(my_dek=gcs_dek)
    gcs_dde.set_peer_dek(1, drone_dek)    # GCS knows Drone DEK

    print("\n2. Engines initialized")

    # Test 1: Drone sends to GCS
    print("\n3. Test: Drone → GCS")
    test_payload = b"ATTITUDE data: roll=0.1, pitch=0.2, yaw=3.14"
    print(f"   Payload: {test_payload[:30]}...")

    encrypted = drone_dde.encrypt(test_payload)
    if encrypted is None:
        print("   FAILED: Encryption returned None")
        return False

    print(f"   Encrypted: {len(encrypted)} bytes (overhead: {len(encrypted) - len(test_payload)})")
    print(f"   Nonce: {encrypted[:8].hex()}...")

    decrypted = gcs_dde.decrypt(1, encrypted)  # sysid=1 is drone
    if decrypted is None:
        print("   FAILED: Decryption returned None")
        return False

    if decrypted != test_payload:
        print("   FAILED: Decrypted doesn't match original")
        return False

    print(f"   Decrypted: {decrypted[:30]}...")
    print("   ✓ Drone → GCS OK")

    # Test 2: GCS sends to Drone
    print("\n4. Test: GCS → Drone")
    cmd_payload = b"COMMAND_LONG: cmd=176 (DO_SET_MODE)"

    encrypted2 = gcs_dde.encrypt(cmd_payload)
    decrypted2 = drone_dde.decrypt(255, encrypted2)  # sysid=255 is GCS

    if decrypted2 != cmd_payload:
        print("   FAILED: Roundtrip failed")
        return False

    print(f"   ✓ GCS → Drone OK")

    # Test 3: Wrong key should fail
    print("\n5. Test: Wrong key (should fail)")
    wrong_dde = DualDekEngine(my_dek=os.urandom(KEY_SIZE))
    wrong_dde.set_peer_dek(1, os.urandom(KEY_SIZE))  # Wrong DEK

    bad_decrypt = wrong_dde.decrypt(1, encrypted)
    if bad_decrypt is not None:
        print("   FAILED: Should have failed with wrong key")
        return False

    print("   ✓ Auth failure detected correctly")

    # Print stats
    print("\n6. Statistics:")
    drone_dde.print_status()

    print("\n" + "=" * 50)
    print("  *** ALL TESTS PASSED ***")
    print("=" * 50)

    return True


if __name__ == '__main__':
    success = test_dual_dek_engine()
    exit(0 if success else 1)
