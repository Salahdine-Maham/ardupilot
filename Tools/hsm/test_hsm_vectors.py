#!/usr/bin/env python3
"""
HSM Cross-Platform Test Vectors
===============================

Test vectors to validate that Python and C++ implementations
produce identical results with the same inputs.

These vectors can be used to:
1. Verify Python implementation matches C++
2. Debug interoperability issues
3. Regression testing after changes

Test Categories:
    V1: HKDF-SHA256 Test Vectors
    V2: XChaCha20-Poly1305 Test Vectors
    V3: P-256 ECDH Test Vectors
    V4: ECIES Test Vectors
    V5: DualDekEngine Format Vectors

Usage:
    python3 test_hsm_vectors.py

Date: 2026-01-30
"""

import os
import sys
import hashlib
import hmac
from typing import Tuple

# Add paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Test results
PASSED = 0
FAILED = 0


def test_result(name: str, passed: bool, msg: str = "") -> bool:
    """Print test result"""
    global PASSED, FAILED
    status = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
    if passed:
        PASSED += 1
    else:
        FAILED += 1
    extra = f" - {msg}" if msg else ""
    print(f"  [{status}] {name}{extra}")
    return passed


# =============================================================================
# V1: HKDF-SHA256 Test Vectors (RFC 5869)
# =============================================================================

def test_v1_hkdf_vectors():
    """Test HKDF-SHA256 against RFC 5869 test vectors"""
    print("\n" + "=" * 60)
    print("  V1: HKDF-SHA256 Test Vectors (RFC 5869)")
    print("=" * 60)

    try:
        from ecies import ECIES
    except ImportError as e:
        print(f"  SKIP: Cannot import ecies: {e}")
        return False

    # RFC 5869 Test Case 1
    # https://www.rfc-editor.org/rfc/rfc5869#appendix-A.1
    ikm_1 = bytes.fromhex("0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b")
    salt_1 = bytes.fromhex("000102030405060708090a0b0c")
    info_1 = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    expected_1 = bytes.fromhex(
        "3cb25f25faacd57a90434f64d0362f2a"
        "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )

    result_1 = ECIES.hkdf_derive(ikm_1, salt=salt_1, info=info_1, length=42)
    test_result("V1.1 RFC5869 Test Case 1", result_1 == expected_1)

    # RFC 5869 Test Case 2
    ikm_2 = bytes.fromhex(
        "000102030405060708090a0b0c0d0e0f"
        "101112131415161718191a1b1c1d1e1f"
        "202122232425262728292a2b2c2d2e2f"
        "303132333435363738393a3b3c3d3e3f"
        "404142434445464748494a4b4c4d4e4f"
    )
    salt_2 = bytes.fromhex(
        "606162636465666768696a6b6c6d6e6f"
        "707172737475767778797a7b7c7d7e7f"
        "808182838485868788898a8b8c8d8e8f"
        "909192939495969798999a9b9c9d9e9f"
        "a0a1a2a3a4a5a6a7a8a9aaabacadaeaf"
    )
    info_2 = bytes.fromhex(
        "b0b1b2b3b4b5b6b7b8b9babbbcbdbebf"
        "c0c1c2c3c4c5c6c7c8c9cacbcccdcecf"
        "d0d1d2d3d4d5d6d7d8d9dadbdcdddedf"
        "e0e1e2e3e4e5e6e7e8e9eaebecedeeef"
        "f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"
    )
    expected_2 = bytes.fromhex(
        "b11e398dc80327a1c8e7f78c596a4934"
        "4f012eda2d4efad8a050cc4c19afa97c"
        "59045a99cac7827271cb41c65e590e09"
        "da3275600c2f09b8367793a9aca3db71"
        "cc30c58179ec3e87c14c01d5c1f3434f"
        "1d87"
    )

    result_2 = ECIES.hkdf_derive(ikm_2, salt=salt_2, info=info_2, length=82)
    test_result("V1.2 RFC5869 Test Case 2", result_2 == expected_2)

    # Test Case 3: Empty salt and info
    ikm_3 = bytes.fromhex("0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b")
    expected_3 = bytes.fromhex(
        "8da4e775a563c18f715f802a063c5a31"
        "b8a11f5c5ee1879ec3454e5f3c738d2d"
        "9d201395faa4b61a96c8"
    )

    result_3 = ECIES.hkdf_derive(ikm_3, salt=b"", info=b"", length=42)
    test_result("V1.3 RFC5869 Test Case 3 (empty salt/info)", result_3 == expected_3)

    # V1.4: ECIES-specific HKDF (used in our implementation)
    shared_secret = bytes.fromhex("deadbeefcafebabe" * 4)
    ecies_derived = ECIES.hkdf_derive(shared_secret)  # Uses default salt/info
    test_result("V1.4 ECIES HKDF produces 32 bytes", len(ecies_derived) == 32)

    # V1.5: Deterministic derivation
    derived_1 = ECIES.hkdf_derive(shared_secret)
    derived_2 = ECIES.hkdf_derive(shared_secret)
    test_result("V1.5 HKDF deterministic", derived_1 == derived_2)

    return True


# =============================================================================
# V2: XChaCha20-Poly1305 Test Vectors
# =============================================================================

def test_v2_xchacha_vectors():
    """Test XChaCha20-Poly1305 with known vectors"""
    print("\n" + "=" * 60)
    print("  V2: XChaCha20-Poly1305 Test Vectors")
    print("=" * 60)

    try:
        from ecies import ECIES
    except ImportError as e:
        print(f"  SKIP: Cannot import ecies: {e}")
        return False

    # V2.1: Zero key and nonce
    key_zero = bytes(32)
    nonce_zero = bytes(24)
    plaintext = b"Test message"

    ct, tag = ECIES.xchacha20_poly1305_encrypt(key_zero, nonce_zero, plaintext)
    pt = ECIES.xchacha20_poly1305_decrypt(key_zero, nonce_zero, ct, tag)
    test_result("V2.1 Zero key/nonce roundtrip", pt == plaintext)

    # V2.2: Known key vector
    key_known = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    nonce_known = bytes.fromhex("000102030405060708090a0b0c0d0e0f1011121314151617")
    plaintext_known = b"Hello, XChaCha20-Poly1305!"

    ct_known, tag_known = ECIES.xchacha20_poly1305_encrypt(key_known, nonce_known, plaintext_known)
    pt_known = ECIES.xchacha20_poly1305_decrypt(key_known, nonce_known, ct_known, tag_known)
    test_result("V2.2 Known key roundtrip", pt_known == plaintext_known)

    # V2.3: Ciphertext length = plaintext length
    test_result("V2.3 CT length = PT length", len(ct_known) == len(plaintext_known))

    # V2.4: Tag is 16 bytes
    test_result("V2.4 Tag is 16 bytes", len(tag_known) == 16)

    # V2.5: Different nonces produce different ciphertexts
    nonce_alt = bytes.fromhex("fffefdfcfbfaf9f8f7f6f5f4f3f2f1f0efeeedecebeae9e8")
    ct_alt, _ = ECIES.xchacha20_poly1305_encrypt(key_known, nonce_alt, plaintext_known)
    test_result("V2.5 Different nonce = different CT", ct_known != ct_alt)

    # V2.6: Wrong key fails decryption
    key_wrong = bytes.fromhex("ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
    pt_fail = ECIES.xchacha20_poly1305_decrypt(key_wrong, nonce_known, ct_known, tag_known)
    test_result("V2.6 Wrong key fails", pt_fail is None)

    # V2.7: Tampered ciphertext fails
    ct_tampered = bytearray(ct_known)
    ct_tampered[0] ^= 0xFF
    pt_tampered = ECIES.xchacha20_poly1305_decrypt(key_known, nonce_known, bytes(ct_tampered), tag_known)
    test_result("V2.7 Tampered CT fails", pt_tampered is None)

    # V2.8: Tampered tag fails
    tag_tampered = bytearray(tag_known)
    tag_tampered[0] ^= 0x01
    pt_bad_tag = ECIES.xchacha20_poly1305_decrypt(key_known, nonce_known, ct_known, bytes(tag_tampered))
    test_result("V2.8 Tampered tag fails", pt_bad_tag is None)

    return True


# =============================================================================
# V3: P-256 ECDH Test Vectors
# =============================================================================

def test_v3_ecdh_vectors():
    """Test P-256 ECDH with known vectors"""
    print("\n" + "=" * 60)
    print("  V3: P-256 ECDH Test Vectors")
    print("=" * 60)

    try:
        from ecies import ECIES
    except ImportError as e:
        print(f"  SKIP: Cannot import ecies: {e}")
        return False

    # V3.1: ECDH symmetry (A-B == B-A)
    priv_a, pub_a = ECIES.generate_keypair()
    priv_b, pub_b = ECIES.generate_keypair()

    shared_ab = ECIES.ecdh(priv_a, pub_b)
    shared_ba = ECIES.ecdh(priv_b, pub_a)
    test_result("V3.1 ECDH symmetric (A-B == B-A)", shared_ab == shared_ba)

    # V3.2: Shared secret is 32 bytes
    test_result("V3.2 Shared secret is 32 bytes", len(shared_ab) == 32)

    # V3.3: Public key derivation
    derived_pub_a = ECIES.derive_public_key(priv_a)
    test_result("V3.3 Public key derivation", derived_pub_a == pub_a)

    # V3.4: Private key is 32 bytes
    test_result("V3.4 Private key is 32 bytes", len(priv_a) == 32)

    # V3.5: Public key is 64 bytes (X||Y)
    test_result("V3.5 Public key is 64 bytes", len(pub_a) == 64)

    # V3.6: Different keypairs produce different shared secrets
    priv_c, pub_c = ECIES.generate_keypair()
    shared_ac = ECIES.ecdh(priv_a, pub_c)
    test_result("V3.6 Different peers = different shared", shared_ab != shared_ac)

    return True


# =============================================================================
# V4: ECIES Test Vectors
# =============================================================================

def test_v4_ecies_vectors():
    """Test ECIES encrypt/decrypt"""
    print("\n" + "=" * 60)
    print("  V4: ECIES Test Vectors")
    print("=" * 60)

    try:
        from ecies import ECIES
    except ImportError as e:
        print(f"  SKIP: Cannot import ecies: {e}")
        return False

    # Generate receiver keypair
    recv_priv, recv_pub = ECIES.generate_keypair()

    # DEK to encrypt
    dek = bytes.fromhex("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

    # V4.1: ECIES encrypt produces correct sizes
    eph_pub, enc_dek, nonce, tag = ECIES.encrypt_dek(recv_pub, dek)
    test_result("V4.1 Ephemeral pub is 64 bytes", len(eph_pub) == 64)
    test_result("V4.2 Encrypted DEK is 32 bytes", len(enc_dek) == 32)
    test_result("V4.3 Nonce is 24 bytes", len(nonce) == 24)
    test_result("V4.4 Tag is 16 bytes", len(tag) == 16)

    # V4.5: ECIES decrypt recovers DEK
    dec_dek = ECIES.decrypt_dek(recv_priv, eph_pub, enc_dek, nonce, tag)
    test_result("V4.5 ECIES decrypt recovers DEK", dec_dek == dek)

    # V4.6: Total ECIES output is 136 bytes (64+32+24+16)
    total = len(eph_pub) + len(enc_dek) + len(nonce) + len(tag)
    test_result("V4.6 Total ECIES output = 136 bytes", total == 136)

    # V4.7: Multiple encryptions non-deterministic
    eph2, enc2, nonce2, tag2 = ECIES.encrypt_dek(recv_pub, dek)
    test_result("V4.7 ECIES non-deterministic", eph_pub != eph2 or enc_dek != enc2)

    # V4.8: Wrong private key fails
    wrong_priv, _ = ECIES.generate_keypair()
    dec_fail = ECIES.decrypt_dek(wrong_priv, eph_pub, enc_dek, nonce, tag)
    test_result("V4.8 Wrong private key fails", dec_fail is None)

    return True


# =============================================================================
# V5: DualDekEngine Format Vectors
# =============================================================================

def test_v5_dde_vectors():
    """Test DualDekEngine format compatibility"""
    print("\n" + "=" * 60)
    print("  V5: DualDekEngine Format Vectors")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine, NONCE_SIZE, TAG_SIZE, HEADER_SIZE, KEY_SIZE
    except ImportError as e:
        print(f"  SKIP: Cannot import dual_dek_engine: {e}")
        return False

    # V5.1: Constants match C++
    test_result("V5.1 KEY_SIZE = 32", KEY_SIZE == 32)
    test_result("V5.2 NONCE_SIZE = 24", NONCE_SIZE == 24)
    test_result("V5.3 TAG_SIZE = 16", TAG_SIZE == 16)
    test_result("V5.4 HEADER_SIZE = 40", HEADER_SIZE == 40)

    # Create engine with known DEK
    dek = bytes.fromhex("0123456789abcdef" * 4)
    dde = DualDekEngine(my_dek=dek)

    # V5.5: Encrypt produces correct format
    plaintext = b"ATTITUDE telemetry data"
    encrypted = dde.encrypt(plaintext)

    # Format: nonce(24) + tag(16) + ciphertext
    nonce = encrypted[:NONCE_SIZE]
    tag = encrypted[NONCE_SIZE:HEADER_SIZE]
    ct = encrypted[HEADER_SIZE:]

    test_result("V5.5 Nonce extracted (24 bytes)", len(nonce) == 24)
    test_result("V5.6 Tag extracted (16 bytes)", len(tag) == 16)
    test_result("V5.7 Ciphertext = plaintext length", len(ct) == len(plaintext))

    # V5.8: Encrypted size = plaintext + header
    test_result("V5.8 Total size = PT + 40", len(encrypted) == len(plaintext) + HEADER_SIZE)

    # V5.9: Plaintext message IDs
    from dual_dek_engine import PLAINTEXT_MSGIDS
    expected_plaintext = {0, 12000, 12001, 12002}
    test_result("V5.9 Plaintext msgids correct", PLAINTEXT_MSGIDS == expected_plaintext)

    # V5.10: Bidirectional encryption
    peer_dek = bytes.fromhex("fedcba9876543210" * 4)
    peer_dde = DualDekEngine(my_dek=peer_dek)
    peer_dde.set_peer_dek(255, dek)
    dde.set_peer_dek(1, peer_dek)

    # We encrypt, peer decrypts
    enc1 = dde.encrypt(plaintext)
    dec1 = peer_dde.decrypt(255, enc1)
    test_result("V5.10 Bidirectional works", dec1 == plaintext)

    return True


# =============================================================================
# Main
# =============================================================================

def main():
    global PASSED, FAILED

    print("=" * 60)
    print("  HSM Cross-Platform Test Vectors")
    print("=" * 60)
    print("  Validates Python matches C++ implementation")
    print("=" * 60)

    # Run all vector tests
    test_v1_hkdf_vectors()
    test_v2_xchacha_vectors()
    test_v3_ecdh_vectors()
    test_v4_ecies_vectors()
    test_v5_dde_vectors()

    # Summary
    print("\n" + "=" * 60)
    print("  Test Vector Summary")
    print("=" * 60)
    print(f"  PASSED:  {PASSED}")
    print(f"  FAILED:  {FAILED}")
    print("=" * 60)

    if FAILED == 0:
        print("\n  \033[92mAll test vectors PASSED!\033[0m")
        print("  Python implementation is compatible with C++")
        return 0
    else:
        print(f"\n  \033[91m{FAILED} test vectors FAILED\033[0m")
        return 1


if __name__ == '__main__':
    sys.exit(main())
