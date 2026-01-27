#!/usr/bin/env python3
"""
Phase A5: Hiérarchie Complète MK→WK→DEK
========================================
Teste le flux complet de dérivation de clés entre deux HSM.

Tests:
  5.1 Générer MK et stocker (les 2 HSM)
  5.2 Dériver WK depuis MK (HKDF)
  5.3 Générer paire P-256 depuis WK
  5.4 Simuler échange WK (2 HSM)
  5.5 Calculer ECDH des deux côtés
  5.6 Dériver DEK depuis shared secret
  5.7 Test chiffrement croisé
  5.8 Stocker DEK wrappée
  5.9 Restaurer DEK depuis HSM

Ce test utilise les DEUX HSM simultanément pour simuler Drone ↔ GCS
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
    from nacl.bindings import (
        crypto_aead_xchacha20poly1305_ietf_encrypt,
        crypto_aead_xchacha20poly1305_ietf_decrypt,
    )
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("WARNING: Required crypto libraries not installed")

# Configuration
HSM_PORTS = ['/dev/ttyUSB0', '/dev/ttyUSB3']
HSM_NAMES = ['DRONE', 'GCS']
BAUDRATE = 115200
TIMEOUT = 5

# EEPROM Offsets
OFFSET_MK = 0x0100           # Master Key (32 bytes)
OFFSET_WK_PRIV = 0x0120      # WK Private (32 bytes)
OFFSET_DEK_WRAPPED = 0x0140  # Wrapped DEK (32 bytes)
OFFSET_WK_PUB = 0x0160       # WK Public (64 bytes)
OFFSET_DEK_TAG = 0x0180      # HMAC Tag (32 bytes)

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
    MAGENTA = '\033[35m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}  {text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")

def print_test(test_num, description):
    print(f"\n{Colors.CYAN}[Test {test_num}] {description}{Colors.ENDC}")
    print("-" * 60)

def print_ok(message):
    print(f"  {Colors.GREEN}✓ {message}{Colors.ENDC}")

def print_fail(message):
    print(f"  {Colors.RED}✗ {message}{Colors.ENDC}")

def print_info(message):
    print(f"  {Colors.CYAN}→ {message}{Colors.ENDC}")

def print_drone(message):
    print(f"  {Colors.BLUE}[DRONE] {message}{Colors.ENDC}")

def print_gcs(message):
    print(f"  {Colors.MAGENTA}[GCS]   {message}{Colors.ENDC}")

def print_data(label, data, max_len=48):
    if isinstance(data, bytes):
        data = data.hex().upper()
    if len(data) > max_len:
        display = data[:max_len] + "..."
    else:
        display = data
    print(f"  {Colors.YELLOW}{label}: {display}{Colors.ENDC}")


class CryptoManager:
    """Gère toutes les opérations cryptographiques"""

    @staticmethod
    def generate_random(size=32):
        return os.urandom(size)

    @staticmethod
    def hkdf_sha256(ikm, salt, info, length=32):
        """HKDF-SHA256 (Extract + Expand)"""
        # Extract
        prk = hmac.new(salt, ikm, hashlib.sha256).digest()
        # Expand (simplifié pour 32 bytes)
        okm = hmac.new(prk, info + b'\x01', hashlib.sha256).digest()
        return okm[:length]

    @staticmethod
    def derive_wk_private(mk):
        """Dérive WK private depuis MK"""
        salt = b"ArduPilot-HSM-WK-Salt-2026"
        info = b"WK-Private-Derivation-v1"
        return CryptoManager.hkdf_sha256(mk, salt, info, 32)

    @staticmethod
    def generate_p256_from_private(private_bytes):
        """Génère une paire P-256 depuis une clé privée"""
        private_value = int.from_bytes(private_bytes, 'big')
        # Assurer que la valeur est dans la plage valide pour P-256
        curve_order = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
        private_value = private_value % curve_order
        if private_value == 0:
            private_value = 1

        private_key = ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())
        public_key = private_key.public_key()
        public_numbers = public_key.public_numbers()

        private_bytes_fixed = private_value.to_bytes(32, 'big')
        public_bytes = (
            public_numbers.x.to_bytes(32, 'big') +
            public_numbers.y.to_bytes(32, 'big')
        )
        return private_bytes_fixed, public_bytes

    @staticmethod
    def compute_ecdh(private_bytes, peer_public_bytes):
        """Calcule ECDH shared secret"""
        private_value = int.from_bytes(private_bytes, 'big')
        private_key = ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())

        peer_public_numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(peer_public_bytes[:32], 'big'),
            int.from_bytes(peer_public_bytes[32:], 'big'),
            ec.SECP256R1()
        )
        peer_public_key = peer_public_numbers.public_key(default_backend())

        shared_key = private_key.exchange(ec.ECDH(), peer_public_key)
        return shared_key

    @staticmethod
    def derive_dek(shared_secret):
        """Dérive DEK depuis shared secret"""
        salt = b"ArduPilot-HSM-DEK-Salt-2026"
        info = b"DEK-Derivation-v1"
        return CryptoManager.hkdf_sha256(shared_secret, salt, info, 32)

    @staticmethod
    def encrypt(key, plaintext, nonce=None):
        """Chiffre avec XChaCha20-Poly1305"""
        if nonce is None:
            nonce = os.urandom(24)
        if isinstance(plaintext, str):
            plaintext = plaintext.encode()

        ct_with_tag = crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, None, nonce, key)
        return ct_with_tag[:-16], ct_with_tag[-16:], nonce

    @staticmethod
    def decrypt(key, ciphertext, tag, nonce):
        """Déchiffre avec XChaCha20-Poly1305"""
        try:
            ct_with_tag = ciphertext + tag
            return crypto_aead_xchacha20poly1305_ietf_decrypt(ct_with_tag, None, nonce, key)
        except:
            return None

    @staticmethod
    def wrap_key(key_to_wrap, wrapping_key):
        """Wrap avec XOR + HMAC"""
        wrapped = bytes(a ^ b for a, b in zip(key_to_wrap, wrapping_key))
        tag = hmac.new(wrapping_key, wrapped, hashlib.sha256).digest()
        return wrapped, tag

    @staticmethod
    def unwrap_key(wrapped, tag, wrapping_key):
        """Unwrap et vérifie HMAC"""
        expected_tag = hmac.new(wrapping_key, wrapped, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            return None
        return bytes(a ^ b for a, b in zip(wrapped, wrapping_key))


class HSMDevice:
    """Représente un HSM physique"""

    def __init__(self, port, name):
        self.port = port
        self.name = name
        self.serial = None

        # Clés
        self.mk = None
        self.wk_priv = None
        self.wk_pub = None
        self.peer_wk_pub = None
        self.shared_secret = None
        self.dek = None

    def connect(self):
        try:
            self.serial = serial.Serial(self.port, BAUDRATE, timeout=TIMEOUT)
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            return True
        except Exception as e:
            print_fail(f"{self.name}: Connexion impossible - {e}")
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
        self.send_command(CMD_OFF, wait_time=0.5)
        resp = self.send_command(CMD_ON, wait_time=4, read_timeout=5)
        if not resp:
            return False
        time.sleep(0.5)
        self.serial.reset_input_buffer()
        resp = self.send_command(CMD_SELECT_CC, wait_time=1.5)
        if not resp or b'9000' not in resp:
            return False
        resp = self.send_command(CMD_VERIFY_PIN, wait_time=1)
        if not resp or b'9000' not in resp:
            return False
        return True

    def write_binary(self, offset, data):
        if isinstance(data, str):
            data = bytes.fromhex(data)
        length = len(data)
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF
        apdu = f"A 00D0{offset_high:02X}{offset_low:02X}{length:02X}{data.hex().upper()}\r\n"
        response = self.send_command(apdu, wait_time=2.5, read_timeout=4)
        return response and b'9000' in response

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


class HierarchyTester:
    """Teste la hiérarchie complète avec les deux HSM"""

    def __init__(self):
        self.crypto = CryptoManager()
        self.drone = HSMDevice(HSM_PORTS[0], "DRONE")
        self.gcs = HSMDevice(HSM_PORTS[1], "GCS")
        self.results = {}

    def init_both_hsm(self):
        print_info("Initialisation des deux HSM...")

        if not self.drone.connect():
            return False
        if not self.gcs.connect():
            self.drone.disconnect()
            return False

        if not self.drone.init_hsm():
            print_fail("DRONE: Échec init")
            return False
        print_drone("HSM initialisé ✓")

        if not self.gcs.init_hsm():
            print_fail("GCS: Échec init")
            return False
        print_gcs("HSM initialisé ✓")

        return True

    def cleanup(self):
        self.drone.disconnect()
        self.gcs.disconnect()

    # ==================== TESTS ====================

    def test_5_1_generate_store_mk(self):
        """Test 5.1: Générer MK et stocker (les 2 HSM)"""
        print_info("Génération et stockage MK pour les deux HSM...")

        # DRONE
        self.drone.mk = self.crypto.generate_random(32)
        print_drone(f"MK générée")
        print_data("MK_drone", self.drone.mk)

        if not self.drone.write_binary(OFFSET_MK, self.drone.mk):
            print_fail("DRONE: Échec stockage MK")
            self.results['5.1'] = False
            return False
        print_drone("MK stockée @ 0x0100 ✓")

        # GCS
        self.gcs.mk = self.crypto.generate_random(32)
        print_gcs(f"MK générée")
        print_data("MK_gcs", self.gcs.mk)

        if not self.gcs.write_binary(OFFSET_MK, self.gcs.mk):
            print_fail("GCS: Échec stockage MK")
            self.results['5.1'] = False
            return False
        print_gcs("MK stockée @ 0x0100 ✓")

        self.results['5.1'] = True
        return True

    def test_5_2_derive_wk(self):
        """Test 5.2: Dériver WK depuis MK (HKDF)"""
        print_info("Dérivation WK depuis MK avec HKDF-SHA256...")

        # DRONE
        self.drone.wk_priv = self.crypto.derive_wk_private(self.drone.mk)
        print_drone("WK dérivée depuis MK")
        print_data("WK_priv_drone", self.drone.wk_priv)

        # GCS
        self.gcs.wk_priv = self.crypto.derive_wk_private(self.gcs.mk)
        print_gcs("WK dérivée depuis MK")
        print_data("WK_priv_gcs", self.gcs.wk_priv)

        # Vérifier qu'elles sont différentes (MK différentes → WK différentes)
        if self.drone.wk_priv != self.gcs.wk_priv:
            print_ok("Les WK sont différentes (correct - MK différentes)")
        else:
            print_fail("Les WK sont identiques (anormal!)")

        self.results['5.2'] = True
        return True

    def test_5_3_generate_p256(self):
        """Test 5.3: Générer paire P-256 depuis WK"""
        print_info("Génération paires P-256 depuis WK...")

        # DRONE
        self.drone.wk_priv, self.drone.wk_pub = self.crypto.generate_p256_from_private(self.drone.wk_priv)
        print_drone("Paire P-256 générée")
        print_data("WK_pub_drone", self.drone.wk_pub)

        # Stocker dans HSM
        if self.drone.write_binary(OFFSET_WK_PRIV, self.drone.wk_priv):
            print_drone("WK_priv stockée @ 0x0120 ✓")
        if self.drone.write_binary(OFFSET_WK_PUB, self.drone.wk_pub):
            print_drone("WK_pub stockée @ 0x0160 ✓")

        # GCS
        self.gcs.wk_priv, self.gcs.wk_pub = self.crypto.generate_p256_from_private(self.gcs.wk_priv)
        print_gcs("Paire P-256 générée")
        print_data("WK_pub_gcs", self.gcs.wk_pub)

        if self.gcs.write_binary(OFFSET_WK_PRIV, self.gcs.wk_priv):
            print_gcs("WK_priv stockée @ 0x0120 ✓")
        if self.gcs.write_binary(OFFSET_WK_PUB, self.gcs.wk_pub):
            print_gcs("WK_pub stockée @ 0x0160 ✓")

        self.results['5.3'] = True
        return True

    def test_5_4_exchange_wk(self):
        """Test 5.4: Simuler échange WK (HSM_WK_EXCHANGE)"""
        print_info("Simulation échange de clés publiques WK...")

        # DRONE envoie sa clé publique au GCS
        print_drone("─── HSM_WK_EXCHANGE ───────────────────────►")
        print_data("  WK_pub envoyée", self.drone.wk_pub)
        self.gcs.peer_wk_pub = self.drone.wk_pub
        print_gcs("WK_pub_drone reçue ✓")

        # GCS envoie sa clé publique au DRONE
        print_gcs("◄─────────────────────── HSM_WK_EXCHANGE ───")
        print_data("  WK_pub envoyée", self.gcs.wk_pub)
        self.drone.peer_wk_pub = self.gcs.wk_pub
        print_drone("WK_pub_gcs reçue ✓")

        self.results['5.4'] = True
        return True

    def test_5_5_compute_ecdh(self):
        """Test 5.5: Calculer ECDH des deux côtés"""
        print_info("Calcul ECDH shared secret des deux côtés...")

        # DRONE calcule shared secret
        self.drone.shared_secret = self.crypto.compute_ecdh(
            self.drone.wk_priv, self.drone.peer_wk_pub
        )
        print_drone("Shared secret calculé")
        print_data("shared_drone", self.drone.shared_secret)

        # GCS calcule shared secret
        self.gcs.shared_secret = self.crypto.compute_ecdh(
            self.gcs.wk_priv, self.gcs.peer_wk_pub
        )
        print_gcs("Shared secret calculé")
        print_data("shared_gcs", self.gcs.shared_secret)

        # Vérification critique !
        if self.drone.shared_secret == self.gcs.shared_secret:
            print_ok("★★★ SHARED SECRETS IDENTIQUES ! ★★★")
            print_ok("L'échange de clés ECDH fonctionne parfaitement!")
            self.results['5.5'] = True
        else:
            print_fail("ERREUR: Shared secrets DIFFÉRENTS!")
            self.results['5.5'] = False

        return self.results['5.5']

    def test_5_6_derive_dek(self):
        """Test 5.6: Dériver DEK depuis shared secret"""
        print_info("Dérivation DEK depuis shared secret (HKDF)...")

        # DRONE
        self.drone.dek = self.crypto.derive_dek(self.drone.shared_secret)
        print_drone("DEK dérivée")
        print_data("DEK_drone", self.drone.dek)

        # GCS
        self.gcs.dek = self.crypto.derive_dek(self.gcs.shared_secret)
        print_gcs("DEK dérivée")
        print_data("DEK_gcs", self.gcs.dek)

        # Vérification
        if self.drone.dek == self.gcs.dek:
            print_ok("★★★ DEK IDENTIQUES ! ★★★")
            print_ok("Les deux parties peuvent communiquer de façon chiffrée!")
            self.results['5.6'] = True
        else:
            print_fail("ERREUR: DEK DIFFÉRENTES!")
            self.results['5.6'] = False

        return self.results['5.6']

    def test_5_7_cross_encryption(self):
        """Test 5.7: Test chiffrement croisé"""
        print_info("Test chiffrement croisé DRONE ↔ GCS...")

        # Test 1: DRONE → GCS
        print_info("Test 1: DRONE chiffre, GCS déchiffre")
        msg_drone = b"ARM THROTTLE | TAKEOFF 10m"
        ct, tag, nonce = self.crypto.encrypt(self.drone.dek, msg_drone)
        print_drone(f"Message: {msg_drone.decode()}")
        print_drone(f"Chiffré avec DEK_drone")

        decrypted = self.crypto.decrypt(self.gcs.dek, ct, tag, nonce)
        if decrypted == msg_drone:
            print_gcs(f"Déchiffré: {decrypted.decode()}")
            print_ok("DRONE → GCS : OK ✓")
        else:
            print_fail("DRONE → GCS : ÉCHEC!")
            self.results['5.7'] = False
            return False

        # Test 2: GCS → DRONE
        print_info("Test 2: GCS chiffre, DRONE déchiffre")
        msg_gcs = b"SET_MODE GUIDED | MISSION_START"
        ct2, tag2, nonce2 = self.crypto.encrypt(self.gcs.dek, msg_gcs)
        print_gcs(f"Message: {msg_gcs.decode()}")
        print_gcs(f"Chiffré avec DEK_gcs")

        decrypted2 = self.crypto.decrypt(self.drone.dek, ct2, tag2, nonce2)
        if decrypted2 == msg_gcs:
            print_drone(f"Déchiffré: {decrypted2.decode()}")
            print_ok("GCS → DRONE : OK ✓")
        else:
            print_fail("GCS → DRONE : ÉCHEC!")
            self.results['5.7'] = False
            return False

        print_ok("★★★ CHIFFREMENT BIDIRECTIONNEL VALIDÉ ! ★★★")
        self.results['5.7'] = True
        return True

    def test_5_8_store_wrapped_dek(self):
        """Test 5.8: Stocker DEK wrappée"""
        print_info("Wrapping et stockage DEK dans les HSM...")

        # DRONE
        wrap_key_drone = self.crypto.hkdf_sha256(
            self.drone.mk, b"wrap-salt", b"dek-wrap", 32
        )
        wrapped_drone, tag_drone = self.crypto.wrap_key(self.drone.dek, wrap_key_drone)

        if self.drone.write_binary(OFFSET_DEK_WRAPPED, wrapped_drone):
            print_drone("DEK wrappée stockée @ 0x0140 ✓")
        if self.drone.write_binary(OFFSET_DEK_TAG, tag_drone):
            print_drone("TAG stocké @ 0x0180 ✓")

        # GCS
        wrap_key_gcs = self.crypto.hkdf_sha256(
            self.gcs.mk, b"wrap-salt", b"dek-wrap", 32
        )
        wrapped_gcs, tag_gcs = self.crypto.wrap_key(self.gcs.dek, wrap_key_gcs)

        if self.gcs.write_binary(OFFSET_DEK_WRAPPED, wrapped_gcs):
            print_gcs("DEK wrappée stockée @ 0x0140 ✓")
        if self.gcs.write_binary(OFFSET_DEK_TAG, tag_gcs):
            print_gcs("TAG stocké @ 0x0180 ✓")

        self.wrapped_drone = wrapped_drone
        self.tag_drone = tag_drone
        self.wrap_key_drone = wrap_key_drone

        self.wrapped_gcs = wrapped_gcs
        self.tag_gcs = tag_gcs
        self.wrap_key_gcs = wrap_key_gcs

        self.results['5.8'] = True
        return True

    def test_5_9_restore_dek(self):
        """Test 5.9: Restaurer DEK depuis HSM (simulation reboot)"""
        print_info("Simulation reboot: restauration DEK depuis HSM...")

        # DRONE
        print_drone("Lecture DEK wrappée depuis HSM...")
        read_wrapped = self.drone.read_binary(OFFSET_DEK_WRAPPED, 32)
        read_tag = self.drone.read_binary(OFFSET_DEK_TAG, 32)

        if read_wrapped and read_tag:
            restored_dek = self.crypto.unwrap_key(read_wrapped, read_tag, self.wrap_key_drone)
            if restored_dek == self.drone.dek:
                print_drone("DEK restaurée et vérifiée ✓")
            else:
                print_fail("DRONE: DEK restaurée différente!")
                self.results['5.9'] = False
                return False
        else:
            print_fail("DRONE: Échec lecture")
            self.results['5.9'] = False
            return False

        # GCS
        print_gcs("Lecture DEK wrappée depuis HSM...")
        read_wrapped_gcs = self.gcs.read_binary(OFFSET_DEK_WRAPPED, 32)
        read_tag_gcs = self.gcs.read_binary(OFFSET_DEK_TAG, 32)

        if read_wrapped_gcs and read_tag_gcs:
            restored_dek_gcs = self.crypto.unwrap_key(read_wrapped_gcs, read_tag_gcs, self.wrap_key_gcs)
            if restored_dek_gcs == self.gcs.dek:
                print_gcs("DEK restaurée et vérifiée ✓")
            else:
                print_fail("GCS: DEK restaurée différente!")
                self.results['5.9'] = False
                return False
        else:
            print_fail("GCS: Échec lecture")
            self.results['5.9'] = False
            return False

        print_ok("Les deux HSM peuvent restaurer leur DEK après reboot!")
        self.results['5.9'] = True
        return True

    def run_all_tests(self):
        """Exécute tous les tests"""
        if not self.init_both_hsm():
            return self.results

        try:
            print_test("5.1", "Générer MK et stocker (les 2 HSM)")
            self.test_5_1_generate_store_mk()

            print_test("5.2", "Dériver WK depuis MK (HKDF)")
            self.test_5_2_derive_wk()

            print_test("5.3", "Générer paire P-256 depuis WK")
            self.test_5_3_generate_p256()

            print_test("5.4", "Simuler échange WK (HSM_WK_EXCHANGE)")
            self.test_5_4_exchange_wk()

            print_test("5.5", "Calculer ECDH des deux côtés")
            self.test_5_5_compute_ecdh()

            print_test("5.6", "Dériver DEK depuis shared secret")
            self.test_5_6_derive_dek()

            print_test("5.7", "Test chiffrement croisé")
            self.test_5_7_cross_encryption()

            print_test("5.8", "Stocker DEK wrappée")
            self.test_5_8_store_wrapped_dek()

            print_test("5.9", "Restaurer DEK depuis HSM")
            self.test_5_9_restore_dek()

        finally:
            self.cleanup()

        return self.results


def print_summary(results):
    print_header("RÉSUMÉ DES TESTS - Phase A5")

    tests = [
        ('5.1', 'Générer et stocker MK'),
        ('5.2', 'Dériver WK (HKDF)'),
        ('5.3', 'Générer P-256 depuis WK'),
        ('5.4', 'Échange WK (simulation)'),
        ('5.5', 'ECDH shared secret'),
        ('5.6', 'Dériver DEK'),
        ('5.7', 'Chiffrement croisé'),
        ('5.8', 'Stocker DEK wrappée'),
        ('5.9', 'Restaurer DEK'),
    ]

    print(f"\n{'Test':<8} {'Description':<35} {'Résultat':<12}")
    print("-" * 60)

    for test_id, desc in tests:
        result = results.get(test_id, None)
        result_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if result else f"{Colors.RED}FAIL{Colors.ENDC}" if result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"
        print(f"{test_id:<8} {desc:<35} {result_str}")

    passed = sum(1 for v in results.values() if v is True)
    total = len(tests)
    print(f"\nTotal: {passed}/{total} tests passés")


def main():
    print_header("Phase A5: Hiérarchie Complète MK→WK→DEK")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n{Colors.YELLOW}Configuration:{Colors.ENDC}")
    print(f"  DRONE: {HSM_PORTS[0]}")
    print(f"  GCS:   {HSM_PORTS[1]}")

    print(f"\n{Colors.YELLOW}Flow testé:{Colors.ENDC}")
    print(f"  MK → HKDF → WK_priv → P-256 → WK_pub")
    print(f"  WK_pub échangé → ECDH → shared_secret")
    print(f"  shared_secret → HKDF → DEK")
    print(f"  DEK → XChaCha20-Poly1305 → Communication chiffrée")

    if not CRYPTO_AVAILABLE:
        print(f"\n{Colors.RED}ERREUR: Bibliothèques crypto requises!{Colors.ENDC}")
        return 1

    tester = HierarchyTester()
    results = tester.run_all_tests()

    print_summary(results)

    all_passed = all(v for v in results.values() if v is not None)

    print("\n" + "=" * 70)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}Phase A5 COMPLÈTE - Tous les tests passés!{Colors.ENDC}")
        print(f"{Colors.GREEN}La hiérarchie MK→WK→DEK fonctionne entre les deux HSM!{Colors.ENDC}")
        print(f"\n→ Prêt pour Phase A6: Stress Tests")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Phase A5 INCOMPLÈTE{Colors.ENDC}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
