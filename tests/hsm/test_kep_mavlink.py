#!/usr/bin/env python3
"""
Test Key Exchange Protocol via MAVLink

Connects to SITL and performs WK exchange with the drone.

Usage:
    1. Start SITL: ./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &
    2. Wait for HSM init (~25s)
    3. Run this script: python3 tests/hsm/test_kep_mavlink.py
"""

import sys
import os
import time
import socket
import struct

# Add generated mavlink to path
sys.path.insert(0, '/tmp')
import mavlink_hsm as mavlink

# Add Tools/hsm to path for ECIES
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../Tools/hsm'))

try:
    from ecies import ECIES, CRYPTO_AVAILABLE
except ImportError:
    CRYPTO_AVAILABLE = False
    print("WARNING: ECIES not available")


class KEPTest:
    """Test Key Exchange Protocol via MAVLink"""

    def __init__(self, host='127.0.0.1', port=5760):
        self.host = host
        self.port = port
        self.sock = None
        self.mav = None

        # Our identity
        self.my_sysid = 255
        self.my_compid = 0

        # Keys (generate random for test)
        if CRYPTO_AVAILABLE:
            self._wk_private, self._wk_public = ECIES.generate_keypair()
            self._my_dek = os.urandom(32)
            print(f"Generated WK: {self._wk_public[:8].hex()}...")
            print(f"Generated DEK: {self._my_dek[:4].hex()}...")
        else:
            # Dummy keys
            self._wk_public = bytes(64)
            self._my_dek = bytes(32)

        # Peer info
        self.peer_wk_received = False
        self.peer_wk_public = None
        self.peer_dek_received = False
        self.peer_dek = None

    def connect(self):
        """Connect to SITL via TCP"""
        print(f"\nConnecting to {self.host}:{self.port}...")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)

        try:
            self.sock.connect((self.host, self.port))
            print("Connected!")
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

        self.sock.setblocking(False)
        self.mav = mavlink.MAVLink(None)
        self.mav.srcSystem = self.my_sysid
        self.mav.srcComponent = self.my_compid
        return True

    def send_heartbeat(self):
        """Send HEARTBEAT to drone"""
        msg = self.mav.heartbeat_encode(
            type=mavlink.MAV_TYPE_GCS,
            autopilot=mavlink.MAV_AUTOPILOT_INVALID,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink.MAV_STATE_ACTIVE
        )
        self._send_msg(msg)

    def send_wk_exchange(self, target_sysid):
        """Send our WK_EXCHANGE to drone"""
        print(f"\n>>> Sending WK_EXCHANGE to sysid={target_sysid}")
        print(f"    WK_PUB: {self._wk_public[:8].hex()}...")

        msg = self.mav.hsm_wk_exchange_encode(
            target_system=target_sysid,
            target_component=1,
            wk_public=self._wk_public,
            timestamp=int(time.time() * 1000) & 0xFFFFFFFF
        )
        self._send_msg(msg)

    def send_dek_exchange(self, target_sysid, peer_wk_public):
        """Send our DEK encrypted with peer's WK"""
        if not CRYPTO_AVAILABLE:
            print("Cannot send DEK: ECIES not available")
            return

        print(f"\n>>> Sending DEK_EXCHANGE to sysid={target_sysid}")

        # Encrypt our DEK with peer's WK
        ephemeral_pub, encrypted_dek, nonce, tag = ECIES.encrypt_dek(
            peer_wk_public, self._my_dek
        )

        print(f"    Ephemeral: {ephemeral_pub[:8].hex()}...")
        print(f"    Encrypted: {encrypted_dek[:8].hex()}...")

        msg = self.mav.hsm_dek_exchange_encode(
            target_system=target_sysid,
            target_component=1,
            ephemeral_pubkey=ephemeral_pub,
            encrypted_dek=encrypted_dek,
            nonce=nonce,
            auth_tag=tag
        )
        self._send_msg(msg)

    def _send_msg(self, msg):
        """Send MAVLink message"""
        buf = msg.pack(self.mav)
        self.sock.send(buf)

    def receive_messages(self, timeout=1.0):
        """Receive and process messages"""
        start = time.time()
        bytes_received = 0
        msgs_parsed = 0
        parse_errors = 0
        while time.time() - start < timeout:
            try:
                data = self.sock.recv(1024)
                if data:
                    bytes_received += len(data)
                    for byte in data:
                        try:
                            msg = self.mav.parse_char(bytes([byte]))
                            if msg:
                                msgs_parsed += 1
                                self._handle_message(msg)
                        except Exception as e:
                            parse_errors += 1
            except BlockingIOError:
                time.sleep(0.01)
            except Exception as e:
                print(f"Receive error: {e}")
                break
        # Show RX stats on first receive
        if bytes_received > 0 and not hasattr(self, '_first_rx_shown'):
            self._first_rx_shown = True
            print(f"    [RX] First data: {bytes_received} bytes, {msgs_parsed} msgs, {parse_errors} errors")

    def _handle_message(self, msg):
        """Handle received MAVLink message"""
        msg_id = msg.get_msgId()

        # Debug: show first few message types
        if not hasattr(self, '_msg_types_seen'):
            self._msg_types_seen = set()
        if msg_id not in self._msg_types_seen and len(self._msg_types_seen) < 10:
            self._msg_types_seen.add(msg_id)
            print(f"    [DEBUG] New msg type: {msg_id} from sysid={msg.get_srcSystem()}")

        if msg_id == mavlink.MAVLINK_MSG_ID_HEARTBEAT:
            if msg.get_srcSystem() != self.my_sysid:
                self._drone_hb_seen = True
                print(f"<<< HEARTBEAT from sysid={msg.get_srcSystem()}")

        elif msg_id == mavlink.MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
            self._handle_wk_exchange(msg)

        elif msg_id == mavlink.MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
            self._handle_dek_exchange(msg)

        elif msg_id == mavlink.MAVLINK_MSG_ID_HSM_KEY_ACK:
            self._handle_key_ack(msg)

    def _handle_wk_exchange(self, msg):
        """Handle WK_EXCHANGE from drone"""
        src_sysid = msg.get_srcSystem()
        wk_pub = bytes(msg.wk_public)

        print(f"\n<<< HSM_WK_EXCHANGE from sysid={src_sysid}")
        print(f"    WK_PUB: {wk_pub[:8].hex()}...")

        self.peer_wk_received = True
        self.peer_wk_public = wk_pub

        # Send our WK in response
        self.send_wk_exchange(src_sysid)

        # Now send our DEK encrypted with peer's WK
        if CRYPTO_AVAILABLE and self.peer_wk_public:
            time.sleep(0.1)  # Small delay
            self.send_dek_exchange(src_sysid, self.peer_wk_public)

    def _handle_dek_exchange(self, msg):
        """Handle DEK_EXCHANGE from drone"""
        src_sysid = msg.get_srcSystem()
        ephemeral_pub = bytes(msg.ephemeral_pubkey)
        encrypted_dek = bytes(msg.encrypted_dek)
        nonce = bytes(msg.nonce)
        tag = bytes(msg.auth_tag)

        print(f"\n<<< HSM_DEK_EXCHANGE from sysid={src_sysid}")
        print(f"    Ephemeral: {ephemeral_pub[:8].hex()}...")

        if CRYPTO_AVAILABLE:
            try:
                decrypted_dek = ECIES.decrypt_dek(
                    self._wk_private,
                    ephemeral_pub,
                    encrypted_dek,
                    nonce,
                    tag
                )
                if decrypted_dek:
                    self.peer_dek_received = True
                    self.peer_dek = decrypted_dek
                    print(f"    ✓ DEK decrypted: {decrypted_dek[:4].hex()}...")
                else:
                    print(f"    ✗ DEK decryption failed (auth)")
            except Exception as e:
                print(f"    ✗ DEK decryption error: {e}")
        else:
            print("    Cannot decrypt: ECIES not available")

    def _handle_key_ack(self, msg):
        """Handle KEY_ACK from drone"""
        src_sysid = msg.get_srcSystem()
        status = msg.status
        phase = msg.phase

        status_names = {0: 'SUCCESS', 1: 'WK_ERROR', 2: 'DEK_ERROR', 3: 'TIMEOUT'}
        phase_names = {1: 'WK_RECEIVED', 2: 'DEK_RECEIVED', 3: 'COMPLETE'}

        print(f"\n<<< HSM_KEY_ACK from sysid={src_sysid}: "
              f"status={status_names.get(status, status)} "
              f"phase={phase_names.get(phase, phase)}")

    def run_test(self):
        """Run the key exchange test"""
        print("=" * 60)
        print("  Key Exchange Protocol - MAVLink Test")
        print("=" * 60)
        print("  NOTE: Run this BEFORE any other connection to SITL")
        print("=" * 60)

        if not self.connect():
            return False

        print("\n0. Waiting for HSM init + sending HEARTBEATs (~40s)...")
        print("   (WK_EXCHANGE will be sent when drone detects us)")
        for i in range(80):  # 80 * 0.5s = 40s max wait
            self.send_heartbeat()
            self.receive_messages(timeout=0.5)
            # Check if we received WK from drone (means init complete + exchange started)
            if self.peer_wk_received:
                print(f"\n   ✓ WK_EXCHANGE received after {i*0.5:.1f}s!")
                break
            # Show progress
            if i % 10 == 0:
                if hasattr(self, '_drone_hb_seen') and self._drone_hb_seen:
                    print(f"   [{i*0.5:.0f}s] Drone HEARTBEAT OK, waiting for WK...")
                else:
                    print(f"   [{i*0.5:.0f}s] Waiting for drone HEARTBEAT...")

        print("\n1. Sending HEARTBEATs to trigger discovery...")
        for i in range(5):
            self.send_heartbeat()
            self.receive_messages(timeout=0.5)

        print("\n2. Waiting for WK_EXCHANGE from drone...")
        for i in range(20):
            self.receive_messages(timeout=0.5)
            if self.peer_wk_received:
                break

        print("\n3. Waiting for DEK_EXCHANGE from drone...")
        for i in range(10):
            self.receive_messages(timeout=0.5)
            if self.peer_dek_received:
                break

        print("\n" + "=" * 60)
        print("  RESULTS")
        print("=" * 60)
        print(f"  Peer WK received: {'✓' if self.peer_wk_received else '✗'}")
        print(f"  Peer DEK received: {'✓' if self.peer_dek_received else '✗'}")

        if self.peer_wk_received and self.peer_dek_received:
            print("\n  *** KEY EXCHANGE SUCCESS ***")
            return True
        else:
            print("\n  *** KEY EXCHANGE INCOMPLETE ***")
            return False


def main():
    test = KEPTest()
    success = test.run_test()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
