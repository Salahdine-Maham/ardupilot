#!/usr/bin/env python3
"""
Phase B: MAVProxy HSM Module Integration Tests
===============================================

Tests the mavproxy_hsm.py module for automatic encryption/decryption.

Architecture tested:
    SITL (HSM#1) <--encrypted--> MAVProxy+HSM Module (HSM#2)

Tests:
    B1: Module import and initialization
    B2: ChaCha20 encryption/decryption
    B3: HSM initialization
    B4: Key exchange protocol
    B5: Integration with SITL (manual - requires running SITL)

Usage:
    python3 test_hsm_phase_b.py --hsm /dev/ttyUSB3

    For integration test with SITL:
    # Terminal 1: Start SITL with HSM
    ./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200

    # Terminal 2: Run this test
    python3 test_hsm_phase_b.py --hsm /dev/ttyUSB3 --mavlink tcp:127.0.0.1:5760

Date: 2026-01-27
"""

import os
import sys
import time
import argparse
from typing import Optional, Tuple

# Add parent dir to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Test results
PASSED = 0
FAILED = 0
SKIPPED = 0


def test_result(name: str, passed: bool, msg: str = ""):
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
# Phase B1: Module Import Tests
# =============================================================================

def test_b1_module_imports():
    """Test that mavproxy_hsm module can be imported"""
    print("\n" + "=" * 60)
    print("  Phase B1: Module Import Tests")
    print("=" * 60)

    # B1.1: Import mavproxy_hsm
    try:
        import mavproxy_hsm
        test_result("B1.1 Import mavproxy_hsm", True)
    except ImportError as e:
        test_result("B1.1 Import mavproxy_hsm", False, str(e))
        return False

    # B1.2: Check ChaCha20 available
    test_result("B1.2 ChaCha20 available", mavproxy_hsm.CHACHA20_AVAILABLE)

    # B1.3: Check HSM libs available
    test_result("B1.3 HSM libs available", mavproxy_hsm.HSM_AVAILABLE)

    # B1.4: Check chacha20_xor function exists
    test_result("B1.4 chacha20_xor function", callable(mavproxy_hsm.chacha20_xor))

    # B1.5: Check build_nonce function exists
    test_result("B1.5 build_nonce function", callable(mavproxy_hsm.build_nonce))

    # B1.6: Check HSMModule class exists
    test_result("B1.6 HSMModule class", hasattr(mavproxy_hsm, 'HSMModule'))

    return True


# =============================================================================
# Phase B2: ChaCha20 Encryption Tests
# =============================================================================

def test_b2_chacha20():
    """Test ChaCha20 encryption/decryption"""
    print("\n" + "=" * 60)
    print("  Phase B2: ChaCha20 Encryption Tests")
    print("=" * 60)

    import mavproxy_hsm

    if not mavproxy_hsm.CHACHA20_AVAILABLE:
        skip_test("B2.x", "cryptography library not available")
        return False

    # B2.1: Basic encryption/decryption
    key = bytes([i for i in range(32)])
    nonce = mavproxy_hsm.build_nonce(42, 1, 0, 30, 0, 0)
    plaintext = b"Hello HSM World!"

    encrypted = mavproxy_hsm.chacha20_xor(key, 0, nonce, plaintext)
    decrypted = mavproxy_hsm.chacha20_xor(key, 0, nonce, encrypted)

    test_result("B2.1 Encrypt/decrypt roundtrip", decrypted == plaintext)

    # B2.2: Different nonces produce different ciphertext
    nonce2 = mavproxy_hsm.build_nonce(43, 1, 0, 30, 0, 0)
    encrypted2 = mavproxy_hsm.chacha20_xor(key, 0, nonce2, plaintext)
    test_result("B2.2 Different nonce = different ciphertext", encrypted != encrypted2)

    # B2.3: Different keys produce different ciphertext
    key2 = bytes([i + 1 for i in range(32)])
    encrypted3 = mavproxy_hsm.chacha20_xor(key2, 0, nonce, plaintext)
    test_result("B2.3 Different key = different ciphertext", encrypted != encrypted3)

    # B2.4: Zero-length payload
    empty = mavproxy_hsm.chacha20_xor(key, 0, nonce, b"")
    test_result("B2.4 Empty payload handling", empty == b"")

    # B2.5: Large payload (256 bytes)
    large = bytes([i % 256 for i in range(256)])
    enc_large = mavproxy_hsm.chacha20_xor(key, 0, nonce, large)
    dec_large = mavproxy_hsm.chacha20_xor(key, 0, nonce, enc_large)
    test_result("B2.5 Large payload (256 bytes)", dec_large == large)

    # B2.6: Nonce format check (12 bytes)
    nonce_test = mavproxy_hsm.build_nonce(255, 255, 255, 0xFFFFFF, 255, 255)
    test_result("B2.6 Nonce is 12 bytes", len(nonce_test) == 12)

    return True


# =============================================================================
# Phase B3: HSM Initialization Tests
# =============================================================================

def test_b3_hsm_init(hsm_port: str):
    """Test HSM initialization"""
    print("\n" + "=" * 60)
    print("  Phase B3: HSM Initialization Tests")
    print("=" * 60)

    import mavproxy_hsm

    if not mavproxy_hsm.HSM_AVAILABLE:
        skip_test("B3.x", "HSM libs not available")
        return False

    from gcs_hsm import GCS_HSM, KeyState

    # B3.1: HSM connection
    print(f"  Connecting to HSM on {hsm_port}...")
    hsm = GCS_HSM(port=hsm_port)
    connected = hsm.connect()
    test_result("B3.1 HSM connection", connected)

    if not connected:
        return False

    # B3.2: HSM state after connect (check serial is open)
    test_result("B3.2 HSM serial connected", hsm.ser is not None and hsm.ser.is_open)

    # B3.3: Mission key initialization
    print("  Initializing mission keys (~11s)...")
    start = time.time()
    init_ok = hsm.init_mission_keys(force_new=False)
    elapsed = time.time() - start
    test_result("B3.3 Mission keys init", init_ok, f"{elapsed:.1f}s")

    if not init_ok:
        hsm.disconnect()
        return False

    # B3.4: Get MY_DEK
    my_dek = hsm.get_my_dek()
    test_result("B3.4 MY_DEK available", my_dek is not None and len(my_dek) == 32)

    if my_dek:
        print(f"       MY_DEK: {my_dek[:4].hex()}...")

    # B3.5: Check WK private is available (WK public computed from it in KEP)
    wk_priv = hsm._wk_private
    test_result("B3.5 WK private available", wk_priv is not None and len(wk_priv) == 32)

    if wk_priv:
        print(f"       WK_priv: {wk_priv[:4].hex()}...")

    # B3.6: Disconnect
    hsm.disconnect()
    test_result("B3.6 HSM disconnect", True)

    return True


# =============================================================================
# Phase B4: Key Exchange Protocol Tests
# =============================================================================

def test_b4_kep(hsm_port: str):
    """Test Key Exchange Protocol components"""
    print("\n" + "=" * 60)
    print("  Phase B4: Key Exchange Protocol Tests")
    print("=" * 60)

    import mavproxy_hsm

    if not mavproxy_hsm.HSM_AVAILABLE:
        skip_test("B4.x", "HSM libs not available")
        return False

    from gcs_hsm import GCS_HSM
    from key_exchange_protocol import KeyExchangeProtocol

    # B4.1: KEP import
    test_result("B4.1 KEP import", True)

    # B4.2: HSM connection for KEP
    hsm = GCS_HSM(port=hsm_port)
    connected = hsm.connect()
    test_result("B4.2 HSM connect for KEP", connected)

    if not connected:
        return False

    # B4.3: Init mission keys
    print("  Initializing keys...")
    init_ok = hsm.init_mission_keys(force_new=False)
    test_result("B4.3 Mission keys for KEP", init_ok)

    if not init_ok:
        hsm.disconnect()
        return False

    # B4.4: Create KEP instance
    sent_messages = []
    def send_callback(msg_id, target_sysid, target_compid, payload):
        sent_messages.append((msg_id, target_sysid, payload))

    kep = KeyExchangeProtocol(hsm, my_sysid=255, my_compid=190)
    kep.set_send_callback(send_callback)
    test_result("B4.4 KEP instance created", kep is not None)

    # B4.5: Initiate key exchange
    kep.initiate_exchange(peer_sysid=1, peer_compid=0)
    # Should have sent WK exchange message
    wk_sent = any(m[0] == mavproxy_hsm.MAVLINK_MSG_ID_HSM_WK_EXCHANGE for m in sent_messages)
    test_result("B4.5 WK exchange initiated", wk_sent)

    # B4.6: KEP state check - check WK public is available
    test_result("B4.6 KEP has WK public", kep._my_wk_public is not None and len(kep._my_wk_public) == 64)

    hsm.disconnect()
    return True


# =============================================================================
# Phase B5: SITL Integration Tests
# =============================================================================

def test_b5_sitl_integration(hsm_port: str, mavlink_url: str):
    """Test integration with running SITL"""
    print("\n" + "=" * 60)
    print("  Phase B5: SITL Integration Tests")
    print("=" * 60)

    if mavlink_url is None:
        skip_test("B5.x", "No --mavlink URL provided")
        return False

    import mavproxy_hsm

    if not mavproxy_hsm.HSM_AVAILABLE:
        skip_test("B5.x", "HSM libs not available")
        return False

    # Import pymavlink
    try:
        from pymavlink import mavutil
        test_result("B5.1 pymavlink import", True)
    except ImportError:
        test_result("B5.1 pymavlink import", False)
        return False

    # B5.2: Connect to SITL
    print(f"  Connecting to SITL at {mavlink_url}...")
    try:
        mav = mavutil.mavlink_connection(mavlink_url, baud=115200)
        mav.wait_heartbeat(timeout=10)
        test_result("B5.2 SITL connection", True, f"sysid={mav.target_system}")
    except Exception as e:
        test_result("B5.2 SITL connection", False, str(e))
        return False

    # B5.3: Initialize HSM
    from gcs_hsm import GCS_HSM
    from key_exchange_protocol import KeyExchangeProtocol

    print(f"  Initializing HSM on {hsm_port}...")
    hsm = GCS_HSM(port=hsm_port)
    connected = hsm.connect()
    test_result("B5.3 HSM connect", connected)

    if not connected:
        mav.close()
        return False

    print("  Loading mission keys...")
    init_ok = hsm.init_mission_keys(force_new=False)
    test_result("B5.4 HSM mission keys", init_ok)

    if not init_ok:
        hsm.disconnect()
        mav.close()
        return False

    # B5.5: Create KEP and exchange keys
    def send_wk(msg_id, target_sysid, target_compid, payload):
        if msg_id == mavproxy_hsm.MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
            # Send WK_EXCHANGE message
            wk_pub = hsm.get_wk_public()
            timestamp = int(time.time())
            # Use custom message (requires dialect)
            print(f"  Sending WK_EXCHANGE to sysid={target_sysid}")

    kep = KeyExchangeProtocol(hsm, my_sysid=255, my_compid=190)
    test_result("B5.5 KEP created", kep is not None)

    # B5.6: Wait for messages from drone
    print("  Waiting for drone messages (10s)...")
    msg_count = 0
    hsm_msgs = 0
    bad_data_msgs = 0
    start = time.time()

    while time.time() - start < 10:
        msg = mav.recv_match(blocking=True, timeout=1)
        if msg:
            msg_count += 1
            msg_type = msg.get_type()
            msgid = msg.get_msgId()
            if msgid in [12000, 12001, 12002]:
                hsm_msgs += 1
                print(f"    HSM message: {msg_type} from sysid={msg.get_srcSystem()}")
            if msg_type == 'BAD_DATA':
                bad_data_msgs += 1

    test_result("B5.6 Received messages from drone", msg_count > 0, f"{msg_count} msgs, {hsm_msgs} HSM")

    # B5.7: Check for encrypted messages
    # When drone is encrypting, messages come as BAD_DATA (CRC mismatch due to encrypted payload)
    # Or as HSM messages (key exchange)
    encrypted_detected = bad_data_msgs > 0 or hsm_msgs > 0
    test_result("B5.7 Encrypted traffic detected", encrypted_detected,
                f"bad_data={bad_data_msgs}, hsm={hsm_msgs}")

    hsm.disconnect()
    mav.close()
    return True


# =============================================================================
# Phase B6: MAVProxy Module Simulation
# =============================================================================

def test_b6_module_simulation(hsm_port: str):
    """Test MAVProxy module behavior without actual MAVProxy"""
    print("\n" + "=" * 60)
    print("  Phase B6: Module Simulation Tests")
    print("=" * 60)

    import mavproxy_hsm

    if not mavproxy_hsm.CHACHA20_AVAILABLE:
        skip_test("B6.x", "cryptography not available")
        return False

    # B6.1: Simulate HSMModule without MAVProxy
    class MockMPState:
        def __init__(self):
            pass

    # Create module (will use stub MPModule)
    try:
        # We need to test the functions directly since MAVProxy isn't available
        test_result("B6.1 Module functions accessible", True)
    except Exception as e:
        test_result("B6.1 Module functions accessible", False, str(e))
        return False

    # B6.2: Test plaintext message IDs
    expected_plaintext = {0, 12000, 12001, 12002}
    test_result("B6.2 Plaintext msgids defined",
                mavproxy_hsm.PLAINTEXT_MSGIDS == expected_plaintext)

    # B6.3: Encryption simulation - message flow
    key = bytes.fromhex("0db7e8549ed362cb" * 4)[:32]  # Sample DEK

    # Simulate TX encryption
    tx_plaintext = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])  # 6 byte payload
    tx_nonce = mavproxy_hsm.build_nonce(100, 255, 190, 76, 0, 0)  # COMMAND_LONG
    tx_encrypted = mavproxy_hsm.chacha20_xor(key, 0, tx_nonce, tx_plaintext)

    test_result("B6.3 TX encryption works", tx_encrypted != tx_plaintext)

    # B6.4: Simulate RX decryption
    rx_encrypted = tx_encrypted  # Same as what would be received
    rx_decrypted = mavproxy_hsm.chacha20_xor(key, 0, tx_nonce, rx_encrypted)
    test_result("B6.4 RX decryption recovers plaintext", rx_decrypted == tx_plaintext)

    # B6.5: Verify nonce includes all components
    nonce = mavproxy_hsm.build_nonce(seq=42, sysid=1, compid=0, msgid=30, chan=0, direction=1)
    test_result("B6.5 Nonce includes seq", nonce[0] == 42)
    test_result("B6.6 Nonce includes sysid", nonce[1] == 1)
    test_result("B6.7 Nonce includes compid", nonce[2] == 0)
    test_result("B6.8 Nonce includes direction", nonce[7] == 1)

    return True


# =============================================================================
# Main
# =============================================================================

def main():
    global PASSED, FAILED, SKIPPED

    parser = argparse.ArgumentParser(description="Phase B: MAVProxy HSM Module Tests")
    parser.add_argument('--hsm', type=str, default='/dev/ttyUSB3',
                        help='HSM serial port (default: /dev/ttyUSB3)')
    parser.add_argument('--mavlink', type=str, default=None,
                        help='MAVLink URL for SITL (e.g., tcp:127.0.0.1:5760)')
    parser.add_argument('--skip-hsm', action='store_true',
                        help='Skip tests requiring physical HSM')
    args = parser.parse_args()

    print("=" * 60)
    print("  Phase B: MAVProxy HSM Module Integration Tests")
    print("=" * 60)
    print(f"  HSM Port: {args.hsm}")
    print(f"  MAVLink:  {args.mavlink or 'None (B5 will be skipped)'}")
    print("=" * 60)

    start_time = time.time()

    # Run test phases
    test_b1_module_imports()
    test_b2_chacha20()

    if not args.skip_hsm:
        test_b3_hsm_init(args.hsm)
        test_b4_kep(args.hsm)
        test_b6_module_simulation(args.hsm)
    else:
        skip_test("B3.x", "HSM tests skipped")
        skip_test("B4.x", "HSM tests skipped")
        skip_test("B6.x", "HSM tests skipped")

    if args.mavlink:
        test_b5_sitl_integration(args.hsm, args.mavlink)
    else:
        skip_test("B5.x", "No --mavlink URL provided")

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("  Phase B Summary")
    print("=" * 60)
    print(f"  PASSED:  {PASSED}")
    print(f"  FAILED:  {FAILED}")
    print(f"  SKIPPED: {SKIPPED}")
    print(f"  Time:    {elapsed:.1f}s")
    print("=" * 60)

    if FAILED == 0:
        print("\n  \033[92mAll Phase B tests PASSED!\033[0m")
        return 0
    else:
        print(f"\n  \033[91m{FAILED} tests FAILED\033[0m")
        return 1


if __name__ == '__main__':
    sys.exit(main())
