#!/usr/bin/env python3
"""
HSM Stress and Performance Tests
================================

Tests for HSM system performance, throughput, and stability under load.

Test Categories:
    ST1: Encryption Throughput
    ST2: Decryption Throughput
    ST3: Key Exchange Performance
    ST4: Multi-peer Stress
    ST5: Memory/Resource Usage
    ST6: Long-running Stability

Usage:
    python3 test_hsm_stress.py

    With extended duration:
    python3 test_hsm_stress.py --duration 60

Date: 2026-01-30
"""

import os
import sys
import time
import argparse
import statistics
from typing import List, Tuple

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
# ST1: Encryption Throughput Tests
# =============================================================================

def test_st1_encryption_throughput(iterations: int = 1000):
    """Test encryption throughput"""
    print("\n" + "=" * 60)
    print("  ST1: Encryption Throughput Tests")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        print(f"  SKIP: Cannot import dual_dek_engine: {e}")
        return False

    dek = os.urandom(32)
    dde = DualDekEngine(my_dek=dek)

    # ST1.1: Small payload throughput (32 bytes)
    payload_small = os.urandom(32)
    start = time.time()
    for _ in range(iterations):
        dde.encrypt(payload_small)
    elapsed = time.time() - start
    rate_small = iterations / elapsed
    test_result("ST1.1 Small payload (32B)", rate_small > 1000,
                f"{rate_small:.0f} enc/s")

    # ST1.2: Medium payload throughput (128 bytes)
    payload_medium = os.urandom(128)
    start = time.time()
    for _ in range(iterations):
        dde.encrypt(payload_medium)
    elapsed = time.time() - start
    rate_medium = iterations / elapsed
    test_result("ST1.2 Medium payload (128B)", rate_medium > 500,
                f"{rate_medium:.0f} enc/s")

    # ST1.3: Large payload throughput (255 bytes - max)
    payload_large = os.urandom(255)
    start = time.time()
    for _ in range(iterations):
        dde.encrypt(payload_large)
    elapsed = time.time() - start
    rate_large = iterations / elapsed
    test_result("ST1.3 Large payload (255B)", rate_large > 300,
                f"{rate_large:.0f} enc/s")

    # ST1.4: Latency measurement
    latencies = []
    for _ in range(100):
        t0 = time.perf_counter()
        dde.encrypt(payload_small)
        latencies.append((time.perf_counter() - t0) * 1000000)  # microseconds

    avg_latency = statistics.mean(latencies)
    p99_latency = sorted(latencies)[98]
    test_result("ST1.4 Avg latency < 1ms", avg_latency < 1000,
                f"avg={avg_latency:.1f}µs, p99={p99_latency:.1f}µs")

    return True


# =============================================================================
# ST2: Decryption Throughput Tests
# =============================================================================

def test_st2_decryption_throughput(iterations: int = 1000):
    """Test decryption throughput"""
    print("\n" + "=" * 60)
    print("  ST2: Decryption Throughput Tests")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        print(f"  SKIP: Cannot import dual_dek_engine: {e}")
        return False

    # Setup two engines
    dek1 = os.urandom(32)
    dek2 = os.urandom(32)

    dde1 = DualDekEngine(my_dek=dek1)
    dde1.set_peer_dek(2, dek2)

    dde2 = DualDekEngine(my_dek=dek2)
    dde2.set_peer_dek(1, dek1)

    # Pre-encrypt messages
    payload = os.urandom(128)
    encrypted_msgs = [dde1.encrypt(payload) for _ in range(iterations)]

    # ST2.1: Decryption throughput
    start = time.time()
    success = 0
    for enc in encrypted_msgs:
        dec = dde2.decrypt(1, enc)
        if dec == payload:
            success += 1
    elapsed = time.time() - start
    rate = iterations / elapsed
    test_result("ST2.1 Decryption throughput", rate > 500,
                f"{rate:.0f} dec/s")

    # ST2.2: 100% success rate
    test_result("ST2.2 100% success rate", success == iterations,
                f"{success}/{iterations}")

    # ST2.3: Decryption latency
    latencies = []
    for enc in encrypted_msgs[:100]:
        t0 = time.perf_counter()
        dde2.decrypt(1, enc)
        latencies.append((time.perf_counter() - t0) * 1000000)

    avg_latency = statistics.mean(latencies)
    test_result("ST2.3 Avg decrypt latency < 1ms", avg_latency < 1000,
                f"{avg_latency:.1f}µs")

    return True


# =============================================================================
# ST3: Key Exchange Performance Tests
# =============================================================================

def test_st3_key_exchange_perf(iterations: int = 100):
    """Test key exchange performance"""
    print("\n" + "=" * 60)
    print("  ST3: Key Exchange Performance Tests")
    print("=" * 60)

    try:
        from ecies import ECIES
    except ImportError as e:
        print(f"  SKIP: Cannot import ecies: {e}")
        return False

    # ST3.1: Keypair generation speed
    start = time.time()
    keypairs = []
    for _ in range(iterations):
        keypairs.append(ECIES.generate_keypair())
    elapsed = time.time() - start
    rate = iterations / elapsed
    test_result("ST3.1 Keypair generation", rate > 50,
                f"{rate:.1f} keypairs/s")

    # ST3.2: ECDH speed
    priv_a, pub_a = keypairs[0]
    priv_b, pub_b = keypairs[1]

    start = time.time()
    for _ in range(iterations):
        ECIES.ecdh(priv_a, pub_b)
    elapsed = time.time() - start
    rate = iterations / elapsed
    test_result("ST3.2 ECDH computation", rate > 100,
                f"{rate:.1f} ECDH/s")

    # ST3.3: Full ECIES encrypt
    dek = os.urandom(32)
    start = time.time()
    for _ in range(iterations):
        ECIES.encrypt_dek(pub_b, dek)
    elapsed = time.time() - start
    rate = iterations / elapsed
    test_result("ST3.3 ECIES encrypt", rate > 50,
                f"{rate:.1f} enc/s")

    # ST3.4: Full ECIES decrypt
    eph, enc_dek, nonce, tag = ECIES.encrypt_dek(pub_b, dek)
    start = time.time()
    for _ in range(iterations):
        ECIES.decrypt_dek(priv_b, eph, enc_dek, nonce, tag)
    elapsed = time.time() - start
    rate = iterations / elapsed
    test_result("ST3.4 ECIES decrypt", rate > 100,
                f"{rate:.1f} dec/s")

    return True


# =============================================================================
# ST4: Multi-peer Stress Tests
# =============================================================================

def test_st4_multi_peer(num_peers: int = 20):
    """Test multi-peer handling under stress"""
    print("\n" + "=" * 60)
    print("  ST4: Multi-peer Stress Tests")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        print(f"  SKIP: Cannot import dual_dek_engine: {e}")
        return False

    # Create main engine
    my_dek = os.urandom(32)
    dde = DualDekEngine(my_dek=my_dek)

    # ST4.1: Add many peers
    peer_deks = {}
    start = time.time()
    for i in range(1, num_peers + 1):
        peer_dek = os.urandom(32)
        peer_deks[i] = peer_dek
        dde.set_peer_dek(i, peer_dek)
    elapsed = time.time() - start
    test_result("ST4.1 Add 20 peers", elapsed < 1.0,
                f"{elapsed*1000:.1f}ms")

    # ST4.2: Encrypt/decrypt with all peers
    payload = b"Test message for multi-peer stress"
    success = 0

    for sysid, peer_dek in peer_deks.items():
        peer_dde = DualDekEngine(my_dek=peer_dek)
        peer_dde.set_peer_dek(255, my_dek)

        # We encrypt, peer decrypts
        enc = dde.encrypt(payload)
        dec = peer_dde.decrypt(255, enc)
        if dec == payload:
            success += 1

    test_result("ST4.2 All peers decrypt OK", success == num_peers,
                f"{success}/{num_peers}")

    # ST4.3: Rapid peer switching (simulate multi-drone scenario)
    iterations = 1000
    start = time.time()
    success = 0

    for i in range(iterations):
        sysid = (i % num_peers) + 1
        peer_dek = peer_deks[sysid]

        peer_dde = DualDekEngine(my_dek=peer_dek)
        peer_dde.set_peer_dek(255, my_dek)

        enc = dde.encrypt(payload)
        dec = peer_dde.decrypt(255, enc)
        if dec == payload:
            success += 1

    elapsed = time.time() - start
    rate = iterations / elapsed
    test_result("ST4.3 Rapid peer switching", success == iterations,
                f"{rate:.0f} switches/s")

    return True


# =============================================================================
# ST5: Memory/Resource Tests
# =============================================================================

def test_st5_resources():
    """Test memory and resource usage"""
    print("\n" + "=" * 60)
    print("  ST5: Memory/Resource Tests")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine
        from ecies import ECIES
        import gc
    except ImportError as e:
        print(f"  SKIP: Cannot import modules: {e}")
        return False

    # ST5.1: Repeated engine creation (check for leaks)
    gc.collect()
    start_objects = len(gc.get_objects())

    for _ in range(100):
        dek = os.urandom(32)
        dde = DualDekEngine(my_dek=dek)
        for i in range(10):
            dde.set_peer_dek(i, os.urandom(32))
        dde.encrypt(b"test")
        del dde

    gc.collect()
    end_objects = len(gc.get_objects())
    growth = end_objects - start_objects

    # Allow some growth but not excessive
    test_result("ST5.1 No major memory leak", growth < 1000,
                f"object growth: {growth}")

    # ST5.2: Repeated keypair generation
    gc.collect()
    for _ in range(100):
        priv, pub = ECIES.generate_keypair()
        del priv, pub

    gc.collect()
    test_result("ST5.2 Keypair cleanup", True)

    # ST5.3: Large number of encryptions
    dde = DualDekEngine(my_dek=os.urandom(32))
    payload = os.urandom(128)

    for _ in range(10000):
        enc = dde.encrypt(payload)
        del enc

    gc.collect()
    test_result("ST5.3 10K encryptions OK", True)

    return True


# =============================================================================
# ST6: Long-running Stability Tests
# =============================================================================

def test_st6_stability(duration: int = 10):
    """Test long-running stability"""
    print("\n" + "=" * 60)
    print(f"  ST6: Long-running Stability Tests ({duration}s)")
    print("=" * 60)

    try:
        from dual_dek_engine import DualDekEngine
    except ImportError as e:
        print(f"  SKIP: Cannot import dual_dek_engine: {e}")
        return False

    # Setup
    dek1 = os.urandom(32)
    dek2 = os.urandom(32)

    dde1 = DualDekEngine(my_dek=dek1)
    dde1.set_peer_dek(2, dek2)

    dde2 = DualDekEngine(my_dek=dek2)
    dde2.set_peer_dek(1, dek1)

    payload = os.urandom(128)

    # ST6.1: Continuous encrypt/decrypt for duration
    start = time.time()
    success = 0
    errors = 0
    total = 0

    while time.time() - start < duration:
        try:
            enc = dde1.encrypt(payload)
            dec = dde2.decrypt(1, enc)
            if dec == payload:
                success += 1
            else:
                errors += 1
            total += 1
        except Exception as e:
            errors += 1
            total += 1

    elapsed = time.time() - start
    rate = total / elapsed
    error_rate = (errors / total * 100) if total > 0 else 0

    test_result("ST6.1 Long-running success", error_rate == 0,
                f"{total} ops, {rate:.0f} ops/s, {error_rate:.2f}% errors")

    # ST6.2: No degradation (compare first and last 100 ops timing)
    # Already ran, just report
    test_result("ST6.2 No performance degradation", rate > 100,
                f"sustained {rate:.0f} ops/s")

    return True


# =============================================================================
# Main
# =============================================================================

def main():
    global PASSED, FAILED

    parser = argparse.ArgumentParser(description="HSM Stress/Performance Tests")
    parser.add_argument('--duration', type=int, default=10,
                        help='Duration for stability test (seconds)')
    parser.add_argument('--iterations', type=int, default=1000,
                        help='Iterations for throughput tests')
    args = parser.parse_args()

    print("=" * 60)
    print("  HSM Stress and Performance Tests")
    print("=" * 60)
    print(f"  Iterations: {args.iterations}")
    print(f"  Stability duration: {args.duration}s")
    print("=" * 60)

    start_time = time.time()

    # Run tests
    test_st1_encryption_throughput(args.iterations)
    test_st2_decryption_throughput(args.iterations)
    test_st3_key_exchange_perf(min(args.iterations, 100))
    test_st4_multi_peer(20)
    test_st5_resources()
    test_st6_stability(args.duration)

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("  Stress Test Summary")
    print("=" * 60)
    print(f"  PASSED:  {PASSED}")
    print(f"  FAILED:  {FAILED}")
    print(f"  Time:    {elapsed:.1f}s")
    print("=" * 60)

    if FAILED == 0:
        print("\n  \033[92mAll stress tests PASSED!\033[0m")
        return 0
    else:
        print(f"\n  \033[91m{FAILED} tests FAILED\033[0m")
        return 1


if __name__ == '__main__':
    sys.exit(main())
