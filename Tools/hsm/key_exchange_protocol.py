#!/usr/bin/env python3
"""
Key Exchange Protocol for GCS

Implements the HSM key exchange protocol:
1. Discover peers via HEARTBEAT
2. Exchange Wrapper Key public keys (HSM_WK_EXCHANGE)
3. Exchange encrypted DEKs via ECIES (HSM_DEK_EXCHANGE)
4. Acknowledge completion (HSM_KEY_ACK)

Date: 2026-01-24
"""

import time
import struct
from enum import Enum
from typing import Optional, Dict, Callable
from dataclasses import dataclass, field

try:
    from .ecies import ECIES, CRYPTO_AVAILABLE
    from .gcs_hsm import GCS_HSM, KeyState
except ImportError:
    from ecies import ECIES, CRYPTO_AVAILABLE
    from gcs_hsm import GCS_HSM, KeyState

# MAVLink message IDs
MAVLINK_MSG_ID_HSM_WK_EXCHANGE = 12000
MAVLINK_MSG_ID_HSM_DEK_EXCHANGE = 12001
MAVLINK_MSG_ID_HSM_KEY_ACK = 12002


class ExchangeState(Enum):
    """State machine for key exchange with a peer"""
    IDLE = 0
    WK_SENT = 1
    WK_RECEIVED = 2
    DEK_SENT = 3
    DEK_RECEIVED = 4
    COMPLETE = 5
    ERROR = 6


class AckStatus(Enum):
    """ACK status codes"""
    SUCCESS = 0
    WK_ERROR = 1
    DEK_ERROR = 2
    TIMEOUT = 3


class AckPhase(Enum):
    """ACK phase codes"""
    WK_RECEIVED = 1
    DEK_RECEIVED = 2
    COMPLETE = 3


@dataclass
class PeerInfo:
    """Information about a peer in the key exchange"""
    sysid: int
    compid: int
    wk_public: Optional[bytes] = None
    dek: Optional[bytes] = None
    state: ExchangeState = ExchangeState.IDLE
    last_activity: float = field(default_factory=time.time)
    wk_received: bool = False
    dek_received: bool = False


class KeyExchangeProtocol:
    """
    Key Exchange Protocol implementation for GCS

    Usage:
        hsm = GCS_HSM()
        hsm.connect()
        hsm.init_mission_keys()

        kep = KeyExchangeProtocol(hsm)
        kep.set_send_callback(mavlink_send_func)

        # When heartbeat received:
        kep.on_heartbeat_received(sysid, compid)

        # When HSM_WK_EXCHANGE received:
        kep.handle_wk_exchange(sysid, compid, wk_pub, timestamp)

        # etc.
    """

    MAX_PEERS = 5
    EXCHANGE_TIMEOUT_S = 10.0  # 10 seconds

    def __init__(self, hsm: GCS_HSM, my_sysid: int = 255, my_compid: int = 0):
        """
        Initialize Key Exchange Protocol

        Args:
            hsm: GCS_HSM instance with keys loaded
            my_sysid: Our MAVLink system ID (default 255 for GCS)
            my_compid: Our MAVLink component ID
        """
        self.hsm = hsm
        self.my_sysid = my_sysid
        self.my_compid = my_compid

        # Peer table
        self.peers: Dict[tuple, PeerInfo] = {}

        # Callback for sending MAVLink messages
        self._send_callback: Optional[Callable] = None

        # Our Wrapper Key (derived from HSM)
        self._my_wk_private: Optional[bytes] = None
        self._my_wk_public: Optional[bytes] = None

        # Initialize WK from HSM
        self._init_wrapper_key()

    def _log(self, msg: str):
        """Log with prefix"""
        print(f"[KEP] {msg}", flush=True)

    def _init_wrapper_key(self):
        """Initialize Wrapper Key public from HSM private"""
        if self.hsm.wk_state != KeyState.LOADED:
            self._log("WARNING: WK not loaded in HSM")
            return

        # Get WK private from HSM (it's loaded in memory)
        self._my_wk_private = self.hsm._wk_private
        if self._my_wk_private:
            # Derive public key
            self._my_wk_public = ECIES.derive_public_key(self._my_wk_private)
            self._log(f"WK public initialized: {self._my_wk_public[:8].hex()}...")

    def set_send_callback(self, callback: Callable):
        """
        Set callback for sending MAVLink messages

        The callback should have signature:
            callback(msg_id: int, target_sysid: int, target_compid: int, payload: bytes)
        """
        self._send_callback = callback

    # =========================================================================
    # PEER MANAGEMENT
    # =========================================================================

    def _get_peer_key(self, sysid: int, compid: int) -> tuple:
        """Get dictionary key for peer"""
        return (sysid, compid)

    def find_peer(self, sysid: int, compid: int) -> Optional[PeerInfo]:
        """Find peer by sysid/compid"""
        return self.peers.get(self._get_peer_key(sysid, compid))

    def add_peer(self, sysid: int, compid: int) -> Optional[PeerInfo]:
        """Add new peer"""
        if len(self.peers) >= self.MAX_PEERS:
            self._log(f"ERROR: Max peers ({self.MAX_PEERS}) reached")
            return None

        key = self._get_peer_key(sysid, compid)
        peer = PeerInfo(sysid=sysid, compid=compid)
        self.peers[key] = peer
        return peer

    def get_num_peers(self) -> int:
        """Get number of known peers"""
        return len(self.peers)

    # =========================================================================
    # DISCOVERY (HEARTBEAT)
    # =========================================================================

    def on_heartbeat_received(self, sysid: int, compid: int):
        """
        Handle received HEARTBEAT - discover new peers

        Args:
            sysid: Source system ID
            compid: Source component ID
        """
        # Ignore our own heartbeat
        if sysid == self.my_sysid and compid == self.my_compid:
            return

        peer = self.find_peer(sysid, compid)

        if peer is None:
            # New peer detected
            self._log(f"New peer detected: sysid={sysid} compid={compid}")
            peer = self.add_peer(sysid, compid)

            if peer is not None:
                # Initiate key exchange automatically
                self.initiate_exchange(sysid, compid)
        else:
            # Known peer, update activity timestamp
            peer.last_activity = time.time()

    # =========================================================================
    # EXCHANGE INITIATION
    # =========================================================================

    def initiate_exchange(self, peer_sysid: int, peer_compid: int) -> bool:
        """
        Initiate key exchange with a peer

        Args:
            peer_sysid: Target system ID
            peer_compid: Target component ID

        Returns:
            True if exchange initiated successfully
        """
        if self._my_wk_public is None:
            self._log("ERROR: WK not initialized")
            return False

        peer = self.find_peer(peer_sysid, peer_compid)
        if peer is None:
            peer = self.add_peer(peer_sysid, peer_compid)
            if peer is None:
                return False

        # Send our WK public
        if self._send_wk_exchange(peer_sysid, peer_compid):
            peer.state = ExchangeState.WK_SENT
            peer.last_activity = time.time()
            return True

        return False

    def initiate_exchange_all_peers(self) -> int:
        """
        Initiate exchange with all known peers

        Returns:
            Number of exchanges initiated
        """
        count = 0
        for peer in self.peers.values():
            if peer.state == ExchangeState.IDLE:
                if self.initiate_exchange(peer.sysid, peer.compid):
                    count += 1
        return count

    # =========================================================================
    # MESSAGE SENDING
    # =========================================================================

    def _send_wk_exchange(self, target_sysid: int, target_compid: int) -> bool:
        """Send HSM_WK_EXCHANGE message"""
        if self._send_callback is None:
            self._log("ERROR: No send callback set")
            return False

        if self._my_wk_public is None:
            return False

        timestamp = int(time.time())

        # Pack payload: target_system(1) + target_component(1) + wk_public(64) + timestamp(4)
        payload = struct.pack('<BB', target_sysid, target_compid)
        payload += self._my_wk_public
        payload += struct.pack('<I', timestamp)

        self._send_callback(MAVLINK_MSG_ID_HSM_WK_EXCHANGE, target_sysid, target_compid, payload)
        self._log(f"WK_EXCHANGE sent to sysid={target_sysid}")
        return True

    def _send_dek_exchange(self, peer: PeerInfo) -> bool:
        """Send HSM_DEK_EXCHANGE message with ECIES encrypted DEK"""
        if self._send_callback is None:
            return False

        if peer.wk_public is None:
            self._log("ERROR: Peer WK not received yet")
            return False

        # Get our DEK
        my_dek = self.hsm.get_my_dek()
        if my_dek is None:
            self._log("ERROR: DEK not available")
            return False

        # Encrypt DEK with ECIES
        try:
            ephemeral_pub, encrypted_dek, nonce, tag = ECIES.encrypt_dek(
                peer.wk_public, my_dek
            )
        except Exception as e:
            self._log(f"ERROR: ECIES encryption failed: {e}")
            return False

        # Pack payload
        payload = struct.pack('<BB', peer.sysid, peer.compid)
        payload += ephemeral_pub      # 64 bytes
        payload += encrypted_dek      # 32 bytes
        payload += nonce              # 12 bytes
        payload += tag                # 16 bytes

        self._send_callback(MAVLINK_MSG_ID_HSM_DEK_EXCHANGE, peer.sysid, peer.compid, payload)
        self._log(f"DEK_EXCHANGE sent to sysid={peer.sysid}")
        return True

    def _send_key_ack(self, target_sysid: int, target_compid: int,
                      status: AckStatus, phase: AckPhase) -> bool:
        """Send HSM_KEY_ACK message"""
        if self._send_callback is None:
            return False

        payload = struct.pack('<BBBB',
                              target_sysid, target_compid,
                              status.value, phase.value)

        self._send_callback(MAVLINK_MSG_ID_HSM_KEY_ACK, target_sysid, target_compid, payload)
        self._log(f"KEY_ACK sent: status={status.name} phase={phase.name}")
        return True

    # =========================================================================
    # MESSAGE HANDLERS
    # =========================================================================

    def handle_wk_exchange(self, src_sysid: int, src_compid: int,
                           wk_pub: bytes, timestamp: int):
        """
        Handle received HSM_WK_EXCHANGE message

        Args:
            src_sysid: Source system ID
            src_compid: Source component ID
            wk_pub: Wrapper Key public (64 bytes)
            timestamp: Unix timestamp
        """
        peer = self.find_peer(src_sysid, src_compid)
        if peer is None:
            peer = self.add_peer(src_sysid, src_compid)

        if peer is None:
            return

        # Store peer's WK public
        peer.wk_public = wk_pub
        peer.wk_received = True
        peer.last_activity = time.time()

        self._log(f"WK_EXCHANGE received from sysid={src_sysid}: {wk_pub[:8].hex()}...")

        # If we haven't sent our WK yet, send it
        if peer.state == ExchangeState.IDLE:
            self._send_wk_exchange(src_sysid, src_compid)
            peer.state = ExchangeState.WK_SENT

        # If WK exchanged both ways, proceed to DEK
        if peer.state == ExchangeState.WK_SENT and peer.wk_received:
            peer.state = ExchangeState.WK_RECEIVED
            self._send_dek_exchange(peer)
            peer.state = ExchangeState.DEK_SENT

        # Send ACK
        self._send_key_ack(src_sysid, src_compid, AckStatus.SUCCESS, AckPhase.WK_RECEIVED)

    def handle_dek_exchange(self, src_sysid: int, src_compid: int,
                            ephemeral_pub: bytes, encrypted_dek: bytes,
                            nonce: bytes, tag: bytes):
        """
        Handle received HSM_DEK_EXCHANGE message

        Args:
            src_sysid: Source system ID
            src_compid: Source component ID
            ephemeral_pub: ECIES ephemeral public key (64 bytes)
            encrypted_dek: Encrypted DEK (32 bytes)
            nonce: ChaCha20 nonce (12 bytes)
            tag: Poly1305 tag (16 bytes)
        """
        peer = self.find_peer(src_sysid, src_compid)
        if peer is None:
            self._log(f"ERROR: DEK from unknown peer sysid={src_sysid}")
            return

        # Decrypt peer's DEK
        if self._my_wk_private is None:
            self._log("ERROR: WK private not available")
            self._send_key_ack(src_sysid, src_compid, AckStatus.DEK_ERROR, AckPhase.DEK_RECEIVED)
            return

        try:
            decrypted_dek = ECIES.decrypt_dek(
                self._my_wk_private,
                ephemeral_pub,
                encrypted_dek,
                nonce,
                tag
            )
        except Exception as e:
            self._log(f"ERROR: ECIES decryption failed: {e}")
            self._send_key_ack(src_sysid, src_compid, AckStatus.DEK_ERROR, AckPhase.DEK_RECEIVED)
            return

        if decrypted_dek is None:
            self._log("ERROR: DEK decryption failed (auth error)")
            self._send_key_ack(src_sysid, src_compid, AckStatus.DEK_ERROR, AckPhase.DEK_RECEIVED)
            return

        # Store peer's DEK
        peer.dek = decrypted_dek
        peer.dek_received = True
        peer.last_activity = time.time()

        self._log(f"DEK received from sysid={src_sysid}: {decrypted_dek[:4].hex()}...")

        # Store in HSM for later use
        self.hsm.store_peer_dek(src_sysid, decrypted_dek)

        # Check if exchange complete
        if peer.state == ExchangeState.DEK_SENT and peer.dek_received:
            peer.state = ExchangeState.COMPLETE
            self._log(f"Exchange COMPLETE with sysid={src_sysid}")

        # Send ACK
        self._send_key_ack(src_sysid, src_compid, AckStatus.SUCCESS, AckPhase.DEK_RECEIVED)

    def handle_key_ack(self, src_sysid: int, src_compid: int,
                       status: int, phase: int):
        """
        Handle received HSM_KEY_ACK message

        Args:
            src_sysid: Source system ID
            src_compid: Source component ID
            status: ACK status code
            phase: ACK phase code
        """
        peer = self.find_peer(src_sysid, src_compid)
        if peer is None:
            return

        peer.last_activity = time.time()

        status_name = AckStatus(status).name if status < 4 else f"UNKNOWN({status})"
        phase_name = AckPhase(phase).name if 0 < phase < 4 else f"UNKNOWN({phase})"

        self._log(f"KEY_ACK from sysid={src_sysid}: status={status_name} phase={phase_name}")

        if status != AckStatus.SUCCESS.value:
            self._log(f"WARNING: Peer reported error: {status_name}")
            peer.state = ExchangeState.ERROR

    # =========================================================================
    # TIMEOUT MANAGEMENT
    # =========================================================================

    def check_timeouts(self):
        """Check for timed out exchanges"""
        now = time.time()
        for peer in self.peers.values():
            if peer.state not in [ExchangeState.IDLE, ExchangeState.COMPLETE, ExchangeState.ERROR]:
                if (now - peer.last_activity) > self.EXCHANGE_TIMEOUT_S:
                    self._log(f"TIMEOUT: Exchange with sysid={peer.sysid}")
                    peer.state = ExchangeState.ERROR

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> dict:
        """Get protocol status"""
        peers_status = []
        for peer in self.peers.values():
            peers_status.append({
                'sysid': peer.sysid,
                'compid': peer.compid,
                'state': peer.state.name,
                'wk_received': peer.wk_received,
                'dek_received': peer.dek_received
            })

        return {
            'my_sysid': self.my_sysid,
            'my_compid': self.my_compid,
            'wk_public_ready': self._my_wk_public is not None,
            'num_peers': len(self.peers),
            'peers': peers_status
        }

    def is_exchange_complete(self, sysid: int, compid: int) -> bool:
        """Check if exchange with peer is complete"""
        peer = self.find_peer(sysid, compid)
        return peer is not None and peer.state == ExchangeState.COMPLETE

    def get_peer_dek(self, sysid: int, compid: int) -> Optional[bytes]:
        """Get DEK for a peer"""
        peer = self.find_peer(sysid, compid)
        return peer.dek if peer else None


# =============================================================================
# TEST
# =============================================================================

def test_key_exchange_loopback():
    """Test key exchange between two simulated endpoints"""
    print("=" * 60)
    print("  Key Exchange Protocol - Loopback Test")
    print("=" * 60)

    if not CRYPTO_AVAILABLE:
        print("SKIP: cryptography library not available")
        return False

    # Create two simulated HSMs
    print("\n1. Creating simulated HSMs...")

    # Simulated HSM for GCS
    class MockHSM:
        def __init__(self, name):
            self.name = name
            self.wk_state = KeyState.LOADED
            self.dek_state = KeyState.LOADED
            self._wk_private, wk_pub = ECIES.generate_keypair()
            self._my_dek = os.urandom(32)
            self._peer_deks = {}

        def get_my_dek(self):
            return self._my_dek

        def store_peer_dek(self, sysid, dek):
            self._peer_deks[sysid] = dek
            print(f"   [{self.name}] Stored peer DEK for sysid={sysid}")

    import os
    hsm_gcs = MockHSM("GCS")
    hsm_drone = MockHSM("DRONE")

    print(f"   GCS DEK:   {hsm_gcs._my_dek[:4].hex()}...")
    print(f"   Drone DEK: {hsm_drone._my_dek[:4].hex()}...")

    # Create protocols
    print("\n2. Creating Key Exchange Protocols...")
    kep_gcs = KeyExchangeProtocol(hsm_gcs, my_sysid=255, my_compid=0)
    kep_drone = KeyExchangeProtocol(hsm_drone, my_sysid=1, my_compid=1)

    # Message queues for simulation
    gcs_to_drone = []
    drone_to_gcs = []

    def gcs_send(msg_id, target_sysid, target_compid, payload):
        gcs_to_drone.append((msg_id, 255, 0, payload))

    def drone_send(msg_id, target_sysid, target_compid, payload):
        drone_to_gcs.append((msg_id, 1, 1, payload))

    kep_gcs.set_send_callback(gcs_send)
    kep_drone.set_send_callback(drone_send)

    # Simulate HEARTBEAT discovery
    print("\n3. Simulating HEARTBEAT discovery...")
    kep_gcs.on_heartbeat_received(1, 1)  # GCS sees drone

    # Process messages back and forth
    print("\n4. Processing message exchange...")
    max_iterations = 10
    for i in range(max_iterations):
        # Process GCS → Drone messages
        while gcs_to_drone:
            msg_id, src_sysid, src_compid, payload = gcs_to_drone.pop(0)
            if msg_id == MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
                wk_pub = payload[2:66]
                timestamp = struct.unpack('<I', payload[66:70])[0]
                kep_drone.handle_wk_exchange(src_sysid, src_compid, wk_pub, timestamp)
            elif msg_id == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
                ephemeral_pub = payload[2:66]
                encrypted_dek = payload[66:98]
                nonce = payload[98:110]
                tag = payload[110:126]
                kep_drone.handle_dek_exchange(src_sysid, src_compid, ephemeral_pub, encrypted_dek, nonce, tag)
            elif msg_id == MAVLINK_MSG_ID_HSM_KEY_ACK:
                status, phase = payload[2], payload[3]
                kep_drone.handle_key_ack(src_sysid, src_compid, status, phase)

        # Process Drone → GCS messages
        while drone_to_gcs:
            msg_id, src_sysid, src_compid, payload = drone_to_gcs.pop(0)
            if msg_id == MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
                wk_pub = payload[2:66]
                timestamp = struct.unpack('<I', payload[66:70])[0]
                kep_gcs.handle_wk_exchange(src_sysid, src_compid, wk_pub, timestamp)
            elif msg_id == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
                ephemeral_pub = payload[2:66]
                encrypted_dek = payload[66:98]
                nonce = payload[98:110]
                tag = payload[110:126]
                kep_gcs.handle_dek_exchange(src_sysid, src_compid, ephemeral_pub, encrypted_dek, nonce, tag)
            elif msg_id == MAVLINK_MSG_ID_HSM_KEY_ACK:
                status, phase = payload[2], payload[3]
                kep_gcs.handle_key_ack(src_sysid, src_compid, status, phase)

        # Check if complete
        if kep_gcs.is_exchange_complete(1, 1) and kep_drone.is_exchange_complete(255, 0):
            print(f"   Exchange complete after {i+1} iterations")
            break

    # Verify results
    print("\n5. Verification...")

    gcs_status = kep_gcs.get_status()
    drone_status = kep_drone.get_status()

    print(f"   GCS status: {gcs_status['peers']}")
    print(f"   Drone status: {drone_status['peers']}")

    # Verify DEKs were exchanged correctly
    gcs_has_drone_dek = 1 in hsm_gcs._peer_deks
    drone_has_gcs_dek = 255 in hsm_drone._peer_deks

    print(f"\n   GCS has Drone DEK: {gcs_has_drone_dek}")
    print(f"   Drone has GCS DEK: {drone_has_gcs_dek}")

    if gcs_has_drone_dek and drone_has_gcs_dek:
        # Verify DEKs match originals
        gcs_got_drone_dek = hsm_gcs._peer_deks[1]
        drone_got_gcs_dek = hsm_drone._peer_deks[255]

        dek_match = (gcs_got_drone_dek == hsm_drone._my_dek and
                     drone_got_gcs_dek == hsm_gcs._my_dek)

        if dek_match:
            print("\n*** TEST PASSED: DEKs exchanged correctly! ***")
            return True
        else:
            print("\n*** TEST FAILED: DEK mismatch! ***")
            return False
    else:
        print("\n*** TEST FAILED: DEKs not exchanged! ***")
        return False


if __name__ == '__main__':
    success = test_key_exchange_loopback()
    exit(0 if success else 1)
