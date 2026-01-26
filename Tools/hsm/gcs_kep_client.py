#!/usr/bin/env python3
"""
GCS Key Exchange Protocol Client

Ce script connecte le GCS au drone via MAVLink et gere l'echange de cles HSM:
1. Initialise le HSM local (GCS)
2. Se connecte au drone via MAVLink
3. Ecoute les messages HSM_WK_EXCHANGE et HSM_DEK_EXCHANGE
4. Repond automatiquement avec ses propres cles

Usage:
    python3 gcs_kep_client.py --mavlink tcp:127.0.0.1:5760 --hsm /dev/ttyUSB0

Date: 2026-01-25
"""

import sys
import os
import time
import struct
import argparse
from threading import Thread

# ChaCha20 for payload decryption (Feature 3)
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    CHACHA20_AVAILABLE = True
except ImportError:
    CHACHA20_AVAILABLE = False
    print("WARNING: cryptography not available for ChaCha20 decryption")

# Add current directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    from gcs_hsm import GCS_HSM, KeyState
    from key_exchange_protocol import KeyExchangeProtocol, MAVLINK_MSG_ID_HSM_WK_EXCHANGE, \
        MAVLINK_MSG_ID_HSM_DEK_EXCHANGE, MAVLINK_MSG_ID_HSM_KEY_ACK
    from dual_dek_engine import DualDekEngine
except ImportError as e:
    print(f"ERROR: Cannot import HSM modules: {e}")
    sys.exit(1)

# Import our generated MAVLink dialect with HSM messages
MAVLINK_HSM_PATH = os.path.join(SCRIPT_DIR, "mavlink_hsm.py")
if os.path.exists(MAVLINK_HSM_PATH):
    # Use generated dialect
    import importlib.util
    spec = importlib.util.spec_from_file_location("mavlink_hsm", MAVLINK_HSM_PATH)
    mavlink_hsm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mavlink_hsm)
    MAVLink = mavlink_hsm.MAVLink
    MAVLINK_HSM_AVAILABLE = True
    print(f"[INFO] Using generated MAVLink dialect: {MAVLINK_HSM_PATH}")
else:
    MAVLINK_HSM_AVAILABLE = False
    MAVLink = None

# Try to import pymavlink for connection handling
try:
    from pymavlink import mavutil
    # IMPORTANT: Replace mavutil's mavlink module with our HSM dialect
    # This makes recv_match() parse HSM messages correctly
    if MAVLINK_HSM_AVAILABLE:
        mavutil.mavlink = mavlink_hsm
        print("[INFO] Replaced mavutil.mavlink with HSM dialect for parsing")
    PYMAVLINK_AVAILABLE = True
except ImportError:
    PYMAVLINK_AVAILABLE = False
    print("WARNING: pymavlink not available")


def log(msg: str, level: str = "INFO"):
    """Log with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}", flush=True)


def chacha20_decrypt(key: bytes, nonce_12: bytes, ciphertext: bytes, counter: int = 0) -> bytes:
    """
    Decrypt using ChaCha20 with 12-byte nonce (RFC 7539 style)

    Args:
        key: 32-byte encryption key
        nonce_12: 12-byte nonce
        ciphertext: Encrypted data
        counter: Block counter (default 0)

    Returns:
        Decrypted plaintext
    """
    if not CHACHA20_AVAILABLE:
        return None

    # cryptography library wants: counter(4 bytes LE) + nonce(12 bytes) = 16 bytes
    nonce_16 = counter.to_bytes(4, 'little') + nonce_12

    cipher = Cipher(algorithms.ChaCha20(key, nonce_16), mode=None)
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext)


def parse_mavlink_message(raw_bytes: bytes) -> dict:
    """
    Parse a MAVLink v2 message from raw bytes

    Returns dict with: stx, len, seq, sysid, compid, msgid, payload, crc
    """
    if len(raw_bytes) < 12 or raw_bytes[0] != 0xFD:
        return None

    result = {
        'stx': raw_bytes[0],
        'len': raw_bytes[1],
        'incompat': raw_bytes[2],
        'compat': raw_bytes[3],
        'seq': raw_bytes[4],
        'sysid': raw_bytes[5],
        'compid': raw_bytes[6],
        'msgid': raw_bytes[7] | (raw_bytes[8] << 8) | (raw_bytes[9] << 16),
        'payload': raw_bytes[10:10+raw_bytes[1]] if len(raw_bytes) >= 10+raw_bytes[1] else b'',
        'crc': raw_bytes[10+raw_bytes[1]:12+raw_bytes[1]] if len(raw_bytes) >= 12+raw_bytes[1] else b'',
    }
    return result


def build_nonce_12(seq: int, sysid: int, compid: int, msgid: int, chan: int = 0, direction: int = 0) -> bytes:
    """
    Build 12-byte deterministic nonce for ChaCha20 (matches C++ implementation)

    Format: seq(1) + sysid(1) + compid(1) + msgid(3) + chan(1) + dir(1) + padding(4)
    """
    nonce = bytes([
        seq & 0xFF,
        sysid & 0xFF,
        compid & 0xFF,
        (msgid >> 0) & 0xFF,
        (msgid >> 8) & 0xFF,
        (msgid >> 16) & 0xFF,
        chan & 0xFF,
        direction & 0xFF,  # TX=0, RX=1
        0x00, 0x00, 0x00, 0x00
    ])
    return nonce


# MAVLink message names (subset for display)
MAVLINK_MSG_NAMES = {
    0: "HEARTBEAT",
    1: "SYS_STATUS",
    24: "GPS_RAW_INT",
    30: "ATTITUDE",
    33: "GLOBAL_POSITION_INT",
    35: "RC_CHANNELS_RAW",
    65: "RC_CHANNELS",
    74: "VFR_HUD",
    76: "COMMAND_LONG",
    77: "COMMAND_ACK",
    147: "BATTERY_STATUS",
    253: "STATUSTEXT",
    12000: "HSM_WK_EXCHANGE",
    12001: "HSM_DEK_EXCHANGE",
    12002: "HSM_KEY_ACK",
}


class MockHSM:
    """
    Mock HSM for testing without physical HSM.
    Generates keys in memory using software crypto.
    """
    def __init__(self):
        import os
        try:
            from ecies import ECIES
            self._wk_private, self._wk_public = ECIES.generate_keypair()
        except ImportError:
            # Fallback: generate random keys (won't work for real crypto)
            self._wk_private = os.urandom(32)
            self._wk_public = os.urandom(64)

        self._my_dek = os.urandom(32)
        self._peer_deks = {}

        self.mk_state = KeyState.LOADED
        self.wk_state = KeyState.LOADED
        self.dek_state = KeyState.LOADED
        self.init_time_ms = 0

    def get_my_dek(self):
        return self._my_dek

    def store_peer_dek(self, sysid, dek):
        self._peer_deks[sysid] = dek
        log(f"MockHSM: Stored peer DEK for sysid={sysid}")

    def disconnect(self):
        pass


class GCSKeyExchangeClient:
    """
    GCS client for HSM Key Exchange Protocol over MAVLink
    """

    def __init__(self, mavlink_connection: str, hsm_port: str = '/dev/ttyUSB0',
                 gcs_sysid: int = 255, gcs_compid: int = 190, verbose: bool = False):
        """
        Initialize GCS KEP Client

        Args:
            mavlink_connection: MAVLink connection string (e.g., 'tcp:127.0.0.1:5760')
            hsm_port: HSM serial port
            gcs_sysid: GCS system ID (default 255)
            gcs_compid: GCS component ID (default 190 = MAV_COMP_ID_MISSIONPLANNER)
            verbose: Enable verbose logging of encrypted/decrypted payloads
        """
        self.mavlink_connection_str = mavlink_connection
        self.hsm_port = hsm_port
        self.gcs_sysid = gcs_sysid
        self.gcs_compid = gcs_compid
        self.verbose = verbose

        self.mav = None
        self.hsm = None
        self.kep = None
        self.dde = None  # Feature 3: DualDekEngine

        self.running = False
        self.exchange_complete = False

        # Statistics for encrypted message handling
        self._crypto_stats = {
            'encrypted_received': 0,
            'decrypted_ok': 0,
            'decrypted_fail': 0,
        }

    def _log(self, msg: str, level: str = "INFO"):
        log(msg, level)

    def init_hsm(self, force_new: bool = False, no_hsm: bool = False) -> bool:
        """Initialize HSM and generate/load keys"""

        if no_hsm:
            # Mode sans HSM physique - génère les clés en mémoire
            self._log("Mode NO-HSM: Generating keys in memory...")
            self.hsm = MockHSM()
            self._log(f"  MK: LOADED (simulated)")
            self._log(f"  WK: LOADED (simulated)")
            self._log(f"  DEK: LOADED (simulated)")
            return True

        self._log("Initializing HSM...")

        self.hsm = GCS_HSM(port=self.hsm_port)

        if not self.hsm.connect():
            self._log("Failed to connect to HSM", "ERROR")
            return False

        # Initialize mission keys
        self._log("Generating/loading mission keys (~25s)...")
        if not self.hsm.init_mission_keys(force_new=force_new):
            self._log("Failed to initialize mission keys", "ERROR")
            return False

        self._log(f"HSM initialized in {self.hsm.init_time_ms}ms")
        self._log(f"  MK: {'LOADED' if self.hsm.mk_state == KeyState.LOADED else 'ERROR'}")
        self._log(f"  WK: {'LOADED' if self.hsm.wk_state == KeyState.LOADED else 'ERROR'}")
        self._log(f"  DEK: {'LOADED' if self.hsm.dek_state == KeyState.LOADED else 'ERROR'}")

        return True

    def init_mavlink(self, trigger_hsm_init: bool = True) -> bool:
        """Initialize MAVLink connection

        Args:
            trigger_hsm_init: If True (SITL mode), use longer timeout for HSM init
        """
        self._log(f"Connecting to MAVLink: {self.mavlink_connection_str}")

        # In SITL mode, first connection triggers HSM init which blocks ~25s
        # We use longer timeouts to wait for init to complete
        heartbeat_timeout = 60 if trigger_hsm_init else 30
        if trigger_hsm_init:
            self._log("SITL mode: Connection will trigger HSM init (~25s blocking)")

        try:
            self.mav = mavutil.mavlink_connection(
                self.mavlink_connection_str,
                source_system=self.gcs_sysid,
                source_component=self.gcs_compid
            )
        except Exception as e:
            self._log(f"MAVLink connection failed: {e}", "ERROR")
            return False

        # Replace the MAVLink instance with our custom one that has HSM messages
        if MAVLINK_HSM_AVAILABLE and MAVLink is not None:
            self._log("Replacing MAVLink with HSM dialect...")
            # Create new MAVLink instance with our dialect
            self.mav_hsm = MAVLink(self.mav, srcSystem=self.gcs_sysid, srcComponent=self.gcs_compid)
        else:
            self.mav_hsm = None
            self._log("WARNING: HSM dialect not available, custom messages may fail", "WARN")

        self._log(f"Waiting for heartbeat (timeout={heartbeat_timeout}s)...")
        self._log("  (HSM init takes ~25s, please wait...)")
        msg = self.mav.wait_heartbeat(timeout=heartbeat_timeout)
        if msg is None:
            self._log("No heartbeat received (timeout)", "ERROR")
            self._log("Check SITL log for HSM init errors", "INFO")
            return False

        self._log(f"Connected to system {self.mav.target_system} component {self.mav.target_component}")
        return True

    def init_kep(self) -> bool:
        """Initialize Key Exchange Protocol"""
        if self.hsm is None:
            self._log("HSM not initialized", "ERROR")
            return False

        self.kep = KeyExchangeProtocol(
            self.hsm,
            my_sysid=self.gcs_sysid,
            my_compid=self.gcs_compid
        )

        # Set send callback
        self.kep.set_send_callback(self._send_mavlink_msg)

        self._log("KEP initialized")
        return True

    def _init_dual_dek_engine(self, peer_sysid: int):
        """Initialize DualDekEngine after key exchange is complete"""
        if self.hsm is None:
            self._log("Cannot init DDE: HSM not initialized", "ERROR")
            return

        try:
            # Get our DEK
            my_dek = self.hsm.get_my_dek()
            if my_dek is None:
                self._log("Cannot init DDE: MY_DEK not available", "ERROR")
                return

            # Initialize DualDekEngine
            self.dde = DualDekEngine(my_dek=my_dek)

            # Get peer DEK from HSM
            peer_dek = self.hsm._peer_deks.get(peer_sysid)
            if peer_dek is not None:
                self.dde.set_peer_dek(peer_sysid, peer_dek)
                self._log(f"DDE initialized with peer sysid={peer_sysid}")
                self._log(f"  MY_DEK: {my_dek[:4].hex()}...")
                self._log(f"  PEER_DEK[{peer_sysid}]: {peer_dek[:4].hex()}...")
            else:
                self._log(f"WARNING: No peer DEK for sysid={peer_sysid}", "WARN")

            self.dde.print_status()

        except Exception as e:
            self._log(f"DDE init failed: {e}", "ERROR")

    def _send_mavlink_msg(self, msg_id: int, target_sysid: int, target_compid: int, payload: bytes):
        """Send custom MAVLink message using HSM dialect"""
        if self.mav is None:
            return

        if msg_id == MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
            # HSM_WK_EXCHANGE: target_system, target_component, wk_public[64], timestamp
            wk_public = list(payload[2:66])
            timestamp = struct.unpack('<I', payload[66:70])[0]

            self._log(f"Sending HSM_WK_EXCHANGE to {target_sysid} wk={bytes(wk_public[:4]).hex()}...")

            if self.mav_hsm:
                # Use our custom MAVLink with HSM messages
                try:
                    msg = self.mav_hsm.hsm_wk_exchange_encode(
                        target_sysid,
                        target_compid,
                        wk_public,
                        timestamp
                    )
                    self.mav.write(msg.pack(self.mav_hsm))
                    self._log(f"  ✓ HSM_WK_EXCHANGE sent ({len(msg.pack(self.mav_hsm))} bytes)")
                    return
                except Exception as e:
                    self._log(f"  ERROR encoding message: {e}", "ERROR")

            # Fallback
            self._send_raw_hsm_message(msg_id, payload)

        elif msg_id == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
            # HSM_DEK_EXCHANGE: target_system, target_component, ephemeral_pub[64], encrypted_dek[32], nonce[24], tag[16]
            # Note: nonce is 24 bytes for XChaCha20-Poly1305 (Monocypher)
            ephemeral_pub = list(payload[2:66])
            encrypted_dek = list(payload[66:98])
            nonce = list(payload[98:122])  # 24 bytes for XChaCha20
            tag = list(payload[122:138])

            self._log(f"Sending HSM_DEK_EXCHANGE to {target_sysid}")

            if self.mav_hsm:
                try:
                    msg = self.mav_hsm.hsm_dek_exchange_encode(
                        target_sysid,
                        target_compid,
                        ephemeral_pub,
                        encrypted_dek,
                        nonce,
                        tag
                    )
                    self.mav.write(msg.pack(self.mav_hsm))
                    self._log(f"  ✓ HSM_DEK_EXCHANGE sent ({len(msg.pack(self.mav_hsm))} bytes)")
                    return
                except Exception as e:
                    self._log(f"  ERROR encoding message: {e}", "ERROR")

            self._send_raw_hsm_message(msg_id, payload)

        elif msg_id == MAVLINK_MSG_ID_HSM_KEY_ACK:
            # HSM_KEY_ACK: target_system, target_component, status, phase
            status = payload[2]
            phase = payload[3]

            self._log(f"Sending HSM_KEY_ACK to {target_sysid}: status={status} phase={phase}")

            if self.mav_hsm:
                try:
                    msg = self.mav_hsm.hsm_key_ack_encode(
                        target_sysid,
                        target_compid,
                        status,
                        phase
                    )
                    self.mav.write(msg.pack(self.mav_hsm))
                    self._log(f"  ✓ HSM_KEY_ACK sent")
                    return
                except Exception as e:
                    self._log(f"  ERROR encoding message: {e}", "ERROR")

            self._send_raw_hsm_message(msg_id, payload)

    def _send_raw_hsm_message(self, msg_id: int, payload: bytes):
        """Send raw HSM message (fallback if pymavlink doesn't have the message)"""
        self._log(f"Sending raw message ID {msg_id} ({len(payload)} bytes)", "DEBUG")
        # This would need mavlink_connection.write() with properly formatted packet
        # For now, log warning
        self._log("WARNING: Raw message sending not implemented", "WARN")

    def _send_heartbeat(self):
        """Send a heartbeat message to announce our presence"""
        try:
            # GCS type: MAV_TYPE_GCS = 6
            # Autopilot: MAV_AUTOPILOT_INVALID = 8 (for GCS)
            # Base mode: 0
            # Custom mode: 0
            # System status: MAV_STATE_ACTIVE = 4
            self.mav.mav.heartbeat_send(
                6,   # type: MAV_TYPE_GCS
                8,   # autopilot: MAV_AUTOPILOT_INVALID
                0,   # base_mode
                0,   # custom_mode
                4    # system_status: MAV_STATE_ACTIVE
            )
        except Exception as e:
            self._log(f"Failed to send heartbeat: {e}", "DEBUG")

    def handle_message(self, msg):
        """Handle incoming MAVLink message"""
        msg_type = msg.get_type()

        # Debug: log all message types
        if msg_type not in ['HEARTBEAT', 'GLOBAL_POSITION_INT', 'ATTITUDE', 'SYS_STATUS',
                             'VFR_HUD', 'RAW_IMU', 'SCALED_IMU2', 'SCALED_PRESSURE',
                             'GPS_RAW_INT', 'RC_CHANNELS', 'SERVO_OUTPUT_RAW',
                             'BATTERY_STATUS', 'MISSION_CURRENT', 'NAV_CONTROLLER_OUTPUT',
                             'TERRAIN_REPORT', 'EKF_STATUS_REPORT', 'VIBRATION', 'AHRS',
                             'AHRS2', 'AHRS3', 'SIMSTATE', 'HWSTATUS', 'POWER_STATUS',
                             'MEMINFO', 'MCU_STATUS', 'SYSTEM_TIME', 'TIMESYNC',
                             'LOCAL_POSITION_NED', 'POSITION_TARGET_GLOBAL_INT',
                             'HOME_POSITION', 'ESTIMATOR_STATUS', 'WIND', 'SENSOR_OFFSETS']:
            self._log(f"[DEBUG] Message type: {msg_type} from sysid={msg.get_srcSystem()}")

        if msg_type == 'HEARTBEAT':
            # Notify KEP about heartbeat
            if self.kep:
                self.kep.on_heartbeat_received(msg.get_srcSystem(), msg.get_srcComponent())

        elif msg_type == 'HSM_WK_EXCHANGE':
            self._log(f">>> Received HSM_WK_EXCHANGE from sysid={msg.get_srcSystem()}")
            if self.kep:
                wk_pub = bytes(msg.wk_public)
                self._log(f"    WK public: {wk_pub[:4].hex()}...")
                self.kep.handle_wk_exchange(
                    msg.get_srcSystem(),
                    msg.get_srcComponent(),
                    wk_pub,
                    msg.timestamp
                )

        elif msg_type == 'HSM_DEK_EXCHANGE':
            self._log(f">>> Received HSM_DEK_EXCHANGE from sysid={msg.get_srcSystem()}")
            if self.kep:
                self.kep.handle_dek_exchange(
                    msg.get_srcSystem(),
                    msg.get_srcComponent(),
                    bytes(msg.ephemeral_pubkey),
                    bytes(msg.encrypted_dek),
                    bytes(msg.nonce),
                    bytes(msg.auth_tag)
                )

                # Check if exchange complete
                if self.kep.is_exchange_complete(msg.get_srcSystem(), msg.get_srcComponent()):
                    self._log("=" * 50)
                    self._log("✓ KEY EXCHANGE COMPLETE!")
                    self._log("=" * 50)
                    self.exchange_complete = True
                    self._init_dual_dek_engine(msg.get_srcSystem())

        elif msg_type == 'STATUSTEXT':
            # Display status text from Pixhawk (debug logs)
            try:
                severity = msg.severity
                text = msg.text.rstrip('\x00')
                sev_names = {0: 'EMERG', 1: 'ALERT', 2: 'CRIT', 3: 'ERR', 4: 'WARN', 5: 'NOTICE', 6: 'INFO', 7: 'DEBUG'}
                self._log(f"[STATUSTEXT] [{sev_names.get(severity, severity)}] {text}")
            except Exception as e:
                self._log(f"[STATUSTEXT] (parse error: {e})")

        elif msg_type == 'HSM_KEY_ACK':
            self._log(f">>> Received HSM_KEY_ACK from sysid={msg.get_srcSystem()}")
            if self.kep:
                self.kep.handle_key_ack(
                    msg.get_srcSystem(),
                    msg.get_srcComponent(),
                    msg.status,
                    msg.phase
                )

        # Handle UNKNOWN messages (HSM custom messages not in pymavlink)
        elif msg_type.startswith('UNKNOWN_'):
            try:
                msg_id = int(msg_type.split('_')[1])
                self._handle_unknown_hsm_message(msg, msg_id)
            except (ValueError, IndexError):
                pass

        # Handle unknown message IDs (might be HSM messages not parsed by default)
        elif msg_type == 'BAD_DATA':
            # Try to parse as HSM message first
            self._parse_raw_hsm_message(msg)
            # Then try to decrypt as encrypted MAVLink message
            self._try_decrypt_message(msg)

    def _handle_unknown_hsm_message(self, msg, msg_id: int):
        """Handle UNKNOWN_* messages which are our custom HSM messages"""
        try:
            # Get raw buffer from message
            raw = None
            for attr in ['_msgbuf', 'msgbuf', '_payload', 'payload']:
                if hasattr(msg, attr):
                    data = getattr(msg, attr)
                    if data is not None:
                        raw = bytes(data)
                        break

            if raw is None or len(raw) < 12:
                attrs = [a for a in dir(msg) if not a.startswith('__')]
                self._log(f"Cannot extract buffer from UNKNOWN_{msg_id}. Attrs: {attrs[:10]}", "WARN")
                return

            # Parse MAVLink v2 header:
            # STX(1) + Len(1) + Incompat(1) + Compat(1) + Seq(1) + SysID(1) + CompID(1) + MsgID(3) = 10 bytes
            # Payload starts at offset 10
            if raw[0] == 0xFD:  # MAVLink v2
                payload_len = raw[1]
                src_sysid = raw[5]
                src_compid = raw[6]
                payload = raw[10:10+payload_len]
            else:
                # MAVLink v1 or unknown format
                self._log(f"Non-v2 message format for UNKNOWN_{msg_id}: 0x{raw[0]:02X}", "WARN")
                return

            if msg_id == MAVLINK_MSG_ID_HSM_WK_EXCHANGE:  # 12000
                self._log(f">>> Received UNKNOWN_12000 (HSM_WK_EXCHANGE) from sysid={src_sysid}")
                self._log(f"    [DEBUG] payload_len={len(payload)}, first 20 bytes: {payload[:20].hex() if len(payload)>=20 else payload.hex()}")
                self._log(f"    [DEBUG] self.kep={self.kep is not None}")
                # MAVLink reorders: timestamp(4) + target_sys(1) + target_comp(1) + wk_public(64) = 70 bytes
                if len(payload) >= 70 and self.kep:
                    try:
                        timestamp = struct.unpack('<I', payload[0:4])[0]
                        target_sys = payload[4]
                        target_comp = payload[5]
                        wk_public = bytes(payload[6:70])   # 64 bytes
                        self._log(f"    target={target_sys},{target_comp} WK: {wk_public[:4].hex()}... ts={timestamp}")
                        self.kep.handle_wk_exchange(src_sysid, src_compid, wk_public, timestamp)
                    except Exception as e:
                        self._log(f"    ERROR parsing WK: {e}", "ERROR")
                else:
                    self._log(f"    [WARN] Cannot parse WK: payload_len={len(payload)}, kep={self.kep is not None}", "WARN")

            elif msg_id == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:  # 12001
                self._log(f">>> Received UNKNOWN_12001 (HSM_DEK_EXCHANGE) from sysid={src_sysid}")
                self._log(f"    [DEBUG] payload_len={len(payload)}, first 20 bytes: {payload[:20].hex()}")
                # Format: target_sys(1) + target_comp(1) + ephemeral(64) + encrypted(32) + nonce(24) + tag(16) = 138 bytes
                # Note: nonce is 24 bytes for XChaCha20-Poly1305 (Monocypher)
                if len(payload) >= 138 and self.kep:
                    target_sys = payload[0]
                    target_comp = payload[1]
                    ephemeral_pub = bytes(payload[2:66])      # 64 bytes
                    encrypted_dek = bytes(payload[66:98])     # 32 bytes
                    nonce = bytes(payload[98:122])            # 24 bytes (XChaCha20)
                    tag = bytes(payload[122:138])             # 16 bytes
                    self._log(f"    target_sys={target_sys} target_comp={target_comp}")
                    self._log(f"    Ephemeral pub: {ephemeral_pub[:8].hex()}...")
                    self._log(f"    Encrypted DEK: {encrypted_dek[:4].hex()}...")
                    self.kep.handle_dek_exchange(src_sysid, src_compid, ephemeral_pub, encrypted_dek, nonce, tag)

                    # Check if exchange complete
                    if self.kep.is_exchange_complete(src_sysid, src_compid):
                        self._log("=" * 50)
                        self._log("✓ KEY EXCHANGE COMPLETE!")
                        self._log("=" * 50)
                        self.exchange_complete = True
                        self._init_dual_dek_engine(src_sysid)

            elif msg_id == MAVLINK_MSG_ID_HSM_KEY_ACK:  # 12002
                self._log(f">>> Received UNKNOWN_12002 (HSM_KEY_ACK) from sysid={src_sysid}")
                # Layout: target_sys(1) + target_comp(1) + status(1) + phase(1) = 4 bytes
                # No reordering needed (all same size)
                if len(payload) >= 4 and self.kep:
                    target_sys = payload[0]
                    target_comp = payload[1]
                    status = payload[2]
                    phase = payload[3]
                    self._log(f"    Status: {status}, Phase: {phase}")
                    self.kep.handle_key_ack(src_sysid, src_compid, status, phase)

        except Exception as e:
            self._log(f"Error handling UNKNOWN_{msg_id}: {e}", "ERROR")

    def _parse_raw_hsm_message(self, msg):
        """Try to parse raw message as HSM message"""
        if not hasattr(msg, '_msgbuf'):
            return

        try:
            # Get raw buffer
            buf = bytes(msg._msgbuf)
            if len(buf) < 10:
                return

            # MAVLink v2 header: STX(1) + len(1) + incompat(1) + compat(1) + seq(1) + sysid(1) + compid(1) + msgid(3)
            if buf[0] == 0xFD:  # MAVLink v2
                msg_id = buf[7] | (buf[8] << 8) | (buf[9] << 16)
                src_sysid = buf[5]
                src_compid = buf[6]
                payload = buf[10:-2]  # Exclude CRC

                if msg_id == MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
                    self._log(f">>> Parsed raw HSM_WK_EXCHANGE from sysid={src_sysid}")
                    if len(payload) >= 70 and self.kep:
                        target_sys = payload[0]
                        target_comp = payload[1]
                        wk_public = bytes(payload[2:66])
                        timestamp = struct.unpack('<I', payload[66:70])[0]
                        self.kep.handle_wk_exchange(src_sysid, src_compid, wk_public, timestamp)

                elif msg_id == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
                    self._log(f">>> Parsed raw HSM_DEK_EXCHANGE from sysid={src_sysid}")
                    # Note: nonce is 24 bytes for XChaCha20-Poly1305 (Monocypher)
                    if len(payload) >= 138 and self.kep:
                        ephemeral_pub = bytes(payload[2:66])
                        encrypted_dek = bytes(payload[66:98])
                        nonce = bytes(payload[98:122])        # 24 bytes (XChaCha20)
                        tag = bytes(payload[122:138])         # 16 bytes
                        self.kep.handle_dek_exchange(src_sysid, src_compid, ephemeral_pub, encrypted_dek, nonce, tag)

                elif msg_id == MAVLINK_MSG_ID_HSM_KEY_ACK:
                    self._log(f">>> Parsed raw HSM_KEY_ACK from sysid={src_sysid}")
                    if len(payload) >= 4 and self.kep:
                        status = payload[2]
                        phase = payload[3]
                        self.kep.handle_key_ack(src_sysid, src_compid, status, phase)

        except Exception as e:
            pass  # Ignore parse errors for non-HSM messages

    def _try_decrypt_message(self, msg):
        """
        Try to decrypt an encrypted MAVLink message (BAD_DATA due to encrypted payload)

        The drone encrypts only the PAYLOAD portion using ChaCha20 with a deterministic nonce.
        This causes CRC check to fail (BAD_DATA) since CRC is computed on encrypted bytes.

        We:
        1. Extract the raw MAVLink frame
        2. Reconstruct the nonce from header fields
        3. Decrypt payload using peer's DEK
        4. Display comparison: encrypted vs decrypted
        """
        if not self.exchange_complete:
            return  # Don't try to decrypt before key exchange

        if not CHACHA20_AVAILABLE:
            return

        # Get raw buffer
        raw = None
        for attr in ['_msgbuf', 'msgbuf', '_payload', 'payload']:
            if hasattr(msg, attr):
                data = getattr(msg, attr)
                if data is not None:
                    raw = bytes(data)
                    break

        if raw is None or len(raw) < 12:
            return

        # Must be MAVLink v2
        if raw[0] != 0xFD:
            return

        # Parse header
        parsed = parse_mavlink_message(raw)
        if parsed is None:
            return

        payload_len = parsed['len']
        src_sysid = parsed['sysid']
        src_compid = parsed['compid']
        msgid = parsed['msgid']
        seq = parsed['seq']
        encrypted_payload = parsed['payload']

        # Skip plaintext messages (HEARTBEAT, HSM_*)
        if msgid in {0, 12000, 12001, 12002}:
            return

        # Get peer's DEK
        peer_dek = None
        if self.hsm and hasattr(self.hsm, '_peer_deks'):
            peer_dek = self.hsm._peer_deks.get(src_sysid)

        if peer_dek is None:
            return  # No DEK for this peer

        self._crypto_stats['encrypted_received'] += 1

        # Reconstruct nonce (must match C++ GCS_MAVLink.cpp)
        # nonce = seq(1) + sysid(1) + compid(1) + msgid(3) + chan(1) + dir(1) + padding(4)
        # Note: chan=0 for TCP, dir=0 for TX (drone's perspective)
        nonce = build_nonce_12(seq, src_sysid, src_compid, msgid, chan=0, direction=0)

        # Decrypt
        try:
            decrypted_payload = chacha20_decrypt(peer_dek, nonce, encrypted_payload, counter=0)

            if decrypted_payload is None:
                self._crypto_stats['decrypted_fail'] += 1
                return

            self._crypto_stats['decrypted_ok'] += 1

            # Get message name
            msg_name = MAVLINK_MSG_NAMES.get(msgid, f"MSG_{msgid}")

            # Log the encrypted vs decrypted comparison
            if self.verbose:
                self._log("=" * 60)
                self._log(f"[CRYPTO] Decrypted message from sysid={src_sysid}")
                self._log(f"  Message: {msg_name} (ID={msgid})")
                self._log(f"  Seq: {seq}")
                self._log(f"  Nonce: {nonce.hex()}")
                self._log(f"  Encrypted ({len(encrypted_payload)} bytes): {encrypted_payload[:16].hex()}...")
                self._log(f"  Decrypted ({len(decrypted_payload)} bytes): {decrypted_payload[:16].hex()}...")

                # Try to interpret the decrypted payload based on message type
                self._interpret_decrypted_payload(msgid, decrypted_payload)

                self._log("=" * 60)
            else:
                # Compact log
                if self._crypto_stats['decrypted_ok'] % 20 == 1:
                    self._log(f"[CRYPTO] Decrypted: {msg_name} seq={seq} ({self._crypto_stats['decrypted_ok']} total)")

        except Exception as e:
            self._crypto_stats['decrypted_fail'] += 1
            if self.verbose:
                self._log(f"[CRYPTO] Decrypt failed: {e}", "ERROR")

    def _interpret_decrypted_payload(self, msgid: int, payload: bytes):
        """Interpret the decrypted payload based on message type"""
        try:
            if msgid == 30:  # ATTITUDE
                if len(payload) >= 28:
                    time_boot_ms = struct.unpack('<I', payload[0:4])[0]
                    roll = struct.unpack('<f', payload[4:8])[0]
                    pitch = struct.unpack('<f', payload[8:12])[0]
                    yaw = struct.unpack('<f', payload[12:16])[0]
                    self._log(f"    → ATTITUDE: roll={roll:.2f} pitch={pitch:.2f} yaw={yaw:.2f}")

            elif msgid == 33:  # GLOBAL_POSITION_INT
                if len(payload) >= 28:
                    time_boot_ms = struct.unpack('<I', payload[0:4])[0]
                    lat = struct.unpack('<i', payload[4:8])[0] / 1e7
                    lon = struct.unpack('<i', payload[8:12])[0] / 1e7
                    alt = struct.unpack('<i', payload[12:16])[0] / 1000.0
                    relative_alt = struct.unpack('<i', payload[16:20])[0] / 1000.0
                    self._log(f"    → POSITION: lat={lat:.6f} lon={lon:.6f} alt={alt:.1f}m rel_alt={relative_alt:.1f}m")

            elif msgid == 1:  # SYS_STATUS
                if len(payload) >= 31:
                    voltage = struct.unpack('<H', payload[14:16])[0] / 1000.0
                    current = struct.unpack('<h', payload[16:18])[0] / 100.0
                    battery = payload[30]
                    self._log(f"    → SYS_STATUS: voltage={voltage:.2f}V current={current:.1f}A battery={battery}%")

            elif msgid == 74:  # VFR_HUD
                if len(payload) >= 20:
                    airspeed = struct.unpack('<f', payload[0:4])[0]
                    groundspeed = struct.unpack('<f', payload[4:8])[0]
                    alt = struct.unpack('<f', payload[8:12])[0]
                    climb = struct.unpack('<f', payload[12:16])[0]
                    heading = struct.unpack('<h', payload[16:18])[0]
                    self._log(f"    → VFR_HUD: airspeed={airspeed:.1f} groundspeed={groundspeed:.1f} alt={alt:.1f}m heading={heading}")

            elif msgid == 77:  # COMMAND_ACK
                if len(payload) >= 3:
                    command = struct.unpack('<H', payload[0:2])[0]
                    result = payload[2]
                    result_names = {0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED", 3: "UNSUPPORTED", 4: "FAILED"}
                    self._log(f"    → COMMAND_ACK: cmd={command} result={result_names.get(result, result)}")

            elif msgid == 253:  # STATUSTEXT
                if len(payload) >= 2:
                    severity = payload[0]
                    text = payload[1:51].rstrip(b'\x00').decode('utf-8', errors='replace')
                    self._log(f"    → STATUSTEXT: [{severity}] {text}")

        except Exception as e:
            self._log(f"    → (parse error: {e})")

    def run(self, timeout: float = 60.0, trigger_hsm_init: bool = True):
        """Run the key exchange client

        Args:
            timeout: Timeout in seconds (0 = infinite)
            trigger_hsm_init: If True, trigger SITL HSM init before connecting
        """
        self._log("Starting GCS KEP Client...")

        # Initialize components
        if not self.init_hsm():
            return False

        if not self.init_mavlink(trigger_hsm_init=trigger_hsm_init):
            return False

        if not self.init_kep():
            return False

        # Send initial heartbeat to announce our presence
        self._send_heartbeat()
        self._log("Sent initial heartbeat to announce GCS")

        self._log("=" * 50)
        self._log("Listening for HSM messages...")
        self._log("=" * 50)

        self.running = True
        start_time = time.time()
        last_heartbeat_time = time.time()

        try:
            while self.running:
                # Check timeout
                if timeout > 0 and (time.time() - start_time) > timeout:
                    self._log("Timeout waiting for exchange", "WARN")
                    break

                # Send periodic heartbeat (every 1 second)
                if time.time() - last_heartbeat_time >= 1.0:
                    self._send_heartbeat()
                    last_heartbeat_time = time.time()

                # Receive message
                msg = self.mav.recv_match(blocking=True, timeout=0.5)
                if msg:
                    self.handle_message(msg)

                # Check if exchange complete (continue listening for encrypted messages)
                if self.exchange_complete and not hasattr(self, '_post_exchange_logged'):
                    self._log("Exchange completed successfully!")
                    self._log("Continuing to listen for encrypted messages...")
                    self._post_exchange_logged = True

                # Check for timeouts
                if self.kep:
                    self.kep.check_timeouts()

        except KeyboardInterrupt:
            self._log("Interrupted by user")
        finally:
            self.running = False

        # Print final status
        self._print_status()

        return self.exchange_complete

    def _print_status(self):
        """Print final status"""
        self._log("")
        self._log("=" * 50)
        self._log("FINAL STATUS")
        self._log("=" * 50)

        if self.kep:
            status = self.kep.get_status()
            self._log(f"GCS sysid: {status['my_sysid']}")
            self._log(f"WK public ready: {status['wk_public_ready']}")
            self._log(f"Peers: {status['num_peers']}")

            for peer in status['peers']:
                self._log(f"  Peer {peer['sysid']}: state={peer['state']} "
                         f"wk_recv={peer['wk_received']} dek_recv={peer['dek_received']}")

        if self.hsm:
            self._log(f"Peer DEKs stored: {len(self.hsm._peer_deks)}")
            for sysid in self.hsm._peer_deks:
                dek = self.hsm._peer_deks[sysid]
                self._log(f"  sysid={sysid}: {dek[:4].hex()}...")

        if self.dde:
            self._log("")
            self._log("DualDekEngine Status:")
            self.dde.print_status()

        # Crypto stats
        self._log("")
        self._log("Crypto Statistics:")
        self._log(f"  Encrypted received: {self._crypto_stats['encrypted_received']}")
        self._log(f"  Decrypted OK: {self._crypto_stats['decrypted_ok']}")
        self._log(f"  Decrypted FAIL: {self._crypto_stats['decrypted_fail']}")

    def stop(self):
        """Stop the client"""
        self.running = False
        if self.hsm:
            self.hsm.disconnect()


def main():
    parser = argparse.ArgumentParser(description='GCS Key Exchange Protocol Client')
    parser.add_argument('--mavlink', '-m', default='tcp:127.0.0.1:5760',
                       help='MAVLink connection string (default: tcp:127.0.0.1:5760)')
    parser.add_argument('--hsm', '-p', default='/dev/ttyUSB0',
                       help='HSM serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--sysid', '-s', type=int, default=255,
                       help='GCS system ID (default: 255)')
    parser.add_argument('--compid', '-c', type=int, default=190,
                       help='GCS component ID (default: 190)')
    parser.add_argument('--timeout', '-t', type=float, default=120.0,
                       help='Timeout in seconds (default: 120, 0=infinite)')
    parser.add_argument('--force-new', '-f', action='store_true',
                       help='Force generation of new keys')
    parser.add_argument('--no-hsm', '-n', action='store_true',
                       help='Run without physical HSM (keys in memory)')
    parser.add_argument('--no-trigger', action='store_true',
                       help='Skip SITL HSM init trigger (use when HSM already initialized)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose logging of encrypted/decrypted payloads')

    args = parser.parse_args()

    if not PYMAVLINK_AVAILABLE:
        print("ERROR: pymavlink is required. Install with: pip install pymavlink")
        sys.exit(1)

    print("=" * 60)
    print("  GCS Key Exchange Protocol Client")
    print("=" * 60)
    print(f"  MAVLink: {args.mavlink}")
    print(f"  HSM Port: {args.hsm}")
    print(f"  GCS ID: sysid={args.sysid} compid={args.compid}")
    print(f"  Verbose: {args.verbose}")
    print("=" * 60)
    print()

    client = GCSKeyExchangeClient(
        mavlink_connection=args.mavlink,
        hsm_port=args.hsm,
        gcs_sysid=args.sysid,
        gcs_compid=args.compid,
        verbose=args.verbose
    )

    # Override init_hsm with command line options
    original_init_hsm = client.init_hsm
    def init_hsm_with_options():
        return original_init_hsm(force_new=args.force_new, no_hsm=args.no_hsm)
    client.init_hsm = init_hsm_with_options

    success = client.run(timeout=args.timeout, trigger_hsm_init=not args.no_trigger)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
