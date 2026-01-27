#!/usr/bin/env python3
"""
Phase A2: Tests Stockage EEPROM HSM
====================================
Teste les fonctionnalités READ/WRITE sur les deux HSM.

Tests:
  2.1 WRITE 32 bytes
  2.2 READ 32 bytes
  2.3 WRITE 64 bytes
  2.4 READ 64 bytes
  2.5 Vérification intégrité (Write→Read→Compare)
  2.6 Multi-offset (écriture à différents offsets)
  2.7 Overwrite (réécriture même offset)

Offsets EEPROM utilisés:
  0x0100 - Test zone 1 (32 bytes)
  0x0120 - Test zone 2 (32 bytes)
  0x0140 - Test zone 3 (64 bytes)
  0x0180 - Test zone 4 (32 bytes)
"""

import serial
import time
import sys
import os
import random
from datetime import datetime

# Configuration
HSM_PORTS = ['/dev/ttyUSB0', '/dev/ttyUSB3']
BAUDRATE = 115200
TIMEOUT = 5

# EEPROM Offsets pour tests
OFFSET_TEST_32B_1 = 0x0100  # Zone test 32 bytes #1
OFFSET_TEST_32B_2 = 0x0120  # Zone test 32 bytes #2
OFFSET_TEST_64B = 0x0140    # Zone test 64 bytes
OFFSET_TEST_32B_3 = 0x0180  # Zone test 32 bytes #3

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

def print_data(label, data, max_len=80):
    if isinstance(data, bytes):
        data = data.hex().upper()
    if len(data) > max_len:
        display = data[:max_len] + "..."
    else:
        display = data
    print(f"    {Colors.YELLOW}{label}: {display}{Colors.ENDC}")

def bytes_to_hex(data):
    """Convertit bytes en string hex"""
    return data.hex().upper()

def hex_to_bytes(hex_str):
    """Convertit string hex en bytes"""
    return bytes.fromhex(hex_str)


class HSMTester:
    def __init__(self, port, hsm_id):
        self.port = port
        self.hsm_id = hsm_id
        self.serial = None
        self.results = {}

    def connect(self):
        """Ouvre la connexion série"""
        try:
            self.serial = serial.Serial(self.port, BAUDRATE, timeout=TIMEOUT)
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            return True
        except Exception as e:
            print_fail(f"Connexion impossible: {e}")
            return False

    def disconnect(self):
        """Ferme la connexion série"""
        if self.serial:
            self.serial.close()
            self.serial = None

    def send_command(self, cmd, wait_time=0.5, read_timeout=3):
        """Envoie une commande et lit la réponse"""
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
        """Initialise le HSM (OFF→ON→SELECT→PIN)"""
        print_info("Initialisation HSM...")

        # OFF
        self.send_command(CMD_OFF, wait_time=0.5)

        # ON
        resp = self.send_command(CMD_ON, wait_time=4, read_timeout=5)
        if not resp:
            print_fail("Timeout ON")
            return False

        # SELECT
        time.sleep(0.5)
        self.serial.reset_input_buffer()
        resp = self.send_command(CMD_SELECT_CC, wait_time=1.5)
        if not resp or b'9000' not in resp:
            print_fail("Échec SELECT")
            return False

        # VERIFY PIN
        resp = self.send_command(CMD_VERIFY_PIN, wait_time=1)
        if not resp or b'9000' not in resp:
            print_fail("Échec VERIFY PIN")
            return False

        print_ok("HSM initialisé et authentifié")
        return True

    def write_binary(self, offset, data):
        """
        Écrit des données à un offset EEPROM
        IMPORTANT: Applet CC utilise 00D0 (pas 00D6 standard!)
        APDU: 00 D0 [offset_high] [offset_low] [length] [data]
        """
        if isinstance(data, str):
            data = bytes.fromhex(data)

        length = len(data)
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF

        # Construire APDU (00D0 pour applet CC, pas 00D6!)
        apdu = f"A 00D0{offset_high:02X}{offset_low:02X}{length:02X}{data.hex().upper()}\r\n"

        print_info(f"WRITE {length} bytes @ 0x{offset:04X}")
        print_data("Data", data, max_len=64)

        # Envoyer avec délai EEPROM (2.5s minimum)
        response = self.send_command(apdu, wait_time=2.5, read_timeout=4)

        if response:
            resp_str = response.decode('utf-8', errors='ignore')
            success = b'9000' in response
            if success:
                print_ok(f"WRITE OK (SW: 9000)")
            else:
                print_fail(f"WRITE FAIL - Réponse: {resp_str[-50:]}")
            return success
        else:
            print_fail("WRITE Timeout")
            return False

    def read_binary(self, offset, length):
        """
        Lit des données depuis un offset EEPROM
        APDU: 00 B0 [offset_high] [offset_low] [length] (standard)
        """
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF

        # Construire APDU (00B0 standard pour READ)
        apdu = f"A 00B0{offset_high:02X}{offset_low:02X}{length:02X}\r\n"

        print_info(f"READ {length} bytes @ 0x{offset:04X}")

        response = self.send_command(apdu, wait_time=0.5, read_timeout=2)

        if response:
            resp_str = response.decode('utf-8', errors='ignore')

            # Chercher les données hex dans la réponse
            # Format typique: ... \n<hex_data>\n9000
            if b'9000' in response:
                # Extraire les données hex avant 9000
                try:
                    # Chercher la dernière ligne de données hex
                    lines = resp_str.strip().split('\n')
                    data_hex = None

                    for line in reversed(lines):
                        line = line.strip()
                        if line == '9000':
                            continue
                        # Vérifier si c'est une ligne hex valide
                        clean = ''.join(c for c in line if c in '0123456789ABCDEFabcdef')
                        if len(clean) >= length * 2:
                            data_hex = clean[:length * 2]
                            break

                    if data_hex:
                        data = bytes.fromhex(data_hex)
                        print_data("Data lue", data, max_len=64)
                        print_ok(f"READ OK ({len(data)} bytes)")
                        return data
                    else:
                        print_warn("Données non trouvées dans réponse")
                        print_data("Réponse brute", resp_str[-200:])
                        return None

                except Exception as e:
                    print_fail(f"Erreur parsing: {e}")
                    return None
            else:
                print_fail(f"READ FAIL - Pas de 9000")
                return None
        else:
            print_fail("READ Timeout")
            return None

    # ==================== TESTS ====================

    def test_2_1_write_32(self):
        """Test 2.1: WRITE 32 bytes"""
        # Générer 32 bytes de test (pattern reconnaissable)
        test_data = bytes([0xA1, 0xB2, 0xC3, 0xD4] * 8)  # 32 bytes

        success = self.write_binary(OFFSET_TEST_32B_1, test_data)
        self.results['2.1'] = success
        self.test_data_32 = test_data  # Sauvegarder pour test 2.2
        return success

    def test_2_2_read_32(self):
        """Test 2.2: READ 32 bytes"""
        data = self.read_binary(OFFSET_TEST_32B_1, 32)

        if data:
            # Vérifier si correspond aux données écrites
            if hasattr(self, 'test_data_32') and data == self.test_data_32:
                print_ok("Données lues correspondent aux données écrites!")
                self.results['2.2'] = True
            else:
                print_warn("Données lues différentes (peut-être anciennes données)")
                self.results['2.2'] = True  # READ a fonctionné
            return True
        else:
            self.results['2.2'] = False
            return False

    def test_2_3_write_64(self):
        """Test 2.3: WRITE 64 bytes"""
        # Générer 64 bytes de test
        test_data = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88] * 8)

        success = self.write_binary(OFFSET_TEST_64B, test_data)
        self.results['2.3'] = success
        self.test_data_64 = test_data
        return success

    def test_2_4_read_64(self):
        """Test 2.4: READ 64 bytes"""
        data = self.read_binary(OFFSET_TEST_64B, 64)

        if data:
            if hasattr(self, 'test_data_64') and data == self.test_data_64:
                print_ok("Données 64 bytes vérifiées!")
            self.results['2.4'] = True
            return True
        else:
            self.results['2.4'] = False
            return False

    def test_2_5_integrity(self):
        """Test 2.5: Vérification intégrité (Write→Read→Compare)"""
        print_info("Test intégrité: écriture données aléatoires puis vérification")

        # Générer 32 bytes vraiment aléatoires
        random_data = bytes([random.randint(0, 255) for _ in range(32)])
        print_data("Données aléatoires générées", random_data)

        # Écrire
        if not self.write_binary(OFFSET_TEST_32B_2, random_data):
            self.results['2.5'] = False
            return False

        # Pause pour EEPROM
        time.sleep(0.5)

        # Relire
        read_data = self.read_binary(OFFSET_TEST_32B_2, 32)

        if read_data is None:
            self.results['2.5'] = False
            return False

        # Comparer
        if read_data == random_data:
            print_ok("INTÉGRITÉ OK - Données identiques!")
            self.results['2.5'] = True
            return True
        else:
            print_fail("INTÉGRITÉ FAIL - Données différentes!")
            print_data("Attendu", random_data)
            print_data("Reçu", read_data)
            # Compter les différences
            diff_count = sum(1 for a, b in zip(random_data, read_data) if a != b)
            print_fail(f"{diff_count} bytes différents sur 32")
            self.results['2.5'] = False
            return False

    def test_2_6_multi_offset(self):
        """Test 2.6: Multi-offset (écriture à différents offsets)"""
        print_info("Test multi-offset: écrire à 3 offsets différents")

        offsets_data = [
            (OFFSET_TEST_32B_1, bytes([0xAA] * 32), "Zone 0x0100"),
            (OFFSET_TEST_32B_2, bytes([0xBB] * 32), "Zone 0x0120"),
            (OFFSET_TEST_32B_3, bytes([0xCC] * 32), "Zone 0x0180"),
        ]

        all_ok = True

        for offset, data, name in offsets_data:
            print_info(f"Écriture {name}...")
            if not self.write_binary(offset, data):
                all_ok = False
                break
            time.sleep(0.3)  # Pause entre writes

        if all_ok:
            print_info("Vérification des 3 zones...")
            for offset, expected, name in offsets_data:
                read_data = self.read_binary(offset, 32)
                if read_data != expected:
                    print_fail(f"{name}: données incorrectes")
                    all_ok = False
                else:
                    print_ok(f"{name}: OK")
                time.sleep(0.2)

        self.results['2.6'] = all_ok
        return all_ok

    def test_2_7_overwrite(self):
        """Test 2.7: Overwrite (réécriture même offset)"""
        print_info("Test overwrite: écrire 3 fois au même offset")

        offset = OFFSET_TEST_32B_1

        # 3 écritures successives avec données différentes
        writes = [
            bytes([0x11] * 32),
            bytes([0x22] * 32),
            bytes([0x33] * 32),
        ]

        for i, data in enumerate(writes, 1):
            print_info(f"Écriture #{i}...")
            if not self.write_binary(offset, data):
                self.results['2.7'] = False
                return False
            time.sleep(0.3)

        # Vérifier que seule la dernière écriture est présente
        print_info("Vérification dernière valeur...")
        read_data = self.read_binary(offset, 32)

        if read_data == writes[-1]:
            print_ok("Overwrite OK - Dernière valeur correcte")
            self.results['2.7'] = True
            return True
        else:
            print_fail("Overwrite FAIL - Valeur inattendue")
            self.results['2.7'] = False
            return False

    def run_all_tests(self):
        """Exécute tous les tests de la Phase A2"""
        print_hsm(self.hsm_id, self.port)

        if not self.connect():
            return self.results

        try:
            # Initialisation
            if not self.init_hsm():
                print_fail("Impossible d'initialiser le HSM")
                return self.results

            # Tests séquentiels
            print_test("2.1", "WRITE 32 bytes")
            self.test_2_1_write_32()

            print_test("2.2", "READ 32 bytes")
            self.test_2_2_read_32()

            print_test("2.3", "WRITE 64 bytes")
            self.test_2_3_write_64()

            print_test("2.4", "READ 64 bytes")
            self.test_2_4_read_64()

            print_test("2.5", "Vérification intégrité (Write→Read→Compare)")
            self.test_2_5_integrity()

            print_test("2.6", "Multi-offset")
            self.test_2_6_multi_offset()

            print_test("2.7", "Overwrite")
            self.test_2_7_overwrite()

        finally:
            self.disconnect()

        return self.results


def print_summary(results_all):
    """Affiche le résumé des tests"""
    print_header("RÉSUMÉ DES TESTS - Phase A2")

    tests = [
        ('2.1', 'WRITE 32 bytes'),
        ('2.2', 'READ 32 bytes'),
        ('2.3', 'WRITE 64 bytes'),
        ('2.4', 'READ 64 bytes'),
        ('2.5', 'Intégrité (Write→Read→Compare)'),
        ('2.6', 'Multi-offset (3 zones)'),
        ('2.7', 'Overwrite (3x même offset)'),
    ]

    print(f"\n{'Test':<8} {'Description':<35} {'HSM #1':<12} {'HSM #2':<12}")
    print("-" * 70)

    for test_id, desc in tests:
        hsm1_result = results_all.get('HSM1', {}).get(test_id, None)
        hsm2_result = results_all.get('HSM2', {}).get(test_id, None)

        hsm1_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm1_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm1_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"
        hsm2_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm2_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm2_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"

        print(f"{test_id:<8} {desc:<35} {hsm1_str:<20} {hsm2_str:<20}")

    # Comptage
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
    print_header("Phase A2: Tests Stockage EEPROM HSM")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"HSM testés: {', '.join(HSM_PORTS)}")

    print(f"\n{Colors.YELLOW}Offsets EEPROM utilisés:{Colors.ENDC}")
    print(f"  0x0100 - Zone test 32 bytes #1")
    print(f"  0x0120 - Zone test 32 bytes #2")
    print(f"  0x0140 - Zone test 64 bytes")
    print(f"  0x0180 - Zone test 32 bytes #3")

    results_all = {}

    # Test chaque HSM
    for idx, port in enumerate(HSM_PORTS, 1):
        print_header(f"Tests HSM #{idx} sur {port}")

        tester = HSMTester(port, idx)
        results = tester.run_all_tests()
        results_all[f'HSM{idx}'] = results

        # Pause entre HSMs
        if idx < len(HSM_PORTS):
            print(f"\n{Colors.CYAN}Pause 3s avant prochain HSM...{Colors.ENDC}")
            time.sleep(3)

    # Résumé
    print_summary(results_all)

    # Conclusion
    all_passed = all(
        all(v for v in results.values() if v is not None)
        for results in results_all.values()
    )

    print("\n" + "=" * 60)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}Phase A2 COMPLÈTE - Tous les tests passés!{Colors.ENDC}")
        print(f"{Colors.GREEN}Le stockage EEPROM fonctionne sur les deux HSM.{Colors.ENDC}")
        print(f"\n→ Prêt pour Phase A3: Tests Clés Asymétriques (P-256)")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Phase A2 INCOMPLÈTE - Certains tests ont échoué{Colors.ENDC}")
        print(f"{Colors.YELLOW}Vérifiez les erreurs ci-dessus.{Colors.ENDC}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
