#!/usr/bin/env python3
"""
Test KeyOrchestrator v2.0 avec HSM LeMonolith reel

Ce script teste les operations HSM de la nouvelle architecture:
- Offsets v2.0: MK@0x0100, WK@0x0120, DEK@0x0140, tags@0x0160/0x0180
- Read/Write BINARY sur ces offsets
- Validation de l'integrite des donnees

Hardware requis:
- HSM LeMonolith v0.6 sur /dev/ttyUSB0

Usage:
    python3 test_key_orchestrator_hsm.py [--port /dev/ttyUSB0]

Date: 2026-01-24
"""

import serial
import time
import sys
import argparse
import hashlib
import hmac
import os

# HSM Offsets v2.0
HSM_OFFSET_MK = 0x0100
HSM_OFFSET_WK = 0x0120
HSM_OFFSET_DEK = 0x0140
HSM_OFFSET_WK_TAG = 0x0160
HSM_OFFSET_DEK_TAG = 0x0180

KEY_SIZE = 32
TAG_SIZE = 32

class HSMTester:
    def __init__(self, port='/dev/ttyUSB0', baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.tests_passed = 0
        self.tests_failed = 0

    def connect(self):
        """Connexion au HSM"""
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
            self.ser.reset_input_buffer()
            print(f"[OK] Connecte a {self.port}")
            return True
        except Exception as e:
            print(f"[ERREUR] Connexion: {e}")
            return False

    def disconnect(self):
        """Deconnexion du HSM"""
        if self.ser:
            self.ser.close()
            print("[OK] Deconnecte")

    def send_apdu(self, apdu_hex, timeout=3):
        """Envoie une commande APDU et retourne la reponse"""
        try:
            # Flush avant commande
            self.flush_input()

            # Format: "A <apdu_hex>\r\n"
            cmd = f"A {apdu_hex}\r\n"
            self.ser.write(cmd.encode())

            # Delai selon type commande
            is_write = apdu_hex.upper().startswith("00D0")
            if is_write:
                time.sleep(2.5)  # WRITE BINARY: 2-3s pour EEPROM
            else:
                time.sleep(0.2)  # Autres commandes

            # Lire la reponse
            response = ""
            start = time.time()
            while (time.time() - start) < timeout:
                if self.ser.in_waiting:
                    chunk = self.ser.read(self.ser.in_waiting).decode('latin-1', errors='replace')
                    response += chunk
                    # Verifier si reponse complete (9000 ou 6xxx)
                    clean = ''.join(c for c in response if c.isalnum() or c in ' \n')
                    if "9000" in clean:
                        time.sleep(0.1)
                        if self.ser.in_waiting:
                            response += self.ser.read(self.ser.in_waiting).decode('latin-1', errors='replace')
                        break
                    # Code erreur
                    for i in range(len(clean) - 3):
                        if clean[i] == '6' and clean[i+1].isdigit() and clean[i+2:i+4].isalnum():
                            return response.strip()
                time.sleep(0.05)

            return response.strip()
        except Exception as e:
            print(f"[ERREUR] APDU: {e}")
            return ""

    def flush_input(self):
        """Vide le buffer d'entree"""
        time.sleep(0.1)
        while self.ser.in_waiting:
            self.ser.read(self.ser.in_waiting)
            time.sleep(0.05)

    def init_hsm(self):
        """Initialise le HSM (OFF + ON + SELECT + VERIFY)"""
        print("\n=== Initialisation HSM ===")

        # 1. Power OFF (reset propre)
        print("Power OFF...")
        self.flush_input()
        self.ser.write(b"off\r\n")
        time.sleep(0.5)
        self.flush_input()

        # 2. Power ON
        print("Power ON (attente ATR 3-5s)...")
        self.ser.write(b"on\r\n")
        time.sleep(3.5)  # Attendre ATR (critique: 3-5s)

        # Lire et ignorer ATR
        start = time.time()
        while (time.time() - start) < 3.0:
            if self.ser.in_waiting:
                chunk = self.ser.read(self.ser.in_waiting)
                print(f"  ATR recu: {len(chunk)} bytes")
            time.sleep(0.1)

        self.flush_input()
        time.sleep(0.5)  # Stabilisation
        self.flush_input()

        # 3. SELECT CC Applet (AID: 010203040601)
        print("SELECT applet CC...")
        time.sleep(0.5)  # Delai avant SELECT
        select_apdu = "00A4040006010203040601"  # AID: CC applet
        response = self.send_apdu(select_apdu, timeout=5)
        if "9000" not in response:
            # Essayer AID alternatif
            print("  Essai AID alternatif...")
            select_apdu = "00A404000CA0000003964541000000000101"
            response = self.send_apdu(select_apdu, timeout=5)
            if "9000" not in response:
                print(f"[ERREUR] SELECT failed: {response[:100]}...")
                return False
        print("[OK] Applet selectionnee")
        time.sleep(0.2)

        # 4. VERIFY PIN (00000000 en ASCII = 3030303030303030)
        print("VERIFY PIN...")
        verify_apdu = "00200001083030303030303030"  # PIN: 00000000
        response = self.send_apdu(verify_apdu, timeout=3)
        if "9000" not in response:
            # Essayer PIN alternatif (12345678)
            print("  Essai PIN alternatif...")
            verify_apdu = "00200001083132333435363738"  # PIN: 12345678
            response = self.send_apdu(verify_apdu, timeout=3)
            if "9000" not in response:
                print(f"[ERREUR] VERIFY failed: {response[:100]}...")
                return False
        print("[OK] PIN verifie")

        print("[OK] HSM initialise avec succes")
        return True

    def read_binary(self, offset, length):
        """Lit des donnees depuis le HSM"""
        apdu = f"00B0{offset >> 8:02X}{offset & 0xFF:02X}{length:02X}"
        response = self.send_apdu(apdu)

        # Extraire les donnees hex de la reponse
        if "9000" in response:
            # Chercher les bytes hex avant 9000
            lines = response.split('\n')
            for line in lines:
                if "9000" in line:
                    # Extraire les hex avant 9000
                    parts = line.split()
                    data_hex = ""
                    for part in parts:
                        if part.upper() == "9000":
                            break
                        if all(c in '0123456789ABCDEFabcdef' for c in part):
                            data_hex += part
                    if len(data_hex) >= length * 2:
                        return bytes.fromhex(data_hex[:length * 2])

            # Alternative: chercher "Rx" marker
            if "Rx" in response:
                idx = response.index("Rx")
                remaining = response[idx+2:]
                hex_chars = ''.join(c for c in remaining if c in '0123456789ABCDEFabcdef')
                if len(hex_chars) >= length * 2:
                    return bytes.fromhex(hex_chars[:length * 2])

        return None

    def write_binary(self, offset, data):
        """Ecrit des donnees dans le HSM (INS=D0 pour applet CC)"""
        data_hex = data.hex().upper()
        # IMPORTANT: Applet CC utilise 00D0 pour WRITE (pas 00D6 standard!)
        apdu = f"00D0{offset >> 8:02X}{offset & 0xFF:02X}{len(data):02X}{data_hex}"
        response = self.send_apdu(apdu, timeout=5)  # WRITE peut etre lent
        return "9000" in response

    def test_assert(self, condition, message):
        """Helper pour assertions"""
        if condition:
            print(f"[PASS] {message}")
            self.tests_passed += 1
        else:
            print(f"[FAIL] {message}")
            self.tests_failed += 1
        return condition

    # ========================================================================
    # TESTS
    # ========================================================================

    def test_read_write_mk_offset(self):
        """Test lecture/ecriture offset MK (0x0100)"""
        print("\n=== TEST 1: R/W Master Key Offset ===")

        # Generer MK test
        test_mk = os.urandom(KEY_SIZE)
        print(f"MK test: {test_mk[:8].hex().upper()}...")

        # Ecrire
        write_ok = self.write_binary(HSM_OFFSET_MK, test_mk)
        self.test_assert(write_ok, f"WRITE MK @0x{HSM_OFFSET_MK:04X}")

        if not write_ok:
            return False

        time.sleep(0.5)  # Delai EEPROM

        # Lire
        read_data = self.read_binary(HSM_OFFSET_MK, KEY_SIZE)
        read_ok = read_data is not None
        self.test_assert(read_ok, f"READ MK @0x{HSM_OFFSET_MK:04X}")

        if read_ok:
            match = (read_data == test_mk)
            self.test_assert(match, "MK data integrity")
            if not match:
                print(f"  Expected: {test_mk[:8].hex().upper()}...")
                print(f"  Got:      {read_data[:8].hex().upper() if read_data else 'None'}...")

        return read_ok

    def test_read_write_wk_offset(self):
        """Test lecture/ecriture offset WK (0x0120)"""
        print("\n=== TEST 2: R/W Wrapper Key Offset ===")

        test_wk = os.urandom(KEY_SIZE)
        print(f"WK test: {test_wk[:8].hex().upper()}...")

        write_ok = self.write_binary(HSM_OFFSET_WK, test_wk)
        self.test_assert(write_ok, f"WRITE WK @0x{HSM_OFFSET_WK:04X}")

        if not write_ok:
            return False

        time.sleep(0.5)

        read_data = self.read_binary(HSM_OFFSET_WK, KEY_SIZE)
        read_ok = read_data is not None
        self.test_assert(read_ok, f"READ WK @0x{HSM_OFFSET_WK:04X}")

        if read_ok:
            match = (read_data == test_wk)
            self.test_assert(match, "WK data integrity")

        return read_ok

    def test_read_write_dek_offset(self):
        """Test lecture/ecriture offset DEK (0x0140)"""
        print("\n=== TEST 3: R/W DEK Offset ===")

        test_dek = os.urandom(KEY_SIZE)
        print(f"DEK test: {test_dek[:8].hex().upper()}...")

        write_ok = self.write_binary(HSM_OFFSET_DEK, test_dek)
        self.test_assert(write_ok, f"WRITE DEK @0x{HSM_OFFSET_DEK:04X}")

        if not write_ok:
            return False

        time.sleep(0.5)

        read_data = self.read_binary(HSM_OFFSET_DEK, KEY_SIZE)
        read_ok = read_data is not None
        self.test_assert(read_ok, f"READ DEK @0x{HSM_OFFSET_DEK:04X}")

        if read_ok:
            match = (read_data == test_dek)
            self.test_assert(match, "DEK data integrity")

        return read_ok

    def test_tag_offsets(self):
        """Test lecture/ecriture offsets TAG (0x0160, 0x0180)"""
        print("\n=== TEST 4: R/W Tag Offsets ===")

        # WK Tag
        test_wk_tag = os.urandom(TAG_SIZE)
        write_ok = self.write_binary(HSM_OFFSET_WK_TAG, test_wk_tag)
        self.test_assert(write_ok, f"WRITE WK_TAG @0x{HSM_OFFSET_WK_TAG:04X}")

        time.sleep(0.3)

        read_data = self.read_binary(HSM_OFFSET_WK_TAG, TAG_SIZE)
        if read_data:
            self.test_assert(read_data == test_wk_tag, "WK_TAG data integrity")

        # DEK Tag
        test_dek_tag = os.urandom(TAG_SIZE)
        write_ok = self.write_binary(HSM_OFFSET_DEK_TAG, test_dek_tag)
        self.test_assert(write_ok, f"WRITE DEK_TAG @0x{HSM_OFFSET_DEK_TAG:04X}")

        time.sleep(0.3)

        read_data = self.read_binary(HSM_OFFSET_DEK_TAG, TAG_SIZE)
        if read_data:
            self.test_assert(read_data == test_dek_tag, "DEK_TAG data integrity")

    def test_full_key_hierarchy(self):
        """Test cycle complet MK -> WK -> DEK avec wrapping"""
        print("\n=== TEST 5: Full Key Hierarchy Cycle ===")

        # 1. Generer et stocker MK
        print("\n--- Step 1: Master Key ---")
        master_key = os.urandom(KEY_SIZE)
        print(f"MK: {master_key[:8].hex().upper()}...")

        self.write_binary(HSM_OFFSET_MK, master_key)
        time.sleep(0.3)

        # 2. Generer WK (simule derivation HKDF)
        print("\n--- Step 2: Wrapper Key ---")
        wk_private = hashlib.pbkdf2_hmac('sha256', master_key, b'ArduPilot-HSM-Salt-v2', 1)
        print(f"WK_priv (derived): {wk_private[:8].hex().upper()}...")

        # Wrap WK avec MK (XOR)
        wrapped_wk = bytes(a ^ b for a, b in zip(wk_private, master_key))
        wk_tag = hmac.new(master_key, wrapped_wk, hashlib.sha256).digest()

        self.write_binary(HSM_OFFSET_WK, wrapped_wk)
        time.sleep(0.3)
        self.write_binary(HSM_OFFSET_WK_TAG, wk_tag)
        time.sleep(0.3)

        # 3. Generer et stocker DEK
        print("\n--- Step 3: DEK ---")
        my_dek = os.urandom(KEY_SIZE)
        print(f"DEK: {my_dek[:8].hex().upper()}...")

        wrapped_dek = bytes(a ^ b for a, b in zip(my_dek, master_key))
        dek_tag = hmac.new(master_key, wrapped_dek, hashlib.sha256).digest()

        self.write_binary(HSM_OFFSET_DEK, wrapped_dek)
        time.sleep(0.3)
        self.write_binary(HSM_OFFSET_DEK_TAG, dek_tag)
        time.sleep(0.3)

        # 4. Simuler reboot: relire tout
        print("\n--- Step 4: Restore (simulated reboot) ---")

        # Relire MK
        loaded_mk = self.read_binary(HSM_OFFSET_MK, KEY_SIZE)
        mk_match = loaded_mk == master_key
        self.test_assert(mk_match, "MK restored correctly")

        # Relire et unwrap WK
        loaded_wrapped_wk = self.read_binary(HSM_OFFSET_WK, KEY_SIZE)
        loaded_wk_tag = self.read_binary(HSM_OFFSET_WK_TAG, TAG_SIZE)

        if loaded_wrapped_wk and loaded_wk_tag:
            expected_tag = hmac.new(loaded_mk, loaded_wrapped_wk, hashlib.sha256).digest()
            tag_valid = (loaded_wk_tag == expected_tag)
            self.test_assert(tag_valid, "WK HMAC tag valid")

            if tag_valid:
                restored_wk = bytes(a ^ b for a, b in zip(loaded_wrapped_wk, loaded_mk))
                wk_match = (restored_wk == wk_private)
                self.test_assert(wk_match, "WK unwrapped correctly")

        # Relire et unwrap DEK
        loaded_wrapped_dek = self.read_binary(HSM_OFFSET_DEK, KEY_SIZE)
        loaded_dek_tag = self.read_binary(HSM_OFFSET_DEK_TAG, TAG_SIZE)

        if loaded_wrapped_dek and loaded_dek_tag:
            expected_tag = hmac.new(loaded_mk, loaded_wrapped_dek, hashlib.sha256).digest()
            tag_valid = (loaded_dek_tag == expected_tag)
            self.test_assert(tag_valid, "DEK HMAC tag valid")

            if tag_valid:
                restored_dek = bytes(a ^ b for a, b in zip(loaded_wrapped_dek, loaded_mk))
                dek_match = (restored_dek == my_dek)
                self.test_assert(dek_match, "DEK unwrapped correctly")

    def run_all_tests(self):
        """Execute tous les tests"""
        print("=" * 60)
        print("  KeyOrchestrator v2.0 - HSM Hardware Tests")
        print("  HSM Port:", self.port)
        print("=" * 60)

        if not self.connect():
            return False

        if not self.init_hsm():
            self.disconnect()
            return False

        # Executer les tests
        self.test_read_write_mk_offset()
        self.test_read_write_wk_offset()
        self.test_read_write_dek_offset()
        self.test_tag_offsets()
        self.test_full_key_hierarchy()

        self.disconnect()

        # Resume
        print("\n" + "=" * 60)
        print("  RESULTATS")
        print("=" * 60)
        print(f"  Passed: {self.tests_passed}")
        print(f"  Failed: {self.tests_failed}")
        print("=" * 60)

        if self.tests_failed > 0:
            print("\n*** CERTAINS TESTS ONT ECHOUE ***")
            return False

        print("\n*** TOUS LES TESTS SONT PASSES ***")
        return True


def main():
    parser = argparse.ArgumentParser(description='Test KeyOrchestrator v2.0 avec HSM')
    parser.add_argument('--port', default='/dev/ttyUSB0', help='Port HSM')
    args = parser.parse_args()

    tester = HSMTester(port=args.port)
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
