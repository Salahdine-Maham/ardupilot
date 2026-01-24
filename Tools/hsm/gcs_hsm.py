#!/usr/bin/env python3
"""
GCS HSM Module - KeyOrchestrator pour Ground Control Station

Ce module gere la hierarchie de cles cryptographiques cote GCS:
- Master Key (MK) - Cle racine unique
- Wrapper Key (WK) - Pour echange securise des DEK (ECDH)
- Data Encryption Key (DEK) - Pour chiffrement MAVLink

Compatible avec HSM LeMonolith v0.6

Architecture:
    GCS (ce module) <---> HSM #1 (USB /dev/ttyUSB0)
    Drone (Pixhawk) <---> HSM #2 (UART TELEM2) [futur]

Usage:
    from gcs_hsm import GCS_HSM

    hsm = GCS_HSM()
    if hsm.connect():
        hsm.init_mission_keys()
        # Pret pour Key Exchange Protocol
    hsm.disconnect()

Date: 2026-01-24
"""

import serial
import time
import os
import hashlib
import hmac
import struct
from typing import Optional, Tuple
from enum import Enum

# =============================================================================
# CONSTANTES
# =============================================================================

# HSM Offsets v2.0 (identiques au C++ KeyOrchestrator)
HSM_OFFSET_MK = 0x0100       # Master Key
HSM_OFFSET_WK = 0x0120       # Wrapped Wrapper Key (private)
HSM_OFFSET_DEK = 0x0140      # Wrapped DEK
HSM_OFFSET_WK_TAG = 0x0160   # HMAC tag for WK
HSM_OFFSET_DEK_TAG = 0x0180  # HMAC tag for DEK

KEY_SIZE = 32   # 256 bits
TAG_SIZE = 32   # HMAC-SHA256

# Timings HSM LeMonolith (critiques!)
DELAY_POWER_ON = 3.5     # ATR + auto-SELECT
DELAY_WRITE = 2.5        # EEPROM write
DELAY_READ = 0.2         # Read operation
DELAY_COMMAND = 0.5      # Generic command

# HKDF parameters (identiques au C++)
HKDF_SALT = b"ArduPilot-HSM-Salt-v2"
HKDF_INFO_WK = b"WrapperKey-P256-v1"

# P-256 curve order (pour validation scalar)
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


class KeyState(Enum):
    """Etat des cles"""
    NOT_LOADED = 0
    LOADED = 1
    ERROR = 2


class GCS_HSM:
    """
    Gestionnaire HSM pour Ground Control Station

    Implemente la meme hierarchie de cles que KeyOrchestrator (C++)
    """

    def __init__(self, port: str = '/dev/ttyUSB0', baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None

        # Etat des cles
        self.mk_state = KeyState.NOT_LOADED
        self.wk_state = KeyState.NOT_LOADED
        self.dek_state = KeyState.NOT_LOADED

        # Cles en memoire (RAM seulement)
        self._master_key: Optional[bytes] = None
        self._wk_private: Optional[bytes] = None
        self._wk_public: Optional[bytes] = None
        self._my_dek: Optional[bytes] = None

        # DEKs des peers (pour dechiffrement messages entrants)
        self._peer_deks: dict = {}  # {system_id: dek_bytes}

        # Stats
        self.init_time_ms = 0
        self.last_error = ""

    # =========================================================================
    # CONNEXION HSM
    # =========================================================================

    def connect(self) -> bool:
        """Connexion au HSM via serial"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=3,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            time.sleep(0.5)
            self._flush_input()
            self._log(f"Connecte a {self.port}")
            return True
        except Exception as e:
            self.last_error = str(e)
            self._log(f"ERREUR connexion: {e}")
            return False

    def disconnect(self):
        """Deconnexion du HSM"""
        if self.ser:
            self.ser.close()
            self.ser = None
            self._log("Deconnecte")

    def is_connected(self) -> bool:
        """Verifie si connecte"""
        return self.ser is not None and self.ser.is_open

    # =========================================================================
    # COMMUNICATION HSM
    # =========================================================================

    def _flush_input(self):
        """Vide le buffer d'entree"""
        if not self.ser:
            return
        time.sleep(0.1)
        while self.ser.in_waiting:
            self.ser.read(self.ser.in_waiting)
            time.sleep(0.05)

    def _send_command(self, cmd: str, timeout: float = 3.0) -> str:
        """Envoie une commande et retourne la reponse"""
        if not self.ser:
            return ""

        self._flush_input()
        self.ser.write(f"{cmd}\r\n".encode())

        response = ""
        start = time.time()
        while (time.time() - start) < timeout:
            if self.ser.in_waiting:
                chunk = self.ser.read(self.ser.in_waiting).decode('latin-1', errors='replace')
                response += chunk
            time.sleep(0.05)

        return response.strip()

    def _send_apdu(self, apdu_hex: str, timeout: float = 3.0) -> str:
        """Envoie une commande APDU"""
        if not self.ser:
            return ""

        self._flush_input()

        # Format: "A <apdu_hex>\r\n"
        cmd = f"A {apdu_hex}\r\n"
        self.ser.write(cmd.encode())

        # Delai selon type commande
        is_write = apdu_hex.upper().startswith("00D0")
        if is_write:
            time.sleep(DELAY_WRITE)
        else:
            time.sleep(DELAY_READ)

        # Lire la reponse
        response = ""
        start = time.time()
        while (time.time() - start) < timeout:
            if self.ser.in_waiting:
                chunk = self.ser.read(self.ser.in_waiting).decode('latin-1', errors='replace')
                response += chunk
                if "9000" in response:
                    time.sleep(0.1)
                    if self.ser.in_waiting:
                        response += self.ser.read(self.ser.in_waiting).decode('latin-1', errors='replace')
                    break
            time.sleep(0.05)

        return response.strip()

    def _init_hsm_hardware(self) -> bool:
        """Initialise le HSM (power cycle + SELECT + VERIFY)"""
        self._log("Initialisation HSM...")

        # 1. Power OFF
        self._flush_input()
        self.ser.write(b"off\r\n")
        time.sleep(0.5)
        self._flush_input()

        # 2. Power ON (attente ATR)
        self._log("  Power ON (attente ATR)...")
        self.ser.write(b"on\r\n")
        time.sleep(DELAY_POWER_ON)

        # Lire et ignorer ATR
        start = time.time()
        while (time.time() - start) < 3.0:
            if self.ser.in_waiting:
                self.ser.read(self.ser.in_waiting)
            time.sleep(0.1)

        self._flush_input()
        time.sleep(DELAY_COMMAND)
        self._flush_input()

        # 3. SELECT CC Applet
        self._log("  SELECT applet CC...")
        response = self._send_apdu("00A4040006010203040601", timeout=5)
        if "9000" not in response:
            self.last_error = "SELECT failed"
            return False

        time.sleep(0.2)

        # 4. VERIFY PIN (00000000)
        self._log("  VERIFY PIN...")
        response = self._send_apdu("00200001083030303030303030", timeout=3)
        if "9000" not in response:
            self.last_error = "VERIFY PIN failed"
            return False

        self._log("HSM initialise avec succes")
        return True

    # =========================================================================
    # OPERATIONS HSM
    # =========================================================================

    def _read_binary(self, offset: int, length: int) -> Optional[bytes]:
        """Lit des donnees depuis le HSM"""
        apdu = f"00B0{offset >> 8:02X}{offset & 0xFF:02X}{length:02X}"
        response = self._send_apdu(apdu)

        if "9000" in response:
            # Extraire les bytes hex de la reponse
            lines = response.split('\n')
            for line in lines:
                if "9000" in line:
                    parts = line.split()
                    data_hex = ""
                    for part in parts:
                        if part.upper() == "9000":
                            break
                        if all(c in '0123456789ABCDEFabcdef' for c in part):
                            data_hex += part
                    if len(data_hex) >= length * 2:
                        return bytes.fromhex(data_hex[:length * 2])

            # Alternative: chercher pattern hex
            if "Rx" in response:
                idx = response.index("Rx")
                remaining = response[idx+2:]
                hex_chars = ''.join(c for c in remaining if c in '0123456789ABCDEFabcdef')
                if len(hex_chars) >= length * 2:
                    return bytes.fromhex(hex_chars[:length * 2])

        return None

    def _write_binary(self, offset: int, data: bytes) -> bool:
        """Ecrit des donnees dans le HSM"""
        data_hex = data.hex().upper()
        # IMPORTANT: Applet CC utilise 00D0 (pas 00D6 standard!)
        apdu = f"00D0{offset >> 8:02X}{offset & 0xFF:02X}{len(data):02X}{data_hex}"
        response = self._send_apdu(apdu, timeout=5)
        return "9000" in response

    # =========================================================================
    # DERIVATION ET WRAPPING
    # =========================================================================

    def _hkdf_sha256(self, ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
        """HKDF-SHA256 (RFC 5869)"""
        # Extract
        if not salt:
            salt = b'\x00' * 32
        prk = hmac.new(salt, ikm, hashlib.sha256).digest()

        # Expand
        t = b""
        okm = b""
        for i in range(1, (length + 31) // 32 + 1):
            t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
            okm += t

        return okm[:length]

    def _derive_wk_private(self, master_key: bytes) -> bytes:
        """Derive WK private depuis MK via HKDF"""
        # Derive 32 bytes pour scalar P-256
        derived = self._hkdf_sha256(master_key, HKDF_SALT, HKDF_INFO_WK, 32)

        # Verifier que c'est un scalar valide (< order)
        scalar = int.from_bytes(derived, 'big')
        if scalar >= P256_ORDER or scalar == 0:
            # Tres rare, mais gerer le cas
            self._log("WARNING: HKDF produced invalid scalar, retrying with counter")
            for counter in range(1, 256):
                info_with_counter = HKDF_INFO_WK + bytes([counter])
                derived = self._hkdf_sha256(master_key, HKDF_SALT, info_with_counter, 32)
                scalar = int.from_bytes(derived, 'big')
                if 0 < scalar < P256_ORDER:
                    break

        return derived

    def _wrap_key(self, key: bytes, master_key: bytes) -> Tuple[bytes, bytes]:
        """Wrap une cle avec XOR + HMAC"""
        wrapped = bytes(a ^ b for a, b in zip(key, master_key))
        tag = hmac.new(master_key, wrapped, hashlib.sha256).digest()
        return wrapped, tag

    def _unwrap_key(self, wrapped: bytes, tag: bytes, master_key: bytes) -> Optional[bytes]:
        """Unwrap une cle et verifier HMAC"""
        expected_tag = hmac.new(master_key, wrapped, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            self._log("ERREUR: HMAC tag invalide!")
            return None
        return bytes(a ^ b for a, b in zip(wrapped, master_key))

    # =========================================================================
    # API PRINCIPALE
    # =========================================================================

    def init_mission_keys(self, force_new: bool = False) -> bool:
        """
        Initialise la hierarchie de cles pour une nouvelle mission

        Args:
            force_new: Si True, genere nouvelles cles meme si existantes

        Returns:
            True si succes
        """
        start_time = time.time()

        if not self.is_connected():
            self.last_error = "Non connecte"
            return False

        # Initialiser hardware HSM
        if not self._init_hsm_hardware():
            return False

        self._log("=== Initialisation Mission Keys ===")

        # 1. Master Key
        self._log("Step 1/3: Master Key...")
        if not self._init_master_key(force_new):
            return False

        # 2. Wrapper Key
        self._log("Step 2/3: Wrapper Key...")
        if not self._init_wrapper_key(force_new):
            return False

        # 3. DEK
        self._log("Step 3/3: Data Encryption Key...")
        if not self._init_dek(force_new):
            return False

        self.init_time_ms = int((time.time() - start_time) * 1000)

        self._log("=== Mission Keys OK ===")
        self._log(f"  Temps: {self.init_time_ms} ms")
        self._log(f"  MK:  @0x{HSM_OFFSET_MK:04X}")
        self._log(f"  WK:  @0x{HSM_OFFSET_WK:04X} (tag @0x{HSM_OFFSET_WK_TAG:04X})")
        self._log(f"  DEK: @0x{HSM_OFFSET_DEK:04X} (tag @0x{HSM_OFFSET_DEK_TAG:04X})")

        return True

    def _init_master_key(self, force_new: bool) -> bool:
        """Initialise ou charge Master Key"""
        if not force_new:
            # Essayer de charger MK existante
            loaded = self._read_binary(HSM_OFFSET_MK, KEY_SIZE)
            if loaded and loaded != bytes(KEY_SIZE):
                self._master_key = loaded
                self.mk_state = KeyState.LOADED
                self._log(f"  MK chargee: {loaded[:4].hex().upper()}...")
                return True

        # Generer nouvelle MK
        self._log("  Generation nouvelle MK...")
        self._master_key = os.urandom(KEY_SIZE)

        if not self._write_binary(HSM_OFFSET_MK, self._master_key):
            self.last_error = "WRITE MK failed"
            self.mk_state = KeyState.ERROR
            return False

        time.sleep(0.3)

        # Verifier
        verify = self._read_binary(HSM_OFFSET_MK, KEY_SIZE)
        if verify != self._master_key:
            self.last_error = "MK verification failed"
            self.mk_state = KeyState.ERROR
            return False

        self.mk_state = KeyState.LOADED
        self._log(f"  MK generee: {self._master_key[:4].hex().upper()}...")
        return True

    def _init_wrapper_key(self, force_new: bool) -> bool:
        """Initialise ou charge Wrapper Key"""
        if self._master_key is None:
            self.last_error = "MK not loaded"
            return False

        if not force_new:
            # Essayer de charger WK wrappee
            wrapped = self._read_binary(HSM_OFFSET_WK, KEY_SIZE)
            tag = self._read_binary(HSM_OFFSET_WK_TAG, TAG_SIZE)

            if wrapped and tag and wrapped != bytes(KEY_SIZE):
                unwrapped = self._unwrap_key(wrapped, tag, self._master_key)
                if unwrapped:
                    self._wk_private = unwrapped
                    self.wk_state = KeyState.LOADED
                    self._log(f"  WK chargee: {unwrapped[:4].hex().upper()}...")
                    return True

        # Deriver nouvelle WK depuis MK
        self._log("  Derivation nouvelle WK...")
        self._wk_private = self._derive_wk_private(self._master_key)

        # Wrap et stocker
        wrapped, tag = self._wrap_key(self._wk_private, self._master_key)

        if not self._write_binary(HSM_OFFSET_WK, wrapped):
            self.last_error = "WRITE WK failed"
            self.wk_state = KeyState.ERROR
            return False

        time.sleep(0.3)

        if not self._write_binary(HSM_OFFSET_WK_TAG, tag):
            self.last_error = "WRITE WK tag failed"
            self.wk_state = KeyState.ERROR
            return False

        self.wk_state = KeyState.LOADED
        self._log(f"  WK derivee: {self._wk_private[:4].hex().upper()}...")
        return True

    def _init_dek(self, force_new: bool) -> bool:
        """Initialise ou charge DEK"""
        if self._master_key is None:
            self.last_error = "MK not loaded"
            return False

        if not force_new:
            # Essayer de charger DEK wrappee
            wrapped = self._read_binary(HSM_OFFSET_DEK, KEY_SIZE)
            tag = self._read_binary(HSM_OFFSET_DEK_TAG, TAG_SIZE)

            if wrapped and tag and wrapped != bytes(KEY_SIZE):
                unwrapped = self._unwrap_key(wrapped, tag, self._master_key)
                if unwrapped:
                    self._my_dek = unwrapped
                    self.dek_state = KeyState.LOADED
                    self._log(f"  DEK chargee: {unwrapped[:4].hex().upper()}...")
                    return True

        # Generer nouvelle DEK
        self._log("  Generation nouvelle DEK...")
        self._my_dek = os.urandom(KEY_SIZE)

        # Wrap et stocker
        wrapped, tag = self._wrap_key(self._my_dek, self._master_key)

        if not self._write_binary(HSM_OFFSET_DEK, wrapped):
            self.last_error = "WRITE DEK failed"
            self.dek_state = KeyState.ERROR
            return False

        time.sleep(0.3)

        if not self._write_binary(HSM_OFFSET_DEK_TAG, tag):
            self.last_error = "WRITE DEK tag failed"
            self.dek_state = KeyState.ERROR
            return False

        self.dek_state = KeyState.LOADED
        self._log(f"  DEK generee: {self._my_dek[:4].hex().upper()}...")
        return True

    # =========================================================================
    # ACCESSEURS (pour Key Exchange Protocol)
    # =========================================================================

    def get_my_dek(self) -> Optional[bytes]:
        """Retourne MY_DEK pour chiffrement messages sortants"""
        return self._my_dek if self.dek_state == KeyState.LOADED else None

    def get_wk_public(self) -> Optional[bytes]:
        """Retourne WK publique (pour echange de cles)"""
        # TODO: Calculer depuis wk_private avec micro-ecc ou cryptography
        # Pour l'instant, retourne None - sera implemente avec Feature 2.2
        return self._wk_public

    def store_peer_dek(self, system_id: int, dek: bytes) -> bool:
        """Stocke la DEK d'un peer (pour dechiffrement messages entrants)"""
        if len(dek) != KEY_SIZE:
            return False
        self._peer_deks[system_id] = dek
        self._log(f"  Peer DEK stockee: sysid={system_id}")
        return True

    def get_peer_dek(self, system_id: int) -> Optional[bytes]:
        """Retourne la DEK d'un peer"""
        return self._peer_deks.get(system_id)

    def get_status(self) -> dict:
        """Retourne l'etat actuel"""
        return {
            'connected': self.is_connected(),
            'mk_state': self.mk_state.name,
            'wk_state': self.wk_state.name,
            'dek_state': self.dek_state.name,
            'peer_count': len(self._peer_deks),
            'init_time_ms': self.init_time_ms,
            'last_error': self.last_error
        }

    # =========================================================================
    # UTILITAIRES
    # =========================================================================

    def _log(self, msg: str):
        """Log avec prefix"""
        print(f"[GCS_HSM] {msg}", flush=True)


# =============================================================================
# TEST STANDALONE
# =============================================================================

def main():
    """Test du module GCS_HSM"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Test GCS_HSM module')
    parser.add_argument('--port', default='/dev/ttyUSB0', help='Port HSM')
    parser.add_argument('--force-new', action='store_true', help='Force nouvelles cles')
    args = parser.parse_args()

    print("=" * 60, flush=True)
    print("  GCS_HSM - Test Module", flush=True)
    print("=" * 60, flush=True)
    sys.stdout.flush()

    hsm = GCS_HSM(port=args.port)

    if not hsm.connect():
        print(f"ERREUR: Impossible de se connecter a {args.port}")
        return 1

    try:
        # Initialiser les cles
        success = hsm.init_mission_keys(force_new=args.force_new)

        if success:
            print("\n" + "=" * 60)
            print("  STATUS")
            print("=" * 60)
            status = hsm.get_status()
            for k, v in status.items():
                print(f"  {k}: {v}")

            # Test accesseurs
            dek = hsm.get_my_dek()
            if dek:
                print(f"\n  MY_DEK disponible: {dek[:4].hex().upper()}...")

            print("\n*** TEST REUSSI ***")
            return 0
        else:
            print(f"\n*** TEST ECHOUE: {hsm.last_error} ***")
            return 1

    finally:
        hsm.disconnect()


if __name__ == '__main__':
    exit(main())
