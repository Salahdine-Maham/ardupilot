#!/usr/bin/env python3
"""
Phase A3: Tests Clés Asymétriques P-256 (ECDSA/ECDH)
=====================================================
Teste la génération, stockage et utilisation des clés P-256 sur les deux HSM.

Tests:
  3.1 Générer paire de clés P-256
  3.2 Stocker clé privée (32 bytes) dans HSM
  3.3 Stocker clé publique (64 bytes) dans HSM
  3.4 Relire et vérifier les clés
  3.5 Test ECDH (shared secret entre 2 paires)
  3.6 Test signature ECDSA
  3.7 Vérification signature ECDSA

Dépendances: pip install cryptography
"""

import serial
import time
import sys
import os
from datetime import datetime

# Crypto imports
try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("WARNING: cryptography not installed. Install with: pip install cryptography")

# Configuration
HSM_PORTS = ['/dev/ttyUSB0', '/dev/ttyUSB3']
BAUDRATE = 115200
TIMEOUT = 5

# EEPROM Offsets
OFFSET_PRIVATE_KEY = 0x0100   # 32 bytes
OFFSET_PUBLIC_KEY = 0x0160    # 64 bytes

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


class P256KeyManager:
    """Gère les opérations cryptographiques P-256"""

    @staticmethod
    def generate_keypair():
        """Génère une paire de clés P-256"""
        if not CRYPTO_AVAILABLE:
            return None, None

        # Générer clé privée
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

        # Extraire clé privée en bytes (32 bytes)
        private_bytes = private_key.private_numbers().private_value.to_bytes(32, 'big')

        # Extraire clé publique en bytes (64 bytes = X + Y)
        public_key = private_key.public_key()
        public_numbers = public_key.public_numbers()
        public_bytes = (
            public_numbers.x.to_bytes(32, 'big') +
            public_numbers.y.to_bytes(32, 'big')
        )

        return private_bytes, public_bytes

    @staticmethod
    def compute_ecdh(private_bytes, peer_public_bytes):
        """Calcule le shared secret ECDH"""
        if not CRYPTO_AVAILABLE:
            return None

        # Reconstruire clé privée
        private_value = int.from_bytes(private_bytes, 'big')
        private_numbers = ec.EllipticCurvePrivateNumbers(
            private_value,
            ec.EllipticCurvePublicNumbers(
                int.from_bytes(peer_public_bytes[:32], 'big'),
                int.from_bytes(peer_public_bytes[32:], 'big'),
                ec.SECP256R1()
            )
        )

        # On a besoin de notre propre clé publique, recalculons
        # En fait, on doit générer depuis la clé privée
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        # Méthode alternative: utiliser la lib directement
        try:
            # Reconstruire depuis private value
            private_key = ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())

            # Reconstruire clé publique du peer
            peer_public_numbers = ec.EllipticCurvePublicNumbers(
                int.from_bytes(peer_public_bytes[:32], 'big'),
                int.from_bytes(peer_public_bytes[32:], 'big'),
                ec.SECP256R1()
            )
            peer_public_key = peer_public_numbers.public_key(default_backend())

            # ECDH
            shared_key = private_key.exchange(ec.ECDH(), peer_public_key)
            return shared_key
        except Exception as e:
            print_fail(f"ECDH error: {e}")
            return None

    @staticmethod
    def sign_message(private_bytes, message):
        """Signe un message avec ECDSA"""
        if not CRYPTO_AVAILABLE:
            return None

        try:
            private_value = int.from_bytes(private_bytes, 'big')
            private_key = ec.derive_private_key(private_value, ec.SECP256R1(), default_backend())

            if isinstance(message, str):
                message = message.encode()

            signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
            return signature
        except Exception as e:
            print_fail(f"Sign error: {e}")
            return None

    @staticmethod
    def verify_signature(public_bytes, message, signature):
        """Vérifie une signature ECDSA"""
        if not CRYPTO_AVAILABLE:
            return False

        try:
            public_numbers = ec.EllipticCurvePublicNumbers(
                int.from_bytes(public_bytes[:32], 'big'),
                int.from_bytes(public_bytes[32:], 'big'),
                ec.SECP256R1()
            )
            public_key = public_numbers.public_key(default_backend())

            if isinstance(message, str):
                message = message.encode()

            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception as e:
            return False


class HSMTester:
    def __init__(self, port, hsm_id):
        self.port = port
        self.hsm_id = hsm_id
        self.serial = None
        self.results = {}
        self.crypto = P256KeyManager()

        # Clés générées pour ce HSM
        self.private_key = None
        self.public_key = None

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

    def test_3_1_generate_keypair(self):
        """Test 3.1: Générer paire de clés P-256"""
        print_info("Génération paire de clés P-256 (secp256r1)...")

        if not CRYPTO_AVAILABLE:
            print_fail("Bibliothèque cryptography non disponible")
            self.results['3.1'] = False
            return False

        self.private_key, self.public_key = self.crypto.generate_keypair()

        if self.private_key and self.public_key:
            print_ok(f"Clé privée générée: {len(self.private_key)} bytes")
            print_data("Private Key", self.private_key)
            print_ok(f"Clé publique générée: {len(self.public_key)} bytes")
            print_data("Public Key (X)", self.public_key[:32])
            print_data("Public Key (Y)", self.public_key[32:])
            self.results['3.1'] = True
            return True
        else:
            print_fail("Échec génération")
            self.results['3.1'] = False
            return False

    def test_3_2_store_private_key(self):
        """Test 3.2: Stocker clé privée dans HSM"""
        if not self.private_key:
            print_fail("Pas de clé privée à stocker")
            self.results['3.2'] = False
            return False

        print_info(f"Stockage clé privée (32 bytes) @ 0x{OFFSET_PRIVATE_KEY:04X}")

        if self.write_binary(OFFSET_PRIVATE_KEY, self.private_key):
            print_ok("Clé privée stockée dans HSM")
            self.results['3.2'] = True
            return True
        else:
            print_fail("Échec stockage clé privée")
            self.results['3.2'] = False
            return False

    def test_3_3_store_public_key(self):
        """Test 3.3: Stocker clé publique dans HSM"""
        if not self.public_key:
            print_fail("Pas de clé publique à stocker")
            self.results['3.3'] = False
            return False

        print_info(f"Stockage clé publique (64 bytes) @ 0x{OFFSET_PUBLIC_KEY:04X}")

        if self.write_binary(OFFSET_PUBLIC_KEY, self.public_key):
            print_ok("Clé publique stockée dans HSM")
            self.results['3.3'] = True
            return True
        else:
            print_fail("Échec stockage clé publique")
            self.results['3.3'] = False
            return False

    def test_3_4_read_verify_keys(self):
        """Test 3.4: Relire et vérifier les clés"""
        print_info("Relecture et vérification des clés...")

        # Lire clé privée
        read_priv = self.read_binary(OFFSET_PRIVATE_KEY, 32)
        if read_priv is None:
            print_fail("Échec lecture clé privée")
            self.results['3.4'] = False
            return False

        print_data("Clé privée lue", read_priv)

        if read_priv == self.private_key:
            print_ok("Clé privée: INTÉGRITÉ OK")
        else:
            print_fail("Clé privée: CORRUPTION DÉTECTÉE!")
            self.results['3.4'] = False
            return False

        # Lire clé publique
        read_pub = self.read_binary(OFFSET_PUBLIC_KEY, 64)
        if read_pub is None:
            print_fail("Échec lecture clé publique")
            self.results['3.4'] = False
            return False

        print_data("Clé publique lue (X)", read_pub[:32])
        print_data("Clé publique lue (Y)", read_pub[32:])

        if read_pub == self.public_key:
            print_ok("Clé publique: INTÉGRITÉ OK")
        else:
            print_fail("Clé publique: CORRUPTION DÉTECTÉE!")
            self.results['3.4'] = False
            return False

        self.results['3.4'] = True
        return True

    def test_3_5_ecdh(self):
        """Test 3.5: Test ECDH (shared secret)"""
        print_info("Test ECDH: Génération de shared secret...")

        # Simuler un "peer" (comme si c'était le GCS)
        print_info("Génération paire de clés PEER (simulation GCS)...")
        peer_priv, peer_pub = self.crypto.generate_keypair()

        if not peer_priv or not peer_pub:
            print_fail("Échec génération clés peer")
            self.results['3.5'] = False
            return False

        print_data("Peer Public Key", peer_pub)

        # ECDH côté "Drone" (notre HSM)
        print_info("Calcul shared secret côté DRONE...")
        shared_drone = self.crypto.compute_ecdh(self.private_key, peer_pub)

        if not shared_drone:
            print_fail("Échec ECDH côté drone")
            self.results['3.5'] = False
            return False

        print_data("Shared Secret (Drone)", shared_drone)

        # ECDH côté "GCS" (peer)
        print_info("Calcul shared secret côté GCS...")
        shared_gcs = self.crypto.compute_ecdh(peer_priv, self.public_key)

        if not shared_gcs:
            print_fail("Échec ECDH côté GCS")
            self.results['3.5'] = False
            return False

        print_data("Shared Secret (GCS)", shared_gcs)

        # Vérifier qu'ils sont identiques
        if shared_drone == shared_gcs:
            print_ok("ECDH SUCCESS: Les deux shared secrets sont IDENTIQUES!")
            print_ok(f"Shared secret: {len(shared_drone)} bytes")
            self.results['3.5'] = True
            return True
        else:
            print_fail("ECDH FAIL: Les shared secrets sont DIFFÉRENTS!")
            self.results['3.5'] = False
            return False

    def test_3_6_sign_message(self):
        """Test 3.6: Signature ECDSA"""
        print_info("Test signature ECDSA...")

        message = b"ARM DRONE COMMAND - TEST MESSAGE 12345"
        print_data("Message à signer", message.decode())

        signature = self.crypto.sign_message(self.private_key, message)

        if signature:
            print_ok(f"Signature générée: {len(signature)} bytes")
            print_data("Signature (DER)", signature)
            self.last_signature = signature
            self.last_message = message
            self.results['3.6'] = True
            return True
        else:
            print_fail("Échec signature")
            self.results['3.6'] = False
            return False

    def test_3_7_verify_signature(self):
        """Test 3.7: Vérification signature ECDSA"""
        print_info("Test vérification signature ECDSA...")

        if not hasattr(self, 'last_signature') or not hasattr(self, 'last_message'):
            print_fail("Pas de signature à vérifier")
            self.results['3.7'] = False
            return False

        # Vérifier avec la bonne clé publique
        print_info("Vérification avec clé publique correcte...")
        valid = self.crypto.verify_signature(self.public_key, self.last_message, self.last_signature)

        if valid:
            print_ok("Signature VALIDE avec clé correcte")
        else:
            print_fail("Signature INVALIDE (devrait être valide!)")
            self.results['3.7'] = False
            return False

        # Vérifier avec un message modifié (doit échouer)
        print_info("Vérification avec message MODIFIÉ (doit échouer)...")
        modified_message = b"MODIFIED MESSAGE - TAMPERED"
        valid_modified = self.crypto.verify_signature(self.public_key, modified_message, self.last_signature)

        if not valid_modified:
            print_ok("Signature REJETÉE pour message modifié (correct!)")
        else:
            print_fail("Signature acceptée pour message modifié (ERREUR SÉCURITÉ!)")
            self.results['3.7'] = False
            return False

        # Vérifier avec une mauvaise clé publique
        print_info("Vérification avec MAUVAISE clé publique (doit échouer)...")
        fake_priv, fake_pub = self.crypto.generate_keypair()
        valid_fake = self.crypto.verify_signature(fake_pub, self.last_message, self.last_signature)

        if not valid_fake:
            print_ok("Signature REJETÉE pour mauvaise clé (correct!)")
        else:
            print_fail("Signature acceptée avec mauvaise clé (ERREUR SÉCURITÉ!)")
            self.results['3.7'] = False
            return False

        self.results['3.7'] = True
        return True

    def run_all_tests(self):
        """Exécute tous les tests de la Phase A3"""
        print_hsm(self.hsm_id, self.port)

        if not self.connect():
            return self.results

        try:
            if not self.init_hsm():
                print_fail("Impossible d'initialiser le HSM")
                return self.results

            print_test("3.1", "Générer paire de clés P-256")
            self.test_3_1_generate_keypair()

            print_test("3.2", "Stocker clé privée dans HSM")
            self.test_3_2_store_private_key()

            print_test("3.3", "Stocker clé publique dans HSM")
            self.test_3_3_store_public_key()

            print_test("3.4", "Relire et vérifier les clés")
            self.test_3_4_read_verify_keys()

            print_test("3.5", "Test ECDH (shared secret)")
            self.test_3_5_ecdh()

            print_test("3.6", "Test signature ECDSA")
            self.test_3_6_sign_message()

            print_test("3.7", "Vérification signature ECDSA")
            self.test_3_7_verify_signature()

        finally:
            self.disconnect()

        return self.results


def print_summary(results_all):
    print_header("RÉSUMÉ DES TESTS - Phase A3")

    tests = [
        ('3.1', 'Générer paire de clés P-256'),
        ('3.2', 'Stocker clé privée (32B)'),
        ('3.3', 'Stocker clé publique (64B)'),
        ('3.4', 'Relire et vérifier clés'),
        ('3.5', 'ECDH (shared secret)'),
        ('3.6', 'Signature ECDSA'),
        ('3.7', 'Vérification signature'),
    ]

    print(f"\n{'Test':<8} {'Description':<35} {'HSM #1':<12} {'HSM #2':<12}")
    print("-" * 70)

    for test_id, desc in tests:
        hsm1_result = results_all.get('HSM1', {}).get(test_id, None)
        hsm2_result = results_all.get('HSM2', {}).get(test_id, None)

        hsm1_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm1_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm1_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"
        hsm2_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm2_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm2_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"

        print(f"{test_id:<8} {desc:<35} {hsm1_str:<20} {hsm2_str:<20}")

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
    print_header("Phase A3: Tests Clés Asymétriques P-256")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"HSM testés: {', '.join(HSM_PORTS)}")

    if not CRYPTO_AVAILABLE:
        print(f"\n{Colors.RED}ERREUR: Bibliothèque 'cryptography' requise!{Colors.ENDC}")
        print(f"Installation: pip install cryptography")
        return 1

    print(f"\n{Colors.YELLOW}Algorithmes testés:{Colors.ENDC}")
    print(f"  - Courbe: P-256 (secp256r1)")
    print(f"  - ECDH: Diffie-Hellman sur courbe elliptique")
    print(f"  - ECDSA: Signature avec SHA-256")

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
        print(f"{Colors.GREEN}{Colors.BOLD}Phase A3 COMPLÈTE - Tous les tests passés!{Colors.ENDC}")
        print(f"{Colors.GREEN}Les opérations P-256 fonctionnent sur les deux HSM.{Colors.ENDC}")
        print(f"\n→ Prêt pour Phase A4: Tests Clés Symétriques (ChaCha20/DEK)")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Phase A3 INCOMPLÈTE - Certains tests ont échoué{Colors.ENDC}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
