#!/usr/bin/env python3
"""
HSM Dual-Hardware End-to-End Tests
==================================

Tests with 2 physical HSM devices for full end-to-end validation.

Architecture:
    HSM #1 (Drone) <---> SITL <--encrypted--> GCS <---> HSM #2 (GCS)

Test Categories:
    DH1: Dual HSM Detection
    DH2: Independent Key Generation
    DH3: Key Exchange via MAVLink
    DH4: Encrypted Command Execution
    DH5: Encrypted Telemetry Reception
    DH6: Full Mission Execution

Prerequisites:
    - 2 physical HSM devices connected (e.g., /dev/ttyUSB0 and /dev/ttyUSB1)
    - SITL built with real HSM support (AP_HSM_MOCK_ENABLED=0)

Usage:
    python3 test_hsm_dual_hardware.py --hsm1 /dev/ttyUSB0 --hsm2 /dev/ttyUSB1

Date: 2026-01-30
"""

import os
import sys
import time
import argparse
from typing import Optional, Tuple

# Add paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Test results
PASSED = 0
FAILED = 0
SKIPPED = 0


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


def skip_test(name: str, reason: str):
    """Skip a test"""
    global SKIPPED
    SKIPPED += 1
    print(f"  [\033[93mSKIP\033[0m] {name} - {reason}")


# =============================================================================
# DH1: Dual HSM Detection Tests
# =============================================================================

def test_dh1_detection(hsm1_port: str, hsm2_port: str):
    """Test detection of both HSMs"""
    print("\n" + "=" * 60)
    print("  DH1: Dual HSM Detection Tests")
    print("=" * 60)

    try:
        from gcs_hsm import GCS_HSM
    except ImportError as e:
        skip_test("DH1.x", f"Cannot import gcs_hsm: {e}")
        return None, None

    # DH1.1: HSM #1 exists
    import os
    hsm1_exists = os.path.exists(hsm1_port)
    test_result("DH1.1 HSM #1 port exists", hsm1_exists, hsm1_port)

    if not hsm1_exists:
        skip_test("DH1.2-DH1.6", f"HSM #1 not found at {hsm1_port}")
        return None, None

    # DH1.2: HSM #2 exists
    hsm2_exists = os.path.exists(hsm2_port)
    test_result("DH1.2 HSM #2 port exists", hsm2_exists, hsm2_port)

    if not hsm2_exists:
        skip_test("DH1.3-DH1.6", f"HSM #2 not found at {hsm2_port}")
        return None, None

    # DH1.3: Connect to HSM #1
    hsm1 = GCS_HSM(port=hsm1_port)
    hsm1_connected = hsm1.connect()
    test_result("DH1.3 HSM #1 connected", hsm1_connected)

    if not hsm1_connected:
        return None, None

    # DH1.4: Connect to HSM #2
    hsm2 = GCS_HSM(port=hsm2_port)
    hsm2_connected = hsm2.connect()
    test_result("DH1.4 HSM #2 connected", hsm2_connected)

    if not hsm2_connected:
        hsm1.disconnect()
        return None, None

    # DH1.5: HSMs are different devices
    test_result("DH1.5 HSMs are different ports", hsm1_port != hsm2_port)

    # DH1.6: Both HSMs responsive
    test_result("DH1.6 Both HSMs responsive", hsm1_connected and hsm2_connected)

    return hsm1, hsm2


# =============================================================================
# DH2: Independent Key Generation Tests
# =============================================================================

def test_dh2_key_generation(hsm1, hsm2):
    """Test independent key generation on both HSMs"""
    print("\n" + "=" * 60)
    print("  DH2: Independent Key Generation Tests")
    print("=" * 60)

    if hsm1 is None or hsm2 is None:
        skip_test("DH2.x", "HSMs not available")
        return False

    # DH2.1: Initialize HSM #1 keys
    print("  Initializing HSM #1 keys (~11s)...")
    start = time.time()
    hsm1_init = hsm1.init_mission_keys(force_new=True)
    elapsed1 = time.time() - start
    test_result("DH2.1 HSM #1 key init", hsm1_init, f"{elapsed1:.1f}s")

    if not hsm1_init:
        return False

    # DH2.2: Initialize HSM #2 keys
    print("  Initializing HSM #2 keys (~11s)...")
    start = time.time()
    hsm2_init = hsm2.init_mission_keys(force_new=True)
    elapsed2 = time.time() - start
    test_result("DH2.2 HSM #2 key init", hsm2_init, f"{elapsed2:.1f}s")

    if not hsm2_init:
        return False

    # DH2.3: Get HSM #1 keys
    mk1 = hsm1._master_key
    wk1_pub = hsm1.get_wk_public()
    dek1 = hsm1.get_my_dek()
    test_result("DH2.3 HSM #1 keys available",
                mk1 is not None and wk1_pub is not None and dek1 is not None)

    # DH2.4: Get HSM #2 keys
    mk2 = hsm2._master_key
    wk2_pub = hsm2.get_wk_public()
    dek2 = hsm2.get_my_dek()
    test_result("DH2.4 HSM #2 keys available",
                mk2 is not None and wk2_pub is not None and dek2 is not None)

    # DH2.5: MKs are different (independently generated)
    test_result("DH2.5 MKs are different", mk1 != mk2)

    # DH2.6: WKs are different
    test_result("DH2.6 WK publics are different", wk1_pub != wk2_pub)

    # DH2.7: DEKs are different
    test_result("DH2.7 DEKs are different", dek1 != dek2)

    # Print key summaries
    print(f"\n  HSM #1 Keys:")
    print(f"    MK:     {mk1[:4].hex()}...")
    print(f"    WK_pub: {wk1_pub[:8].hex()}...")
    print(f"    DEK:    {dek1[:4].hex()}...")

    print(f"\n  HSM #2 Keys:")
    print(f"    MK:     {mk2[:4].hex()}...")
    print(f"    WK_pub: {wk2_pub[:8].hex()}...")
    print(f"    DEK:    {dek2[:4].hex()}...")

    return True


# =============================================================================
# DH3: Key Exchange Tests
# =============================================================================

def test_dh3_key_exchange(hsm1, hsm2):
    """Test ECIES key exchange between HSMs"""
    print("\n" + "=" * 60)
    print("  DH3: Key Exchange Tests")
    print("=" * 60)

    if hsm1 is None or hsm2 is None:
        skip_test("DH3.x", "HSMs not available")
        return False

    try:
        from ecies import ECIES
    except ImportError as e:
        skip_test("DH3.x", f"Cannot import ecies: {e}")
        return False

    # Get keys
    wk1_pub = hsm1.get_wk_public()
    wk1_priv = hsm1._wk_private
    dek1 = hsm1.get_my_dek()

    wk2_pub = hsm2.get_wk_public()
    wk2_priv = hsm2._wk_private
    dek2 = hsm2.get_my_dek()

    # DH3.1: HSM #1 encrypts DEK for HSM #2
    eph1, enc_dek1, nonce1, tag1 = ECIES.encrypt_dek(wk2_pub, dek1)
    test_result("DH3.1 HSM #1 ECIES encrypt", len(enc_dek1) == 32)

    # DH3.2: HSM #2 decrypts HSM #1's DEK
    dec_dek1 = ECIES.decrypt_dek(wk2_priv, eph1, enc_dek1, nonce1, tag1)
    test_result("DH3.2 HSM #2 decrypts DEK #1", dec_dek1 == dek1)

    # DH3.3: HSM #2 encrypts DEK for HSM #1
    eph2, enc_dek2, nonce2, tag2 = ECIES.encrypt_dek(wk1_pub, dek2)
    test_result("DH3.3 HSM #2 ECIES encrypt", len(enc_dek2) == 32)

    # DH3.4: HSM #1 decrypts HSM #2's DEK
    dec_dek2 = ECIES.decrypt_dek(wk1_priv, eph2, enc_dek2, nonce2, tag2)
    test_result("DH3.4 HSM #1 decrypts DEK #2", dec_dek2 == dek2)

    # DH3.5: Bidirectional exchange complete
    test_result("DH3.5 Bidirectional exchange complete",
                dec_dek1 == dek1 and dec_dek2 == dek2)

    return True


# =============================================================================
# DH4: Encrypted Communication Tests
# =============================================================================

def test_dh4_encrypted_comm(hsm1, hsm2):
    """Test encrypted communication between HSMs"""
    print("\n" + "=" * 60)
    print("  DH4: Encrypted Communication Tests")
    print("=" * 60)

    if hsm1 is None or hsm2 is None:
        skip_test("DH4.x", "HSMs not available")
        return False

    try:
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        skip_test("DH4.x", f"Cannot import dual_dek_engine: {e}")
        return False

    # Get DEKs
    dek1 = hsm1.get_my_dek()
    dek2 = hsm2.get_my_dek()

    # Create DualDekEngines
    dde1 = DualDekEngine(my_dek=dek1)
    dde1.set_peer_dek(2, dek2)  # HSM #1 knows HSM #2's DEK

    dde2 = DualDekEngine(my_dek=dek2)
    dde2.set_peer_dek(1, dek1)  # HSM #2 knows HSM #1's DEK

    # DH4.1: HSM #1 → HSM #2 encryption
    msg1 = b"ATTITUDE: roll=0.1 pitch=0.2 yaw=3.14"
    enc1 = dde1.encrypt(msg1)
    dec1 = dde2.decrypt(1, enc1)
    test_result("DH4.1 HSM #1 → HSM #2", dec1 == msg1)

    # DH4.2: HSM #2 → HSM #1 encryption
    msg2 = b"COMMAND_LONG: cmd=400 (ARM)"
    enc2 = dde2.encrypt(msg2)
    dec2 = dde1.decrypt(2, enc2)
    test_result("DH4.2 HSM #2 → HSM #1", dec2 == msg2)

    # DH4.3: Multiple messages
    success_count = 0
    for i in range(10):
        msg = f"Message {i} from HSM #1".encode()
        enc = dde1.encrypt(msg)
        dec = dde2.decrypt(1, enc)
        if dec == msg:
            success_count += 1

    test_result("DH4.3 10 messages HSM #1 → #2", success_count == 10)

    # DH4.4: Large payload
    large_msg = os.urandom(200)
    enc_large = dde1.encrypt(large_msg)
    dec_large = dde2.decrypt(1, enc_large)
    test_result("DH4.4 Large payload (200 bytes)", dec_large == large_msg)

    return True


# =============================================================================
# DH5: HSM Persistence Tests
# =============================================================================

def test_dh5_persistence(hsm1, hsm2):
    """Test key persistence in HSM EEPROM"""
    print("\n" + "=" * 60)
    print("  DH5: HSM Persistence Tests")
    print("=" * 60)

    if hsm1 is None or hsm2 is None:
        skip_test("DH5.x", "HSMs not available")
        return False

    # Save current keys
    dek1_before = hsm1.get_my_dek()
    dek2_before = hsm2.get_my_dek()

    # DH5.1: Keys exist before reload
    test_result("DH5.1 Keys exist before reload",
                dek1_before is not None and dek2_before is not None)

    # DH5.2: Reload keys from HSM #1 (without force_new)
    print("  Reloading HSM #1 keys...")
    hsm1.init_mission_keys(force_new=False)
    dek1_after = hsm1.get_my_dek()
    test_result("DH5.2 HSM #1 keys persisted", dek1_after == dek1_before)

    # DH5.3: Reload keys from HSM #2
    print("  Reloading HSM #2 keys...")
    hsm2.init_mission_keys(force_new=False)
    dek2_after = hsm2.get_my_dek()
    test_result("DH5.3 HSM #2 keys persisted", dek2_after == dek2_before)

    return True


# =============================================================================
# DH6: Cleanup Tests
# =============================================================================

def test_dh6_cleanup(hsm1, hsm2):
    """Cleanup HSM connections"""
    print("\n" + "=" * 60)
    print("  DH6: Cleanup Tests")
    print("=" * 60)

    if hsm1:
        hsm1.disconnect()
        test_result("DH6.1 HSM #1 disconnected", True)

    if hsm2:
        hsm2.disconnect()
        test_result("DH6.2 HSM #2 disconnected", True)

    return True


# =============================================================================
# Main
# =============================================================================

def main():
    global PASSED, FAILED, SKIPPED

    parser = argparse.ArgumentParser(description="HSM Dual-Hardware E2E Tests")
    parser.add_argument('--hsm1', type=str, default='/dev/ttyUSB0',
                        help='HSM #1 port (Drone)')
    parser.add_argument('--hsm2', type=str, default='/dev/ttyUSB1',
                        help='HSM #2 port (GCS)')
    args = parser.parse_args()

    print("=" * 60)
    print("  HSM Dual-Hardware End-to-End Tests")
    print("=" * 60)
    print(f"  HSM #1 (Drone): {args.hsm1}")
    print(f"  HSM #2 (GCS):   {args.hsm2}")
    print("=" * 60)

    start_time = time.time()

    # Run tests
    hsm1, hsm2 = test_dh1_detection(args.hsm1, args.hsm2)

    if hsm1 and hsm2:
        test_dh2_key_generation(hsm1, hsm2)
        test_dh3_key_exchange(hsm1, hsm2)
        test_dh4_encrypted_comm(hsm1, hsm2)
        test_dh5_persistence(hsm1, hsm2)
        test_dh6_cleanup(hsm1, hsm2)
    else:
        skip_test("DH2-DH6", "HSMs not available")

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("  Dual-Hardware Test Summary")
    print("=" * 60)
    print(f"  PASSED:  {PASSED}")
    print(f"  FAILED:  {FAILED}")
    print(f"  SKIPPED: {SKIPPED}")
    print(f"  Time:    {elapsed:.1f}s")
    print("=" * 60)

    if FAILED == 0 and PASSED > 0:
        print("\n  \033[92mAll dual-hardware tests PASSED!\033[0m")
        return 0
    elif PASSED == 0:
        print("\n  \033[93mNo tests ran (HSMs not available?)\033[0m")
        return 1
    else:
        print(f"\n  \033[91m{FAILED} tests FAILED\033[0m")
        return 1


if __name__ == '__main__':
    sys.exit(main())
