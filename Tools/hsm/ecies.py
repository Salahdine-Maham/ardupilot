#!/usr/bin/env python3
"""
ECIES (Elliptic Curve Integrated Encryption Scheme) Implementation

Utilise:
- ECDH sur secp256r1 (P-256) pour l'échange de clé
- HKDF-SHA256 pour la dérivation de clé
- ChaCha20-Poly1305 pour le chiffrement AEAD

Compatible avec l'implémentation C++ de KeyExchangeProtocol.

Date: 2026-01-24
"""

import os
import hashlib
import hmac
from typing import Tuple, Optional

# Utiliser cryptography library
try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("WARNING: cryptography library not available. Install with: pip install cryptography")


# Constants
CURVE = ec.SECP256R1()
KEY_SIZE = 32
NONCE_SIZE = 12
TAG_SIZE = 16
PUBKEY_SIZE = 64  # Uncompressed X||Y (sans le prefix 0x04)

# HKDF parameters (must match C++ implementation)
ECIES_SALT = b"ECIES-Salt"
ECIES_INFO = b"DEK-Encryption-v1"


class ECIES:
    """
    ECIES encryption/decryption for DEK exchange
    """

    @staticmethod
    def generate_keypair() -> Tuple[bytes, bytes]:
        """
        Generate a new P-256 keypair

        Returns:
            Tuple[private_key (32 bytes), public_key (64 bytes)]
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required")

        private_key = ec.generate_private_key(CURVE, default_backend())
        public_key = private_key.public_key()

        # Export private key as raw bytes
        private_bytes = private_key.private_numbers().private_value.to_bytes(32, 'big')

        # Export public key as uncompressed X||Y (64 bytes)
        public_numbers = public_key.public_numbers()
        public_bytes = (
            public_numbers.x.to_bytes(32, 'big') +
            public_numbers.y.to_bytes(32, 'big')
        )

        return private_bytes, public_bytes

    @staticmethod
    def derive_public_key(private_key: bytes) -> bytes:
        """
        Derive public key from private key

        Args:
            private_key: 32 bytes private key

        Returns:
            64 bytes public key (X||Y)
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required")

        # Load private key
        private_int = int.from_bytes(private_key, 'big')
        private_key_obj = ec.derive_private_key(private_int, CURVE, default_backend())
        public_key = private_key_obj.public_key()

        # Export as X||Y
        public_numbers = public_key.public_numbers()
        return (
            public_numbers.x.to_bytes(32, 'big') +
            public_numbers.y.to_bytes(32, 'big')
        )

    @staticmethod
    def ecdh(private_key: bytes, peer_public_key: bytes) -> bytes:
        """
        Perform ECDH to derive shared secret

        Args:
            private_key: Our private key (32 bytes)
            peer_public_key: Peer's public key (64 bytes X||Y)

        Returns:
            Shared secret (32 bytes)
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required")

        # Load our private key
        private_int = int.from_bytes(private_key, 'big')
        private_key_obj = ec.derive_private_key(private_int, CURVE, default_backend())

        # Load peer's public key
        x = int.from_bytes(peer_public_key[:32], 'big')
        y = int.from_bytes(peer_public_key[32:], 'big')
        public_numbers = ec.EllipticCurvePublicNumbers(x, y, CURVE)
        peer_public_key_obj = public_numbers.public_key(default_backend())

        # Perform ECDH
        shared_key = private_key_obj.exchange(ec.ECDH(), peer_public_key_obj)

        return shared_key

    @staticmethod
    def hkdf_derive(shared_secret: bytes, salt: bytes = ECIES_SALT,
                    info: bytes = ECIES_INFO, length: int = KEY_SIZE) -> bytes:
        """
        Derive encryption key using HKDF-SHA256

        Args:
            shared_secret: Input key material
            salt: HKDF salt
            info: HKDF info
            length: Output length

        Returns:
            Derived key
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required")

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=salt,
            info=info,
            backend=default_backend()
        )
        return hkdf.derive(shared_secret)

    @staticmethod
    def encrypt_dek(peer_wk_public: bytes, dek: bytes) -> Tuple[bytes, bytes, bytes, bytes]:
        """
        Encrypt DEK using ECIES for a peer

        Args:
            peer_wk_public: Peer's Wrapper Key public (64 bytes)
            dek: DEK to encrypt (32 bytes)

        Returns:
            Tuple[ephemeral_public (64 bytes), encrypted_dek (32 bytes),
                  nonce (12 bytes), tag (16 bytes)]
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required")

        # 1. Generate ephemeral keypair
        ephemeral_private, ephemeral_public = ECIES.generate_keypair()

        # 2. ECDH with peer's public key
        shared_secret = ECIES.ecdh(ephemeral_private, peer_wk_public)

        # 3. Derive encryption key via HKDF
        encryption_key = ECIES.hkdf_derive(shared_secret)

        # 4. Generate random nonce
        nonce = os.urandom(NONCE_SIZE)

        # 5. Encrypt with ChaCha20-Poly1305
        chacha = ChaCha20Poly1305(encryption_key)
        ciphertext_with_tag = chacha.encrypt(nonce, dek, None)

        # Split ciphertext and tag
        encrypted_dek = ciphertext_with_tag[:KEY_SIZE]
        tag = ciphertext_with_tag[KEY_SIZE:]

        # Clear sensitive data
        del ephemeral_private
        del shared_secret
        del encryption_key

        return ephemeral_public, encrypted_dek, nonce, tag

    @staticmethod
    def decrypt_dek(my_wk_private: bytes, ephemeral_public: bytes,
                    encrypted_dek: bytes, nonce: bytes, tag: bytes) -> Optional[bytes]:
        """
        Decrypt DEK received via ECIES

        Args:
            my_wk_private: Our Wrapper Key private (32 bytes)
            ephemeral_public: Sender's ephemeral public key (64 bytes)
            encrypted_dek: Encrypted DEK (32 bytes)
            nonce: ChaCha20 nonce (12 bytes)
            tag: Poly1305 tag (16 bytes)

        Returns:
            Decrypted DEK (32 bytes) or None if decryption fails
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required")

        try:
            # 1. ECDH with ephemeral public key
            shared_secret = ECIES.ecdh(my_wk_private, ephemeral_public)

            # 2. Derive same encryption key
            encryption_key = ECIES.hkdf_derive(shared_secret)

            # 3. Decrypt with ChaCha20-Poly1305
            chacha = ChaCha20Poly1305(encryption_key)
            ciphertext_with_tag = encrypted_dek + tag
            dek = chacha.decrypt(nonce, ciphertext_with_tag, None)

            # Clear sensitive data
            del shared_secret
            del encryption_key

            return dek

        except Exception as e:
            print(f"[ECIES] Decryption failed: {e}")
            return None


# =============================================================================
# TEST
# =============================================================================

def test_ecies():
    """Test ECIES encrypt/decrypt roundtrip"""
    print("=" * 50)
    print("  ECIES Test")
    print("=" * 50)

    if not CRYPTO_AVAILABLE:
        print("SKIP: cryptography library not available")
        return False

    # Generate keypairs for Alice and Bob
    print("\n1. Generating keypairs...")
    alice_private, alice_public = ECIES.generate_keypair()
    bob_private, bob_public = ECIES.generate_keypair()
    print(f"   Alice public: {alice_public[:8].hex()}...")
    print(f"   Bob public:   {bob_public[:8].hex()}...")

    # Alice's DEK to send to Bob
    alice_dek = os.urandom(32)
    print(f"\n2. Alice DEK: {alice_dek[:8].hex()}...")

    # Alice encrypts DEK for Bob
    print("\n3. Alice encrypts DEK for Bob...")
    ephemeral_pub, encrypted_dek, nonce, tag = ECIES.encrypt_dek(bob_public, alice_dek)
    print(f"   Ephemeral pub: {ephemeral_pub[:8].hex()}...")
    print(f"   Encrypted DEK: {encrypted_dek[:8].hex()}...")
    print(f"   Nonce: {nonce.hex()}")
    print(f"   Tag: {tag.hex()}")

    # Bob decrypts DEK
    print("\n4. Bob decrypts DEK...")
    decrypted_dek = ECIES.decrypt_dek(bob_private, ephemeral_pub, encrypted_dek, nonce, tag)

    if decrypted_dek is None:
        print("   FAILED: Decryption returned None")
        return False

    print(f"   Decrypted DEK: {decrypted_dek[:8].hex()}...")

    # Verify
    if decrypted_dek == alice_dek:
        print("\n*** TEST PASSED: DEK matches! ***")
        return True
    else:
        print("\n*** TEST FAILED: DEK mismatch! ***")
        return False


if __name__ == '__main__':
    success = test_ecies()
    exit(0 if success else 1)
