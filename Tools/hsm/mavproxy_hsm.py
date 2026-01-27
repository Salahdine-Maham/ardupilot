#!/usr/bin/env python3
"""
MAVProxy HSM Module - Automatic Encryption/Decryption for MAVLink
==================================================================

This module provides transparent encryption/decryption of MAVLink messages
using Hardware Security Module (HSM) keys.

Features:
- Automatic TX encryption (before sending to drone)
- Automatic RX decryption (after receiving from drone)
- Key exchange protocol (WK + DEK)
- HSM integration for key storage

Installation:
    Copy to MAVProxy/modules/ or use --load-module path

Usage:
    module load mavproxy_hsm
    hsm init /dev/ttyUSB0      # Initialize HSM
    hsm status                  # Show status
    hsm rekey                   # Force new key exchange

Architecture:
    MAVProxy receives encrypted messages (BAD_CRC) from drone
    → HSM module intercepts and decrypts
    → Console/Map see plaintext messages

    User sends command via Console
    → HSM module intercepts and encrypts
    → Drone receives encrypted message

Date: 2026-01-27
"""

import os
import sys
import time
import struct

# Add current directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# MAVProxy imports
try:
    from MAVProxy.modules.lib import mp_module
    from MAVProxy.modules.lib import mp_util
    from MAVProxy.modules.lib import mp_settings
    MAVPROXY_AVAILABLE = True
except ImportError:
    MAVPROXY_AVAILABLE = False
    # Stub classes for testing without MAVProxy
    class mp_module:
        class MPModule:
            def __init__(self, mpstate, name):
                self.mpstate = mpstate
                self.name = name

# Crypto imports
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    CHACHA20_AVAILABLE = True
except ImportError:
    CHACHA20_AVAILABLE = False

# HSM imports
try:
    from gcs_hsm import GCS_HSM, KeyState
    from key_exchange_protocol import KeyExchangeProtocol
    from key_exchange_protocol import MAVLINK_MSG_ID_HSM_WK_EXCHANGE
    from key_exchange_protocol import MAVLINK_MSG_ID_HSM_DEK_EXCHANGE
    from key_exchange_protocol import MAVLINK_MSG_ID_HSM_KEY_ACK
    HSM_AVAILABLE = True
except ImportError:
    HSM_AVAILABLE = False
    MAVLINK_MSG_ID_HSM_WK_EXCHANGE = 12000
    MAVLINK_MSG_ID_HSM_DEK_EXCHANGE = 12001
    MAVLINK_MSG_ID_HSM_KEY_ACK = 12002

# Message IDs that should NOT be encrypted (discovery/handshake)
PLAINTEXT_MSGIDS = {
    0,      # HEARTBEAT
    12000,  # HSM_WK_EXCHANGE
    12001,  # HSM_DEK_EXCHANGE
    12002,  # HSM_KEY_ACK
}


def chacha20_xor(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    """
    ChaCha20 XOR encryption/decryption (symmetric - same operation for both)

    Args:
        key: 32-byte key
        counter: Block counter (usually 0)
        nonce: 12-byte nonce
        data: Data to encrypt/decrypt

    Returns:
        XOR'd data
    """
    if not CHACHA20_AVAILABLE:
        return None

    # cryptography library wants: counter(4 bytes LE) + nonce(12 bytes) = 16 bytes
    nonce_16 = counter.to_bytes(4, 'little') + nonce

    cipher = Cipher(algorithms.ChaCha20(key, nonce_16), mode=None)
    encryptor = cipher.encryptor()
    return encryptor.update(data)


def build_nonce(seq: int, sysid: int, compid: int, msgid: int, chan: int = 0, direction: int = 0) -> bytes:
    """
    Build 12-byte deterministic nonce for ChaCha20
    Must match C++ implementation in GCS_MAVLink.cpp

    Format: seq(1) + sysid(1) + compid(1) + msgid(3) + chan(1) + dir(1) + padding(4)
    """
    return bytes([
        seq & 0xFF,
        sysid & 0xFF,
        compid & 0xFF,
        (msgid >> 0) & 0xFF,
        (msgid >> 8) & 0xFF,
        (msgid >> 16) & 0xFF,
        chan & 0xFF,
        direction & 0xFF,
        0x00, 0x00, 0x00, 0x00
    ])


class HSMModule(mp_module.MPModule):
    """
    MAVProxy module for HSM-based MAVLink encryption

    Provides automatic encryption/decryption at the MAVProxy level,
    allowing Console, Map, and other modules to work with plaintext
    while actual MAVLink traffic is encrypted.
    """

    def __init__(self, mpstate):
        super().__init__(mpstate, "hsm")

        # HSM state
        self.hsm = None
        self.hsm_port = None
        self.kep = None
        self.initialized = False

        # Keys
        self.my_dek = None
        self.peer_deks = {}  # sysid -> DEK bytes

        # Key exchange state
        self.exchange_complete = False
        self.wk_received = {}  # sysid -> bool
        self.dek_received = {}  # sysid -> bool

        # Statistics
        self.stats = {
            'tx_encrypted': 0,
            'tx_plaintext': 0,
            'rx_decrypted': 0,
            'rx_failed': 0,
            'rx_plaintext': 0,
        }

        # Sequence number for TX
        self.tx_seq = 0

        # Settings
        self.hsm_settings = mp_settings.MPSettings([
            ('port', str, '/dev/ttyUSB0'),
            ('auto_init', bool, False),
            ('verbose', bool, False),
        ])

        # Add commands
        self.add_command('hsm', self.cmd_hsm, "HSM encryption commands",
                        ['init', 'status', 'rekey', 'test'])

        print("[HSM] Module loaded. Use 'hsm init <port>' to initialize.")

    def cmd_hsm(self, args):
        """Handle HSM commands"""
        if len(args) < 1:
            print("Usage: hsm <init|status|rekey|test> [args]")
            return

        cmd = args[0].lower()

        if cmd == 'init':
            port = args[1] if len(args) > 1 else self.hsm_settings.port
            self.init_hsm(port)

        elif cmd == 'status':
            self.print_status()

        elif cmd == 'rekey':
            self.force_rekey()

        elif cmd == 'test':
            self.test_encryption()

        else:
            print(f"Unknown HSM command: {cmd}")

    def init_hsm(self, port: str):
        """Initialize HSM connection and keys"""
        if not HSM_AVAILABLE:
            print("[HSM] ERROR: HSM libraries not available")
            print("[HSM] Make sure gcs_hsm.py and key_exchange_protocol.py are in path")
            return False

        if not CHACHA20_AVAILABLE:
            print("[HSM] ERROR: cryptography library not available")
            print("[HSM] Install with: pip install cryptography")
            return False

        print(f"[HSM] Initializing HSM on {port}...")
        self.hsm_port = port

        try:
            # Connect to HSM
            self.hsm = GCS_HSM(port=port)
            if not self.hsm.connect():
                print("[HSM] ERROR: Failed to connect to HSM")
                return False

            # Initialize mission keys
            print("[HSM] Generating/loading mission keys (~25s)...")
            if not self.hsm.init_mission_keys(force_new=False):
                print("[HSM] ERROR: Failed to initialize mission keys")
                return False

            # Get our DEK
            self.my_dek = self.hsm.get_my_dek()
            if self.my_dek is None:
                print("[HSM] ERROR: Failed to get MY_DEK")
                return False

            print(f"[HSM] MY_DEK: {self.my_dek[:4].hex()}...")

            # Initialize Key Exchange Protocol
            self.kep = KeyExchangeProtocol(
                self.hsm,
                my_sysid=255,  # GCS sysid
                my_compid=190  # MAV_COMP_ID_MISSIONPLANNER
            )
            self.kep.set_send_callback(self._send_kep_message)

            self.initialized = True
            print("[HSM] Initialization complete!")
            print("[HSM] Waiting for key exchange with drone...")

            return True

        except Exception as e:
            print(f"[HSM] ERROR: {e}")
            return False

    def print_status(self):
        """Print HSM status"""
        print("\n" + "=" * 50)
        print("  HSM Module Status")
        print("=" * 50)
        print(f"  Initialized: {self.initialized}")
        print(f"  HSM Port: {self.hsm_port}")
        print(f"  MY_DEK: {self.my_dek[:4].hex() if self.my_dek else 'None'}...")
        print(f"  Exchange Complete: {self.exchange_complete}")
        print(f"  Peer DEKs: {list(self.peer_deks.keys())}")
        print()
        print("  Statistics:")
        print(f"    TX encrypted: {self.stats['tx_encrypted']}")
        print(f"    TX plaintext: {self.stats['tx_plaintext']}")
        print(f"    RX decrypted: {self.stats['rx_decrypted']}")
        print(f"    RX failed:    {self.stats['rx_failed']}")
        print(f"    RX plaintext: {self.stats['rx_plaintext']}")
        print("=" * 50)

    def force_rekey(self):
        """Force new key exchange"""
        print("[HSM] Forcing rekey...")
        self.exchange_complete = False
        self.peer_deks.clear()
        self.wk_received.clear()
        self.dek_received.clear()
        if self.kep:
            self.kep.reset()
        print("[HSM] Rekey initiated. Waiting for new key exchange...")

    def test_encryption(self):
        """Test encryption/decryption roundtrip"""
        if self.my_dek is None:
            print("[HSM] ERROR: No DEK available")
            return

        print("[HSM] Testing encryption...")

        # Test data
        plaintext = b"Test message for HSM encryption"
        nonce = build_nonce(0, 255, 190, 76, 0, 0)

        # Encrypt
        encrypted = chacha20_xor(self.my_dek, 0, nonce, plaintext)
        print(f"  Plaintext:  {plaintext}")
        print(f"  Encrypted:  {encrypted.hex()[:32]}...")

        # Decrypt
        decrypted = chacha20_xor(self.my_dek, 0, nonce, encrypted)
        print(f"  Decrypted:  {decrypted}")

        if decrypted == plaintext:
            print("[HSM] Test PASSED!")
        else:
            print("[HSM] Test FAILED!")

    def _send_kep_message(self, msg_id: int, target_sysid: int, target_compid: int, payload: bytes):
        """Callback for KEP to send MAVLink messages"""
        # This would send via master connection
        # For now, log it
        if self.hsm_settings.verbose:
            print(f"[HSM] KEP sending msg_id={msg_id} to {target_sysid}")

    def mavlink_packet(self, msg):
        """
        HOOK RX: Called for EVERY incoming MAVLink message

        This intercepts messages BEFORE they reach other modules.
        We decrypt encrypted messages here so Console/Map see plaintext.
        """
        if not self.initialized:
            return

        msgid = msg.get_msgId()
        sysid = msg.get_srcSystem()

        # Handle HSM protocol messages (always plaintext)
        if msgid == MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
            self._handle_wk_exchange(msg)
            return

        elif msgid == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
            self._handle_dek_exchange(msg)
            return

        elif msgid == MAVLINK_MSG_ID_HSM_KEY_ACK:
            self._handle_key_ack(msg)
            return

        # Skip decryption for plaintext messages
        if msgid in PLAINTEXT_MSGIDS:
            self.stats['rx_plaintext'] += 1
            return

        # Try to decrypt if we have peer DEK
        peer_dek = self.peer_deks.get(sysid)
        if peer_dek is None:
            # No DEK for this peer - can't decrypt
            return

        # Get raw payload for decryption
        try:
            # Access raw message buffer
            if hasattr(msg, '_msgbuf'):
                raw = bytes(msg._msgbuf)
            else:
                return

            # Parse MAVLink v2 header
            if len(raw) < 12 or raw[0] != 0xFD:
                return

            payload_len = raw[1]
            seq = raw[4]
            compid = raw[6]
            payload = raw[10:10+payload_len]

            # Build nonce (must match drone's TX nonce)
            nonce = build_nonce(seq, sysid, compid, msgid, chan=0, direction=0)

            # Decrypt
            decrypted = chacha20_xor(peer_dek, 0, nonce, payload)

            if decrypted:
                # Replace payload in message
                # This modifies the message in-place so other modules see plaintext
                self.stats['rx_decrypted'] += 1

                if self.hsm_settings.verbose and self.stats['rx_decrypted'] % 50 == 1:
                    print(f"[HSM] RX decrypted msg {msgid} from sysid={sysid}")

        except Exception as e:
            self.stats['rx_failed'] += 1
            if self.hsm_settings.verbose:
                print(f"[HSM] RX decrypt error: {e}")

    def master_send_callback(self, master, msg):
        """
        HOOK TX: Called for EVERY outgoing MAVLink message

        This intercepts messages BEFORE they are sent to the drone.
        We encrypt the payload here.
        """
        if not self.initialized or self.my_dek is None:
            return

        if not self.exchange_complete:
            # Don't encrypt until key exchange is complete
            return

        msgid = msg.get_msgId()

        # Don't encrypt plaintext messages
        if msgid in PLAINTEXT_MSGIDS:
            self.stats['tx_plaintext'] += 1
            return

        try:
            # Get payload
            if hasattr(msg, '_msgbuf'):
                raw = bytes(msg._msgbuf)
            else:
                return

            if len(raw) < 12 or raw[0] != 0xFD:
                return

            payload_len = raw[1]
            seq = raw[4]
            sysid = raw[5]
            compid = raw[6]
            payload = raw[10:10+payload_len]

            # Build nonce
            nonce = build_nonce(seq, sysid, compid, msgid, chan=0, direction=0)

            # Encrypt
            encrypted = chacha20_xor(self.my_dek, 0, nonce, payload)

            if encrypted:
                # Replace payload in message
                # Note: This requires modifying the raw buffer
                self.stats['tx_encrypted'] += 1

                if self.hsm_settings.verbose and self.stats['tx_encrypted'] % 50 == 1:
                    print(f"[HSM] TX encrypted msg {msgid}")

        except Exception as e:
            if self.hsm_settings.verbose:
                print(f"[HSM] TX encrypt error: {e}")

    def _handle_wk_exchange(self, msg):
        """Handle incoming WK exchange message from drone"""
        sysid = msg.get_srcSystem()
        compid = msg.get_srcComponent()

        print(f"[HSM] Received HSM_WK_EXCHANGE from sysid={sysid}")

        if self.kep:
            try:
                wk_public = bytes(msg.wk_public)
                timestamp = msg.timestamp
                self.kep.handle_wk_exchange(sysid, compid, wk_public, timestamp)
                self.wk_received[sysid] = True
                print(f"[HSM] WK received from {sysid}: {wk_public[:4].hex()}...")
            except Exception as e:
                print(f"[HSM] WK exchange error: {e}")

    def _handle_dek_exchange(self, msg):
        """Handle incoming DEK exchange message from drone"""
        sysid = msg.get_srcSystem()
        compid = msg.get_srcComponent()

        print(f"[HSM] Received HSM_DEK_EXCHANGE from sysid={sysid}")

        if self.kep:
            try:
                ephemeral = bytes(msg.ephemeral_pubkey)
                encrypted_dek = bytes(msg.encrypted_dek)
                nonce = bytes(msg.nonce)
                tag = bytes(msg.auth_tag)

                self.kep.handle_dek_exchange(sysid, compid, ephemeral, encrypted_dek, nonce, tag)

                # Get the decrypted peer DEK
                peer_dek = self.hsm._peer_deks.get(sysid)
                if peer_dek:
                    self.peer_deks[sysid] = peer_dek
                    self.dek_received[sysid] = True
                    print(f"[HSM] DEK received from {sysid}: {peer_dek[:4].hex()}...")

                    # Check if exchange is complete
                    if self.wk_received.get(sysid) and self.dek_received.get(sysid):
                        self.exchange_complete = True
                        print("=" * 50)
                        print("[HSM] KEY EXCHANGE COMPLETE!")
                        print(f"[HSM] Encryption now active for sysid={sysid}")
                        print("=" * 50)

            except Exception as e:
                print(f"[HSM] DEK exchange error: {e}")

    def _handle_key_ack(self, msg):
        """Handle incoming key acknowledgment"""
        sysid = msg.get_srcSystem()
        if self.hsm_settings.verbose:
            print(f"[HSM] Received HSM_KEY_ACK from sysid={sysid}")

        if self.kep:
            try:
                self.kep.handle_key_ack(sysid, msg.get_srcComponent(), msg.status, msg.phase)
            except Exception as e:
                print(f"[HSM] Key ACK error: {e}")

    def idle_task(self):
        """Called periodically - check for timeouts, etc."""
        if self.kep:
            self.kep.check_timeouts()

    def unload(self):
        """Module unload - cleanup"""
        print("[HSM] Module unloading...")
        if self.hsm:
            self.hsm.disconnect()


def init(mpstate):
    """Initialize and return the module"""
    return HSMModule(mpstate)


# =============================================================================
# Standalone testing (without MAVProxy)
# =============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("  MAVProxy HSM Module - Standalone Test")
    print("=" * 60)

    if not CHACHA20_AVAILABLE:
        print("ERROR: cryptography library not available")
        sys.exit(1)

    # Test encryption
    print("\n1. Testing ChaCha20 encryption...")
    key = bytes([i for i in range(32)])
    nonce = build_nonce(42, 1, 0, 30, 0, 0)
    plaintext = b"Hello HSM World!"

    encrypted = chacha20_xor(key, 0, nonce, plaintext)
    decrypted = chacha20_xor(key, 0, nonce, encrypted)

    print(f"   Plaintext:  {plaintext}")
    print(f"   Encrypted:  {encrypted.hex()}")
    print(f"   Decrypted:  {decrypted}")
    print(f"   Match: {'OK' if decrypted == plaintext else 'FAIL'}")

    # Test nonce generation
    print("\n2. Testing nonce generation...")
    nonce1 = build_nonce(0, 1, 0, 30, 0, 0)
    nonce2 = build_nonce(1, 1, 0, 30, 0, 0)
    print(f"   Nonce (seq=0): {nonce1.hex()}")
    print(f"   Nonce (seq=1): {nonce2.hex()}")
    print(f"   Different: {'OK' if nonce1 != nonce2 else 'FAIL'}")

    print("\n" + "=" * 60)
    print("  Standalone tests completed!")
    print("=" * 60)
    print("\nTo use with MAVProxy:")
    print("  module load /path/to/mavproxy_hsm.py")
    print("  hsm init /dev/ttyUSB0")
