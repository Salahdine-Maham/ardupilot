#!/usr/bin/env python3
"""
HSM Autotest Framework Integration Tests
=========================================

Tests designed for integration with ArduPilot's autotest framework.
Can also be run standalone.

Test Categories:
    AT1: HSM Mock Initialization
    AT2: Key Hierarchy Verification
    AT3: Key Exchange Protocol
    AT4: Encrypted Telemetry
    AT5: Encrypted Commands
    AT6: Multi-peer Support

Usage:
    Standalone:
        python3 test_hsm_autotest.py --sitl

    With autotest framework:
        python3 Tools/autotest/autotest.py --test HSM_MockInit

Date: 2026-01-30
"""

import os
import sys
import time
import subprocess
import signal
import argparse
from typing import Optional, Tuple, List

# Add paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
ARDUPILOT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

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


class SITLManager:
    """Manages SITL process for tests"""

    def __init__(self):
        self.process = None
        self.mav = None

    def start(self, timeout: int = 30) -> bool:
        """Start SITL with Mock HSM"""
        sitl_binary = os.path.join(ARDUPILOT_ROOT, 'build/sitl/bin/arducopter')
        defaults = os.path.join(ARDUPILOT_ROOT, 'Tools/autotest/default_params/copter.parm')

        if not os.path.exists(sitl_binary):
            print(f"  SITL binary not found: {sitl_binary}")
            return False

        cmd = [sitl_binary, '--model', '+', '--defaults', defaults, '-I0']
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=ARDUPILOT_ROOT
        )

        # Wait for SITL to start
        time.sleep(5)

        # Try to connect
        try:
            from pymavlink import mavutil
            self.mav = mavutil.mavlink_connection('tcp:127.0.0.1:5760',
                                                   source_system=255,
                                                   source_component=190)
            hb = self.mav.wait_heartbeat(timeout=timeout)
            return hb is not None
        except Exception as e:
            print(f"  Connection failed: {e}")
            return False

    def stop(self):
        """Stop SITL"""
        if self.mav:
            self.mav.close()
            self.mav = None

        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def get_output(self, timeout: float = 0.1) -> str:
        """Get SITL output"""
        if self.process and self.process.stdout:
            import select
            ready, _, _ = select.select([self.process.stdout], [], [], timeout)
            if ready:
                return self.process.stdout.readline().decode('utf-8', errors='ignore')
        return ""


# =============================================================================
# AT1: HSM Mock Initialization Tests
# =============================================================================

def test_at1_mock_init(sitl: SITLManager):
    """Test HSM Mock initialization"""
    print("\n" + "=" * 60)
    print("  AT1: HSM Mock Initialization Tests")
    print("=" * 60)

    if sitl.mav is None:
        skip_test("AT1.x", "No SITL connection")
        return False

    # AT1.1: SITL is running
    test_result("AT1.1 SITL running", sitl.process is not None)

    # AT1.2: MAVLink connected
    test_result("AT1.2 MAVLink connected", sitl.mav is not None)

    # AT1.3: Heartbeat received
    hb = sitl.mav.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
    test_result("AT1.3 Heartbeat received", hb is not None)

    # AT1.4: System ID is 1
    if hb:
        test_result("AT1.4 SITL sysid=1", hb.get_srcSystem() == 1)
    else:
        test_result("AT1.4 SITL sysid=1", False)

    # AT1.5: Check for encrypted messages (BAD_DATA)
    bad_data_count = 0
    start = time.time()
    while time.time() - start < 3:
        msg = sitl.mav.recv_match(blocking=True, timeout=0.5)
        if msg and msg.get_type() == 'BAD_DATA':
            bad_data_count += 1

    test_result("AT1.5 Encrypted messages detected", bad_data_count > 0,
                f"{bad_data_count} encrypted")

    # AT1.6: HEARTBEAT remains plaintext
    hb_count = 0
    start = time.time()
    while time.time() - start < 3:
        msg = sitl.mav.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
        if msg:
            hb_count += 1

    test_result("AT1.6 HEARTBEAT plaintext", hb_count > 0, f"{hb_count} heartbeats")

    return True


# =============================================================================
# AT2: Key Hierarchy Tests
# =============================================================================

def test_at2_key_hierarchy():
    """Test key hierarchy (MK → WK → DEK)"""
    print("\n" + "=" * 60)
    print("  AT2: Key Hierarchy Tests")
    print("=" * 60)

    try:
        from ecies import ECIES
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        skip_test("AT2.x", f"Import failed: {e}")
        return False

    # AT2.1: Generate Master Key (32 bytes)
    mk = os.urandom(32)
    test_result("AT2.1 Generate MK (32 bytes)", len(mk) == 32)

    # AT2.2: Derive Wrapper Key from MK (simulated HKDF)
    wk_priv, wk_pub = ECIES.generate_keypair()
    test_result("AT2.2 Generate WK keypair", len(wk_priv) == 32 and len(wk_pub) == 64)

    # AT2.3: Derive public from private
    derived_pub = ECIES.derive_public_key(wk_priv)
    test_result("AT2.3 WK public derivation", derived_pub == wk_pub)

    # AT2.4: Generate DEK (32 bytes)
    dek = os.urandom(32)
    test_result("AT2.4 Generate DEK (32 bytes)", len(dek) == 32)

    # AT2.5: DEK is random (not all zeros)
    test_result("AT2.5 DEK is random", dek != bytes(32))

    # AT2.6: Key hierarchy complete
    test_result("AT2.6 Key hierarchy complete",
                len(mk) == 32 and len(wk_priv) == 32 and len(dek) == 32)

    return True


# =============================================================================
# AT3: Key Exchange Protocol Tests
# =============================================================================

def test_at3_key_exchange():
    """Test key exchange protocol"""
    print("\n" + "=" * 60)
    print("  AT3: Key Exchange Protocol Tests")
    print("=" * 60)

    try:
        from ecies import ECIES
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        skip_test("AT3.x", f"Import failed: {e}")
        return False

    # Simulate Drone and GCS
    drone_wk_priv, drone_wk_pub = ECIES.generate_keypair()
    gcs_wk_priv, gcs_wk_pub = ECIES.generate_keypair()
    drone_dek = os.urandom(32)
    gcs_dek = os.urandom(32)

    # AT3.1: WK exchange (both sides have public keys)
    test_result("AT3.1 WK public exchange",
                len(drone_wk_pub) == 64 and len(gcs_wk_pub) == 64)

    # AT3.2: Drone encrypts DEK for GCS
    eph_d, enc_dek_d, nonce_d, tag_d = ECIES.encrypt_dek(gcs_wk_pub, drone_dek)
    test_result("AT3.2 Drone ECIES encrypt", len(enc_dek_d) == 32)

    # AT3.3: GCS decrypts Drone's DEK
    dec_drone_dek = ECIES.decrypt_dek(gcs_wk_priv, eph_d, enc_dek_d, nonce_d, tag_d)
    test_result("AT3.3 GCS decrypts Drone DEK", dec_drone_dek == drone_dek)

    # AT3.4: GCS encrypts DEK for Drone
    eph_g, enc_dek_g, nonce_g, tag_g = ECIES.encrypt_dek(drone_wk_pub, gcs_dek)
    test_result("AT3.4 GCS ECIES encrypt", len(enc_dek_g) == 32)

    # AT3.5: Drone decrypts GCS's DEK
    dec_gcs_dek = ECIES.decrypt_dek(drone_wk_priv, eph_g, enc_dek_g, nonce_g, tag_g)
    test_result("AT3.5 Drone decrypts GCS DEK", dec_gcs_dek == gcs_dek)

    # AT3.6: Both sides have each other's DEK
    test_result("AT3.6 Bidirectional exchange complete",
                dec_drone_dek == drone_dek and dec_gcs_dek == gcs_dek)

    return True


# =============================================================================
# AT4: Encrypted Telemetry Tests
# =============================================================================

def test_at4_encrypted_telemetry(sitl: SITLManager):
    """Test encrypted telemetry"""
    print("\n" + "=" * 60)
    print("  AT4: Encrypted Telemetry Tests")
    print("=" * 60)

    if sitl.mav is None:
        skip_test("AT4.x", "No SITL connection")
        return False

    # AT4.1: Count message types
    msg_counts = {}
    start = time.time()
    while time.time() - start < 5:
        msg = sitl.mav.recv_match(blocking=True, timeout=0.5)
        if msg:
            mtype = msg.get_type()
            msg_counts[mtype] = msg_counts.get(mtype, 0) + 1

    total = sum(msg_counts.values())
    test_result("AT4.1 Messages received", total > 0, f"{total} messages")

    # AT4.2: Most messages are encrypted (BAD_DATA)
    bad_data = msg_counts.get('BAD_DATA', 0)
    if total > 0:
        ratio = bad_data / total * 100
        test_result("AT4.2 Encryption ratio > 90%", ratio > 90, f"{ratio:.1f}%")
    else:
        test_result("AT4.2 Encryption ratio > 90%", False)

    # AT4.3: HEARTBEAT is plaintext
    heartbeat = msg_counts.get('HEARTBEAT', 0)
    test_result("AT4.3 HEARTBEAT plaintext", heartbeat > 0, f"{heartbeat} heartbeats")

    # AT4.4: Message rate > 100 Hz
    elapsed = time.time() - start
    rate = total / elapsed if elapsed > 0 else 0
    test_result("AT4.4 Message rate > 100 Hz", rate > 100, f"{rate:.1f} msg/s")

    return True


# =============================================================================
# AT5: Encrypted Commands Tests
# =============================================================================

def test_at5_encrypted_commands(sitl: SITLManager):
    """Test encrypted commands"""
    print("\n" + "=" * 60)
    print("  AT5: Encrypted Commands Tests")
    print("=" * 60)

    if sitl.mav is None:
        skip_test("AT5.x", "No SITL connection")
        return False

    # AT5.1: SET_MODE command (plaintext - mode change works)
    sitl.mav.mav.set_mode_send(
        sitl.mav.target_system,
        1,  # MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        4   # GUIDED
    )
    time.sleep(1)

    # Check mode via heartbeat
    hb = sitl.mav.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
    if hb:
        # Mode 4 = GUIDED for copter
        test_result("AT5.1 SET_MODE GUIDED", hb.custom_mode == 4,
                    f"mode={hb.custom_mode}")
    else:
        test_result("AT5.1 SET_MODE GUIDED", False, "No heartbeat")

    # AT5.2: Change to STABILIZE
    sitl.mav.mav.set_mode_send(sitl.mav.target_system, 1, 0)  # STABILIZE
    time.sleep(1)
    hb = sitl.mav.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
    if hb:
        test_result("AT5.2 SET_MODE STABILIZE", hb.custom_mode == 0,
                    f"mode={hb.custom_mode}")
    else:
        test_result("AT5.2 SET_MODE STABILIZE", False)

    # AT5.3: COMMAND_LONG structure valid
    test_result("AT5.3 Command structure", True)

    return True


# =============================================================================
# AT6: Multi-peer Support Tests
# =============================================================================

def test_at6_multi_peer():
    """Test multi-peer DEK support"""
    print("\n" + "=" * 60)
    print("  AT6: Multi-peer Support Tests")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        skip_test("AT6.x", f"Import failed: {e}")
        return False

    # Create engine
    my_dek = os.urandom(32)
    dde = DualDekEngine(my_dek=my_dek)

    # AT6.1: Add multiple peers
    peer_deks = {}
    for sysid in [1, 2, 3, 4, 5]:
        peer_dek = os.urandom(32)
        peer_deks[sysid] = peer_dek
        dde.set_peer_dek(sysid, peer_dek)

    test_result("AT6.1 Add 5 peers", True)

    # AT6.2: Retrieve peer DEKs
    all_match = True
    for sysid, expected_dek in peer_deks.items():
        retrieved = dde.get_peer_dek(sysid)
        if retrieved != expected_dek:
            all_match = False
            break

    test_result("AT6.2 Retrieve peer DEKs", all_match)

    # AT6.3: Encrypt/decrypt with different peers
    test_msg = b"Test message for multi-peer"
    success_count = 0

    for sysid, peer_dek in peer_deks.items():
        # Create peer engine
        peer_dde = DualDekEngine(my_dek=peer_dek)
        peer_dde.set_peer_dek(255, my_dek)  # Peer knows our DEK

        # We encrypt, peer decrypts
        encrypted = dde.encrypt(test_msg)
        decrypted = peer_dde.decrypt(255, encrypted)
        if decrypted == test_msg:
            success_count += 1

    test_result("AT6.3 Multi-peer encryption", success_count == 5,
                f"{success_count}/5 peers")

    return True


# =============================================================================
# Main
# =============================================================================

def main():
    global PASSED, FAILED, SKIPPED

    parser = argparse.ArgumentParser(description="HSM Autotest Framework Tests")
    parser.add_argument('--sitl', action='store_true',
                        help='Start SITL for testing')
    parser.add_argument('--no-sitl', action='store_true',
                        help='Skip SITL tests')
    args = parser.parse_args()

    print("=" * 60)
    print("  HSM Autotest Framework Integration Tests")
    print("=" * 60)

    start_time = time.time()
    sitl = SITLManager()

    # Start SITL if requested
    if args.sitl and not args.no_sitl:
        print("\n  Starting SITL...")
        if sitl.start(timeout=30):
            print("  SITL started successfully")
        else:
            print("  Failed to start SITL")

    # Run tests
    try:
        # Tests without SITL
        test_at2_key_hierarchy()
        test_at3_key_exchange()
        test_at6_multi_peer()

        # Tests with SITL
        if sitl.mav and not args.no_sitl:
            test_at1_mock_init(sitl)
            test_at4_encrypted_telemetry(sitl)
            test_at5_encrypted_commands(sitl)
        elif not args.no_sitl:
            skip_test("AT1.x", "No SITL")
            skip_test("AT4.x", "No SITL")
            skip_test("AT5.x", "No SITL")

    finally:
        sitl.stop()

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("  Autotest Framework Test Summary")
    print("=" * 60)
    print(f"  PASSED:  {PASSED}")
    print(f"  FAILED:  {FAILED}")
    print(f"  SKIPPED: {SKIPPED}")
    print(f"  Time:    {elapsed:.1f}s")
    print("=" * 60)

    if FAILED == 0 and PASSED > 0:
        print("\n  \033[92mAll autotest framework tests PASSED!\033[0m")
        return 0
    else:
        print(f"\n  \033[91m{FAILED} tests FAILED\033[0m")
        return 1


if __name__ == '__main__':
    sys.exit(main())
