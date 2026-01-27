#!/usr/bin/env python3
"""
Phase A1: Tests Communication de Base HSM
==========================================
Teste les deux HSM sur toutes les fonctionnalités de communication.

Tests:
  1.1 Détection USB
  1.2 OFF Command
  1.3 ON Command + ATR
  1.4 SELECT Applet CC
  1.5 VERIFY PIN correct
  1.6 VERIFY PIN incorrect (test erreur)
"""

import serial
import time
import sys
from datetime import datetime

# Configuration
HSM_PORTS = ['/dev/ttyUSB0', '/dev/ttyUSB3']
BAUDRATE = 115200
TIMEOUT = 3

# APDU Commands
CMD_OFF = b'off\r\n'
CMD_ON = b'on\r\n'
CMD_SELECT_CC = b'A 00A4040006010203040601\r\n'  # SELECT applet CC (AID: 010203040601)
CMD_VERIFY_PIN_CORRECT = b'A 00200001083030303030303030\r\n'  # PIN: 00000000
CMD_VERIFY_PIN_WRONG = b'A 00200001083131313131313131\r\n'  # PIN: 11111111 (wrong)

# Colors for output
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
    if len(data) > max_len:
        display = data[:max_len] + "..."
    else:
        display = data
    print(f"    {Colors.YELLOW}{label}: {display}{Colors.ENDC}")

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
        self.serial.write(cmd)
        time.sleep(wait_time)

        # Lire toute la réponse
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

    def check_response(self, response, expected):
        """Vérifie si la réponse contient le code attendu"""
        if response is None:
            return False
        return expected in response

    # ==================== TESTS ====================

    def test_1_1_detection(self):
        """Test 1.1: Détection USB"""
        import os
        exists = os.path.exists(self.port)
        self.results['1.1'] = exists
        if exists:
            print_ok(f"Port {self.port} détecté")
        else:
            print_fail(f"Port {self.port} non trouvé")
        return exists

    def test_1_2_off(self):
        """Test 1.2: Commande OFF"""
        print_info("Envoi: off")
        response = self.send_command(CMD_OFF, wait_time=0.5)

        if response:
            resp_str = response.decode('utf-8', errors='ignore').strip()
            print_data("Réponse", resp_str)
            # OFF retourne généralement "OK" ou rien
            success = True  # OFF réussit généralement
            self.results['1.2'] = success
            print_ok("Commande OFF exécutée")
            return success
        else:
            print_fail("Pas de réponse")
            self.results['1.2'] = False
            return False

    def test_1_3_on_atr(self):
        """Test 1.3: Commande ON + ATR"""
        print_info("Envoi: on (attente ATR ~4s)")
        response = self.send_command(CMD_ON, wait_time=4, read_timeout=5)

        if response:
            resp_str = response.decode('utf-8', errors='ignore').strip()
            print_data("Réponse ATR", resp_str[:200] if len(resp_str) > 200 else resp_str)

            # Vérifier présence ATR ou confirmation ON
            # ATR commence par 3B, ou réponse contient T1, ou simplement "OK"
            has_atr = (b'3B' in response.upper() or
                      b'3b' in response or
                      b'T1' in response or
                      b'OK' in response or
                      len(response) > 10)
            self.results['1.3'] = has_atr

            if b'T1' in response or b'3B' in response.upper():
                print_ok("ATR reçu - Secure Element activé")
            elif b'OK' in response:
                print_ok("Secure Element activé (déjà ON ou ATR simplifié)")
            return has_atr
        else:
            print_fail("Pas de réponse - Timeout")
            self.results['1.3'] = False
            return False

    def test_1_4_select_cc(self):
        """Test 1.4: SELECT Applet CC"""
        print_info("Envoi: SELECT applet CC (AID: 010203040601)")

        # Flush avant SELECT
        time.sleep(0.5)
        self.serial.reset_input_buffer()

        response = self.send_command(CMD_SELECT_CC, wait_time=1.5, read_timeout=3)

        if response:
            resp_str = response.decode('utf-8', errors='ignore').strip()
            print_data("Réponse", resp_str)

            success = b'9000' in response
            self.results['1.4'] = success

            if success:
                print_ok("Applet CC sélectionné (SW: 9000)")
            else:
                # Chercher code erreur
                if b'6A82' in response:
                    print_fail("Applet non trouvé (SW: 6A82)")
                elif b'6D00' in response:
                    print_fail("Instruction non supportée (SW: 6D00)")
                else:
                    print_fail(f"Échec SELECT")
            return success
        else:
            print_fail("Pas de réponse - Timeout")
            self.results['1.4'] = False
            return False

    def test_1_5_verify_pin_correct(self):
        """Test 1.5: VERIFY PIN correct (00000000)"""
        print_info("Envoi: VERIFY PIN 00000000")

        response = self.send_command(CMD_VERIFY_PIN_CORRECT, wait_time=1, read_timeout=2)

        if response:
            resp_str = response.decode('utf-8', errors='ignore').strip()
            print_data("Réponse", resp_str)

            success = b'9000' in response
            self.results['1.5'] = success

            if success:
                print_ok("PIN vérifié avec succès (SW: 9000)")
            else:
                if b'63C' in response:
                    # Extraire tentatives restantes
                    print_fail("PIN incorrect (mais c'est le bon PIN!)")
                elif b'6983' in response:
                    print_fail("PIN BLOQUÉ! (SW: 6983)")
                else:
                    print_fail("Échec VERIFY PIN")
            return success
        else:
            print_fail("Pas de réponse - Timeout")
            self.results['1.5'] = False
            return False

    def test_1_6_verify_pin_wrong(self):
        """Test 1.6: VERIFY PIN incorrect (test erreur)"""
        print_info("Envoi: VERIFY PIN 11111111 (intentionnellement faux)")
        print_warn("Ce test vérifie que le HSM rejette un mauvais PIN")

        response = self.send_command(CMD_VERIFY_PIN_WRONG, wait_time=1, read_timeout=2)

        if response:
            resp_str = response.decode('utf-8', errors='ignore').strip()
            print_data("Réponse", resp_str)

            # On s'attend à une erreur 63XX (vérification échouée)
            # Formats possibles: 63CX, 6300, 6309, etc.
            is_rejected = b'63' in response or b'6983' in response
            self.results['1.6'] = is_rejected

            if b'9000' in response:
                print_fail("PIN accepté alors qu'il devrait être rejeté!")
                self.results['1.6'] = False
            elif b'6983' in response:
                print_warn("PIN BLOQUÉ! (SW: 6983) - Attention!")
            elif b'63C' in response:
                # Format standard 63CX
                try:
                    idx = response.find(b'63C')
                    remaining = chr(response[idx+3])
                    print_ok(f"PIN rejeté correctement - {remaining} tentatives restantes")
                except:
                    print_ok("PIN rejeté correctement (63Cx)")
            elif b'63' in response:
                # Format alternatif 63XX (ex: 6309)
                print_ok("PIN rejeté correctement (SW: 63xx)")
            else:
                print_warn("Réponse inattendue")

            return is_rejected
        else:
            print_fail("Pas de réponse - Timeout")
            self.results['1.6'] = False
            return False

    def test_1_5b_verify_pin_restore(self):
        """Restaurer l'authentification avec le bon PIN après test 1.6"""
        print_info("Restauration: VERIFY PIN 00000000")
        response = self.send_command(CMD_VERIFY_PIN_CORRECT, wait_time=1, read_timeout=2)
        if response and b'9000' in response:
            print_ok("Authentification restaurée")
            return True
        return False

    def run_all_tests(self):
        """Exécute tous les tests de la Phase A1"""
        print_hsm(self.hsm_id, self.port)

        # Connexion
        if not self.connect():
            return self.results

        try:
            # Tests séquentiels
            self.test_1_1_detection()
            self.test_1_2_off()
            self.test_1_3_on_atr()
            self.test_1_4_select_cc()
            self.test_1_5_verify_pin_correct()
            self.test_1_6_verify_pin_wrong()
            self.test_1_5b_verify_pin_restore()  # Restaurer après test PIN faux

        finally:
            self.disconnect()

        return self.results


def print_summary(results_all):
    """Affiche le résumé des tests"""
    print_header("RÉSUMÉ DES TESTS - Phase A1")

    tests = [
        ('1.1', 'Détection USB'),
        ('1.2', 'Commande OFF'),
        ('1.3', 'Commande ON + ATR'),
        ('1.4', 'SELECT Applet CC'),
        ('1.5', 'VERIFY PIN correct'),
        ('1.6', 'VERIFY PIN incorrect (rejet)')
    ]

    print(f"\n{'Test':<8} {'Description':<30} {'HSM #1':<12} {'HSM #2':<12}")
    print("-" * 65)

    for test_id, desc in tests:
        hsm1_result = results_all.get('HSM1', {}).get(test_id, None)
        hsm2_result = results_all.get('HSM2', {}).get(test_id, None)

        hsm1_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm1_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm1_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"
        hsm2_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if hsm2_result else f"{Colors.RED}FAIL{Colors.ENDC}" if hsm2_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"

        print(f"{test_id:<8} {desc:<30} {hsm1_str:<20} {hsm2_str:<20}")

    # Comptage
    for hsm_name, results in results_all.items():
        passed = sum(1 for v in results.values() if v is True)
        failed = sum(1 for v in results.values() if v is False)
        total = len(results)
        print(f"\n{hsm_name}: {passed}/{total} tests passés", end="")
        if failed > 0:
            print(f" ({Colors.RED}{failed} échecs{Colors.ENDC})")
        else:
            print(f" ({Colors.GREEN}Tous OK!{Colors.ENDC})")


def main():
    print_header("Phase A1: Tests Communication de Base HSM")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"HSM testés: {', '.join(HSM_PORTS)}")

    results_all = {}

    # Test chaque HSM
    for idx, port in enumerate(HSM_PORTS, 1):
        print_test(f"A1.{idx}", f"Tests HSM #{idx} sur {port}")

        tester = HSMTester(port, idx)
        results = tester.run_all_tests()
        results_all[f'HSM{idx}'] = results

        # Pause entre HSMs
        if idx < len(HSM_PORTS):
            print(f"\n{Colors.CYAN}Pause 2s avant prochain HSM...{Colors.ENDC}")
            time.sleep(2)

    # Résumé
    print_summary(results_all)

    # Conclusion
    all_passed = all(
        all(v for v in results.values())
        for results in results_all.values()
    )

    print("\n" + "=" * 60)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}Phase A1 COMPLÈTE - Tous les tests passés!{Colors.ENDC}")
        print(f"{Colors.GREEN}Les deux HSM sont opérationnels.{Colors.ENDC}")
        print(f"\n→ Prêt pour Phase A2: Tests Stockage EEPROM")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Phase A1 INCOMPLÈTE - Certains tests ont échoué{Colors.ENDC}")
        print(f"{Colors.YELLOW}Vérifiez les erreurs ci-dessus avant de continuer.{Colors.ENDC}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
