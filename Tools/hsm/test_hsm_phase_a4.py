#!/usr/bin/env python3
"""
Phase A4: Tests Clés Symétriques (ChaCha20/DEK)
================================================
Teste la génération, stockage et utilisation des clés symétriques.

Tests:
  4.1 Générer MK (Master Key)
  4.2 Stocker MK dans HSM
  4.3 Générer DEK (Data Encryption Key)
  4.4 Stocker DEK dans HSM
  4.5 Chiffrement XChaCha20-Poly1305
  4.6 Déchiffrement XChaCha20-Poly1305
  4.7 Test intégrité (TAG - détection modification)
  4.8 Wrap DEK (XOR + HMAC)
  4.9 Unwrap DEK

Dépendances: pip install pynacl
"""

import serial
import time
import sys
import os
import hashlib
import hmac
from datetime import datetime

# Crypto imports
try:
    import nacl.secret
    import nacl.utils
    from nacl.bindings import (
        crypto_aead_xchacha20poly1305_ietf_encrypt,
        crypto_aead_xchacha20poly1305_ietf_decrypt,
        crypto_aead_xchacha20poly1305_ietf_NPUBBYTES,
        crypto_aead_xchacha20poly1305_ietf_ABYTES
    )
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False
    print("WARNING: PyNaCl not installed. Install with: pip install pynacl")

# Configuration
HSM_PORTS = ['/dev/ttyUSB0', '/dev/ttyUSB3']
BAUDRATE = 115200
TIMEOUT = 5

# EEPROM Offsets
OFFSET_MK = 0x0100           # Master Key (32 bytes)
OFFSET_DEK = 0x0140          # Data Encryption Key (32 bytes)
OFFSET_WRAPPED_DEK = 0x0120  # Wrapped DEK (32 bytes)
OFFSET_DEK_TAG = 0x0180      # HMAC Tag for DEK (32 bytes)

# Commandes de base
CMD_OFF = b'off\r\n'
CMD_ON = b'on\r\n'
CMD_SELECT_CC = b'A 00A4040006010203040601\r\n'
CMD_VERIFY_PIN = b'A 00200001083030303030303030\r\n'

# Colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}  {text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")

def print_test(test_num, description):
    print(f"\n{Colors.CYAN}[Test {test_num}] {description}{Colors.ENDC}")
    print("-" * 50)

def print_hsm(hsm_id, port):
    print(f"{Colors.BLUE}  HSM #{hsm_id} ({port}):{Colors.ENDC}")

def print_ok(message):
    print(f"    {Colors.GREEN}✓ {message}{Colors.ENDC}")

def print_fail(message):
    print(f"    {Colors.RED}✗ {message}{Colors.ENDC}")

def print_warn(message):
    print(f"    {Colors.YELLOW}⚠ {message}{Colors.ENDC}")

def print_info(message):
    print(f"    {Colors.CYAN}→ {message}{Colors.ENDC}")

def print_data(label, data, max_len=64):
    if isinstance(data, bytes):
        data = data.hex().upper()
    if len(data) > max_len:
        display = data[:max_len] + "..."
    else:
        display = data
    print(f"    {Colors.YELLOW}{label}: {display}{Colors.ENDC}")


class SymmetricCrypto:
    """Gère les opérations cryptographiques symétriques"""

    @staticmethod
    def generate_key(size=32):
        """Génère une clé aléatoire"""
        return os.urandom(size)

    @staticmethod
    def generate_nonce(size=24):
        """Génère un nonce aléatoire (24 bytes pour XChaCha20)"""
        return os.urandom(size)

    @staticmethod
    def encrypt_xchacha20(key, plaintext, nonce=None):
        """Chiffre avec XChaCha20-Poly1305"""
        if not NACL_AVAILABLE:
            return None, None, None

        if nonce is None:
            nonce = os.urandom(24)  # 24 bytes pour XChaCha20

        if isinstance(plaintext, str):
            plaintext = plaintext.encode()

        try:
            # crypto_aead_xchacha20poly1305_ietf_encrypt retourne ciphertext + tag
            ciphertext_with_tag = crypto_aead_xchacha20poly1305_ietf_encrypt(
                plaintext, None, nonce, key
            )
            # Tag est les 16 derniers bytes
            ciphertext = ciphertext_with_tag[:-16]
            tag = ciphertext_with_tag[-16:]
            return ciphertext, tag, nonce
        except Exception as e:
            print_fail(f"Encryption error: {e}")
            return None, None, None

    @staticmethod
    def decrypt_xchacha20(key, ciphertext, tag, nonce):
        """Déchiffre avec XChaCha20-Poly1305"""
        if not NACL_AVAILABLE:
            return None

        try:
            # Combiner ciphertext + tag
            ciphertext_with_tag = ciphertext + tag
            plaintext = crypto_aead_xchacha20poly1305_ietf_decrypt(
                ciphertext_with_tag, None, nonce, key
            )
            return plaintext
        except Exception as e:
            # Erreur d'authentification (tag invalide)
            return None

    @staticmethod
    def wrap_key(key_to_wrap, wrapping_key):
        """Wrap une clé avec XOR + HMAC"""
        if len(key_to_wrap) != 32 or len(wrapping_key) != 32:
            return None, None

        # XOR wrap
        wrapped = bytes(a ^ b for a, b in zip(key_to_wrap, wrapping_key))

        # HMAC-SHA256 pour intégrité
        tag = hmac.new(wrapping_key, wrapped, hashlib.sha256).digest()

        return wrapped, tag

    @staticmethod
    def unwrap_key(wrapped_key, tag, wrapping_key):
        """Unwrap une clé et vérifie HMAC"""
        if len(wrapped_key) != 32 or len(wrapping_key) != 32:
            return None

        # Vérifier HMAC
        expected_tag = hmac.new(wrapping_key, wrapped_key, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            return None  # Tag invalide

        # XOR unwrap
        unwrapped = bytes(a ^ b for a, b in zip(wrapped_key, wrapping_key))

        return unwrapped

    @staticmethod
    def derive_key_hkdf(input_key, salt, info, length=32):
        """Dérive une clé avec HKDF-SHA256 (simplifié)"""
        # HKDF-Extract
        prk = hmac.new(salt, input_key, hashlib.sha256).digest()

        # HKDF-Expand (simplifié pour 32 bytes)
        okm = hmac.new(prk, info + b'\x01', hashlib.sha256).digest()

        return okm[:length]


class HSMTester:
    def __init__(self, port, hsm_id):
        self.port = port
        self.hsm_id = hsm_id
        self.serial = None
        self.results = {}
        self.crypto = SymmetricCrypto()

        # Clés générées
        self.mk = None
        self.dek = None
        self.wrapping_key = None

    def connect(self):
        try:
            self.serial = serial.Serial(self.port, BAUDRATE, timeout=TIMEOUT)
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            return True
        except Exception as e:
            print_fail(f"Connexion impossible: {e}")
            return False

    def disconnect(self):
        if self.serial:
            self.serial.close()
            self.serial = None

    def send_command(self, cmd, wait_time=0.5, read_timeout=3):
        if not self.serial:
            return None
        self.serial.reset_input_buffer()
        if isinstance(cmd, str):
            cmd = cmd.encode()
        self.serial.write(cmd)
        time.sleep(wait_time)

        start = time.time()
        response = b''
        while (time.time() - start) < read_timeout:
            if self.serial.in_waiting > 0:
                response += self.serial.read(self.serial.in_waiting)
                time.sleep(0.1)
            else:
                if response:
                    break
                time.sleep(0.1)
        return response

    def init_hsm(self):
        print_info("Initialisation HSM...")
        self.send_command(CMD_OFF, wait_time=0.5)
        resp = self.send_command(CMD_ON, wait_time=4, read_timeout=5)
        if not resp:
            print_fail("Timeout ON")
            return False
        time.sleep(0.5)
        self.serial.reset_input_buffer()
        resp = self.send_command(CMD_SELECT_CC, wait_time=1.5)
        if not resp or b'9000' not in resp:
            print_fail("Échec SELECT")
            return False
        resp = self.send_command(CMD_VERIFY_PIN, wait_time=1)
        if not resp or b'9000' not in resp:
            print_fail("Échec VERIFY PIN")
            return False
        print_ok("HSM initialisé et authentifié")
        return True

    def write_binary(self, offset, data):
        if isinstance(data, str):
            data = bytes.fromhex(data)
        length = len(data)
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF
        apdu = f"A 00D0{offset_high:02X}{offset_low:02X}{length:02X}{data.hex().upper()}\r\n"
        response = self.send_command(apdu, wait_time=2.5, read_timeout=4)
        if response and b'9000' in response:
            return True
        return False

    def read_binary(self, offset, length):
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF
        apdu = f"A 00B0{offset_high:02X}{offset_low:02X}{length:02X}\r\n"
        response = self.send_command(apdu, wait_time=0.5, read_timeout=2)

        if response and b'9000' in response:
            resp_str = response.decode('utf-8', errors='ignore')
            lines = resp_str.strip().split('\n')
            for line in reversed(lines):
                line = line.strip()
                if line == '9000':
                    continue
                clean = ''.join(c for c in line if c in '0123456789ABCDEFabcdef')
                if len(clean) >= length * 2:
                    return bytes.fromhex(clean[:length * 2])
        return None

    # ==================== TESTS ====================

    def test_4_1_generate_mk(self):
        """Test 4.1: Générer MK (Master Key)"""
        print_info("Génération Master Key (32 bytes aléatoires)...")

        self.mk = self.crypto.generate_key(32)

        if self.mk and len(self.mk) == 32:
            print_ok(f"MK générée: {len(self.mk)} bytes")
            print_data("Master Key", self.mk)
            self.results['4.1'] = True
            return True
        else:
            print_fail("Échec génération MK")
            self.results['4.1'] = False
            return False

    def test_4_2_store_mk(self):
        """Test 4.2: Stocker MK dans HSM"""
        if not self.mk:
            print_fail("Pas de MK à stocker")
            self.results['4.2'] = False
            return False

        print_info(f"Stockage MK (32 bytes) @ 0x{OFFSET_MK:04X}")

        if self.write_binary(OFFSET_MK, self.mk):
            print_ok("MK stockée dans HSM")

            # Vérification
            read_mk = self.read_binary(OFFSET_MK, 32)
            if read_mk == self.mk:
                print_ok("Vérification: MK intègre")
                self.results['4.2'] = True
                return True
            else:
                print_fail("Vérification: MK corrompue!")
        else:
            print_fail("Échec stockage MK")

        self.results['4.2'] = False
        return False

    def test_4_3_generate_dek(self):
        """Test 4.3: Générer DEK (Data Encryption Key)"""
        print_info("Génération Data Encryption Key (32 bytes)...")

        self.dek = self.crypto.generate_key(32)

        if self.dek and len(self.dek) == 32:
            print_ok(f"DEK générée: {len(self.dek)} bytes")
            print_data("DEK", self.dek)
            self.results['4.3'] = True
            return True
        else:
            print_fail("Échec génération DEK")
            self.results['4.3'] = False
            return False

    def test_4_4_store_dek(self):
        """Test 4.4: Stocker DEK dans HSM"""
        if not self.dek:
            print_fail("Pas de DEK à stocker")
            self.results['4.4'] = False
            return False

        print_info(f"Stockage DEK (32 bytes) @ 0x{OFFSET_DEK:04X}")

        if self.write_binary(OFFSET_DEK, self.dek):
            print_ok("DEK stockée dans HSM")

            # Vérification
            read_dek = self.read_binary(OFFSET_DEK, 32)
            if read_dek == self.dek:
                print_ok("Vérification: DEK intègre")
                self.results['4.4'] = True
                return True
            else:
                print_fail("Vérification: DEK corrompue!")
        else:
            print_fail("Échec stockage DEK")

        self.results['4.4'] = False
        return False

    def test_4_5_encrypt(self):
        """Test 4.5: Chiffrement XChaCha20-Poly1305"""
        if not NACL_AVAILABLE:
            print_fail("PyNaCl non disponible")
            self.results['4.5'] = False
            return False

        if not self.dek:
            print_fail("Pas de DEK")
            self.results['4.5'] = False
            return False

        # Message de test (commande MAVLink typique)
        plaintext = b"SET_MODE GUIDED | ARM THROTTLE | TAKEOFF 10"
        print_info("Message à chiffrer:")
        print_data("Plaintext", plaintext.decode())

        # Chiffrement
        ciphertext, tag, nonce = self.crypto.encrypt_xchacha20(self.dek, plaintext)

        if ciphertext and tag and nonce:
            print_ok("Chiffrement réussi!")
            print_data("Nonce (24B)", nonce)
            print_data("Ciphertext", ciphertext)
            print_data("TAG (16B)", tag)

            # Sauvegarder pour test suivant
            self.last_ciphertext = ciphertext
            self.last_tag = tag
            self.last_nonce = nonce
            self.last_plaintext = plaintext

            self.results['4.5'] = True
            return True
        else:
            print_fail("Échec chiffrement")
            self.results['4.5'] = False
            return False

    def test_4_6_decrypt(self):
        """Test 4.6: Déchiffrement XChaCha20-Poly1305"""
        if not hasattr(self, 'last_ciphertext'):
            print_fail("Pas de ciphertext à déchiffrer")
            self.results['4.6'] = False
            return False

        print_info("Déchiffrement...")

        decrypted = self.crypto.decrypt_xchacha20(
            self.dek,
            self.last_ciphertext,
            self.last_tag,
            self.last_nonce
        )

        if decrypted:
            print_ok("Déchiffrement réussi!")
            print_data("Decrypted", decrypted.decode())

            if decrypted == self.last_plaintext:
                print_ok("Message original récupéré identique!")
                self.results['4.6'] = True
                return True
            else:
                print_fail("Message différent de l'original!")
        else:
            print_fail("Échec déchiffrement")

        self.results['4.6'] = False
        return False

    def test_4_7_integrity(self):
        """Test 4.7: Test intégrité (TAG)"""
        if not hasattr(self, 'last_ciphertext'):
            print_fail("Pas de ciphertext")
            self.results['4.7'] = False
            return False

        print_info("Test 1: Déchiffrement avec TAG correct...")
        decrypted = self.crypto.decrypt_xchacha20(
            self.dek, self.last_ciphertext, self.last_tag, self.last_nonce
        )
        if decrypted:
            print_ok("TAG correct: déchiffrement OK")
        else:
            print_fail("Échec inattendu")
            self.results['4.7'] = False
            return False

        print_info("Test 2: Déchiffrement avec ciphertext MODIFIÉ...")
        modified_ct = bytearray(self.last_ciphertext)
        modified_ct[0] ^= 0xFF  # Modifier 1 byte
        decrypted_bad = self.crypto.decrypt_xchacha20(
            self.dek, bytes(modified_ct), self.last_tag, self.last_nonce
        )
        if decrypted_bad is None:
            print_ok("Ciphertext modifié: REJETÉ (correct!)")
        else:
            print_fail("Ciphertext modifié accepté (ERREUR SÉCURITÉ!)")
            self.results['4.7'] = False
            return False

        print_info("Test 3: Déchiffrement avec TAG MODIFIÉ...")
        modified_tag = bytearray(self.last_tag)
        modified_tag[0] ^= 0xFF
        decrypted_bad2 = self.crypto.decrypt_xchacha20(
            self.dek, self.last_ciphertext, bytes(modified_tag), self.last_nonce
        )
        if decrypted_bad2 is None:
            print_ok("TAG modifié: REJETÉ (correct!)")
        else:
            print_fail("TAG modifié accepté (ERREUR SÉCURITÉ!)")
            self.results['4.7'] = False
            return False

        print_info("Test 4: Déchiffrement avec MAUVAISE clé...")
        fake_key = self.crypto.generate_key(32)
        decrypted_bad3 = self.crypto.decrypt_xchacha20(
            fake_key, self.last_ciphertext, self.last_tag, self.last_nonce
        )
        if decrypted_bad3 is None:
            print_ok("Mauvaise clé: REJETÉ (correct!)")
        else:
            print_fail("Mauvaise clé acceptée (ERREUR SÉCURITÉ!)")
            self.results['4.7'] = False
            return False

        self.results['4.7'] = True
        return True

    def test_4_8_wrap_dek(self):
        """Test 4.8: Wrap DEK (XOR + HMAC)"""
        if not self.dek or not self.mk:
            print_fail("DEK ou MK manquante")
            self.results['4.8'] = False
            return False

        print_info("Dérivation Wrapping Key depuis MK (HKDF)...")
        salt = b"ArduPilot-HSM-Salt-2026"
        info = b"DEK-Wrapping-Key-v1"
        self.wrapping_key = self.crypto.derive_key_hkdf(self.mk, salt, info)
        print_data("Wrapping Key", self.wrapping_key)

        print_info("Wrapping DEK (XOR + HMAC-SHA256)...")
        wrapped_dek, tag = self.crypto.wrap_key(self.dek, self.wrapping_key)

        if wrapped_dek and tag:
            print_ok("DEK wrappée!")
            print_data("Wrapped DEK", wrapped_dek)
            print_data("HMAC Tag", tag)

            # Stocker dans HSM
            print_info("Stockage wrapped DEK et tag dans HSM...")
            if self.write_binary(OFFSET_WRAPPED_DEK, wrapped_dek):
                print_ok(f"Wrapped DEK stockée @ 0x{OFFSET_WRAPPED_DEK:04X}")
            else:
                print_fail("Échec stockage wrapped DEK")
                self.results['4.8'] = False
                return False

            time.sleep(0.3)

            if self.write_binary(OFFSET_DEK_TAG, tag):
                print_ok(f"HMAC Tag stocké @ 0x{OFFSET_DEK_TAG:04X}")
            else:
                print_fail("Échec stockage tag")
                self.results['4.8'] = False
                return False

            self.wrapped_dek = wrapped_dek
            self.dek_tag = tag
            self.results['4.8'] = True
            return True
        else:
            print_fail("Échec wrapping")
            self.results['4.8'] = False
            return False

    def test_4_9_unwrap_dek(self):
        """Test 4.9: Unwrap DEK"""
        if not hasattr(self, 'wrapped_dek') or not self.wrapping_key:
            print_fail("Wrapped DEK ou wrapping key manquante")
            self.results['4.9'] = False
            return False

        print_info("Lecture wrapped DEK et tag depuis HSM...")
        read_wrapped = self.read_binary(OFFSET_WRAPPED_DEK, 32)
        read_tag = self.read_binary(OFFSET_DEK_TAG, 32)

        if not read_wrapped or not read_tag:
            print_fail("Échec lecture depuis HSM")
            self.results['4.9'] = False
            return False

        print_data("Wrapped DEK (lue)", read_wrapped)
        print_data("HMAC Tag (lu)", read_tag)

        print_info("Unwrapping DEK...")
        unwrapped_dek = self.crypto.unwrap_key(read_wrapped, read_tag, self.wrapping_key)

        if unwrapped_dek:
            print_ok("Unwrap réussi!")
            print_data("DEK récupérée", unwrapped_dek)

            if unwrapped_dek == self.dek:
                print_ok("DEK IDENTIQUE à l'originale!")
                self.results['4.9'] = True
                return True
            else:
                print_fail("DEK différente de l'originale!")
        else:
            print_fail("Échec unwrap (HMAC invalide?)")

        # Test avec tag modifié
        print_info("Test: Unwrap avec tag MODIFIÉ (doit échouer)...")
        bad_tag = bytearray(read_tag)
        bad_tag[0] ^= 0xFF
        bad_unwrap = self.crypto.unwrap_key(read_wrapped, bytes(bad_tag), self.wrapping_key)
        if bad_unwrap is None:
            print_ok("Tag modifié: REJETÉ (correct!)")
        else:
            print_warn("Tag modifié accepté (problème!)")

        self.results['4.9'] = False
        return False

    def run_all_tests(self):
        """Exécute tous les tests de la Phase A4"""
        print_hsm(self.hsm_id, self.port)

        if not self.connect():
            return self.results

        try:
            if not self.init_hsm():
                print_fail("Impossible d'initialiser le HSM")
                return self.results

            print_test("4.1", "Générer MK (Master Key)")
            self.test_4_1_generate_mk()

            print_test("4.2", "Stocker MK dans HSM")
            self.test_4_2_store_mk()

            print_test("4.3", "Générer DEK (Data Encryption Key)")
            self.test_4_3_generate_dek()

            print_test("4.4", "Stocker DEK dans HSM")
            self.test_4_4_store_dek()

            print_test("4.5", "Chiffrement XChaCha20-Poly1305")
            self.test_4_5_encrypt()

            print_test("4.6", "Déchiffrement XChaCha20-Poly1305")
            self.test_4_6_decrypt()

            print_test("4.7", "Test intégrité (TAG)")
            self.test_4_7_integrity()

            print_test("4.8", "Wrap DEK (XOR + HMAC)")
            self.test_4_8_wrap_dek()

            print_test("4.9", "Unwrap DEK")
            self.test_4_9_unwrap_dek()

        finally:
            self.disconnect()

        return self.results


def print_summary(results_all):
    print_header("RÉSUMÉ DES TESTS - Phase A4")

    tests = [
        ('4.1', 'Générer MK'),
        ('4.2', 'Stocker MK dans HSM'),
        ('4.3', 'Générer DEK'),
        ('4.4', 'Stocker DEK dans HSM'),
        ('4.5', 'Chiffrement XChaCha20'),
        ('4.6', 'Déchiffrement XChaCha20'),
        ('4.7', 'Test intégrité (TAG)'),
        ('4.8', 'Wrap DEK'),
        ('4.9', 'Unwrap DEK'),
    ]

    print(f"\n{'Test':<8} {'Description':<30} {'HSM #1':<12} {'HSM #2':<12}")
    print("-" * 65)

    for test_id, desc in tests:
        hsm1_result = results_all.get('HSM1', {}).get(test_id, None)
        hsm2_result = results_all.get('HSM2', {}).get(test_id, None)

        hsm1_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm1_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm1_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"
        hsm2_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm2_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm2_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"

        print(f"{test_id:<8} {desc:<30} {hsm1_str:<20} {hsm2_str:<20}")

    for hsm_name, results in results_all.items():
        passed = sum(1 for v in results.values() if v is True)
        failed = sum(1 for v in results.values() if v is False)
        total = len(tests)
        print(f"\n{hsm_name}: {passed}/{total} tests passés", end="")
        if failed > 0:
            print(f" ({Colors.RED}{failed} échecs{Colors.ENDC})")
        else:
            print(f" ({Colors.GREEN}Tous OK!{Colors.ENDC})")


def main():
    print_header("Phase A4: Tests Clés Symétriques (ChaCha20/DEK)")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"HSM testés: {', '.join(HSM_PORTS)}")

    if not NACL_AVAILABLE:
        print(f"\n{Colors.RED}ERREUR: Bibliothèque 'pynacl' requise!{Colors.ENDC}")
        print(f"Installation: pip install pynacl")
        return 1

    print(f"\n{Colors.YELLOW}Algorithmes testés:{Colors.ENDC}")
    print(f"  - XChaCha20-Poly1305 (AEAD)")
    print(f"  - HKDF-SHA256 (dérivation)")
    print(f"  - HMAC-SHA256 (intégrité)")

    results_all = {}

    for idx, port in enumerate(HSM_PORTS, 1):
        print_header(f"Tests HSM #{idx} sur {port}")

        tester = HSMTester(port, idx)
        results = tester.run_all_tests()
        results_all[f'HSM{idx}'] = results

        if idx < len(HSM_PORTS):
            print(f"\n{Colors.CYAN}Pause 3s avant prochain HSM...{Colors.ENDC}")
            time.sleep(3)

    print_summary(results_all)

    all_passed = all(
        all(v for v in results.values() if v is not None)
        for results in results_all.values()
    )

    print("\n" + "=" * 60)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}Phase A4 COMPLÈTE - Tous les tests passés!{Colors.ENDC}")
        print(f"{Colors.GREEN}Les clés symétriques fonctionnent sur les deux HSM.{Colors.ENDC}")
        print(f"\n→ Prêt pour Phase A5: Hiérarchie MK→WK→DEK")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Phase A4 INCOMPLÈTE - Certains tests ont échoué{Colors.ENDC}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
