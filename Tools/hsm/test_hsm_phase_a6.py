#!/usr/bin/env python3
"""
Phase A6: Stress Tests HSM
===========================
Teste les limites des HSM sous charge intensive.

Tests:
  6.1 Latence baseline (10 READ)
  6.2 Burst WRITE rapide (20 ops)
  6.3 Burst READ rapide (50 ops)
  6.4 Alternance WRITE/READ (30 cycles)
  6.5 Endurance longue (100 cycles)
  6.6 Détection seuil d'erreur
  6.7 Récupération après erreur
  6.8 Test PIN répété
  6.9 Performance globale
"""

import serial
import time
import sys
import os
import statistics
from datetime import datetime

# Configuration
HSM_PORTS = ['/dev/ttyUSB0', '/dev/ttyUSB3']
HSM_NAMES = ['DRONE', 'GCS']
BAUDRATE = 115200
TIMEOUT = 3

# APDU Commands
CMD_OFF = b'off\r\n'
CMD_ON = b'on\r\n'
CMD_SELECT_CC = b'A 00A4040006010203040601\r\n'
CMD_VERIFY_PIN = b'A 00200001083030303030303030\r\n'

# Test offsets (éviter les zones critiques)
TEST_OFFSET = 0x0200  # Zone de test stress

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

def print_hsm(hsm_name, port):
    print(f"{Colors.BLUE}  HSM {hsm_name} ({port}):{Colors.ENDC}")

def print_ok(message):
    print(f"    {Colors.GREEN}✓ {message}{Colors.ENDC}")

def print_fail(message):
    print(f"    {Colors.RED}✗ {message}{Colors.ENDC}")

def print_warn(message):
    print(f"    {Colors.YELLOW}⚠ {message}{Colors.ENDC}")

def print_info(message):
    print(f"    {Colors.CYAN}→ {message}{Colors.ENDC}")

def print_stats(label, times_ms):
    """Affiche les statistiques d'une série de mesures"""
    if not times_ms:
        print(f"    {Colors.YELLOW}{label}: Aucune donnée{Colors.ENDC}")
        return

    avg = statistics.mean(times_ms)
    min_t = min(times_ms)
    max_t = max(times_ms)

    if len(times_ms) >= 2:
        std = statistics.stdev(times_ms)
        print(f"    {Colors.YELLOW}{label}:{Colors.ENDC}")
        print(f"      Moyenne: {avg:.1f}ms | Min: {min_t:.1f}ms | Max: {max_t:.1f}ms | StdDev: {std:.1f}ms")
    else:
        print(f"    {Colors.YELLOW}{label}: {avg:.1f}ms{Colors.ENDC}")


class HSMStressTester:
    def __init__(self, port, hsm_name):
        self.port = port
        self.hsm_name = hsm_name
        self.serial = None
        self.results = {}
        self.error_count = 0
        self.total_ops = 0

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

    def send_command(self, cmd, wait_time=0.3, read_timeout=2):
        """Envoie une commande et mesure le temps de réponse"""
        if not self.serial:
            return None, 0

        self.serial.reset_input_buffer()

        start = time.time()
        self.serial.write(cmd)
        time.sleep(wait_time)

        response = b''
        read_start = time.time()
        while (time.time() - read_start) < read_timeout:
            if self.serial.in_waiting > 0:
                response += self.serial.read(self.serial.in_waiting)
                time.sleep(0.05)
            else:
                if response:
                    break
                time.sleep(0.05)

        elapsed = (time.time() - start) * 1000  # ms
        self.total_ops += 1

        return response, elapsed

    def write_binary(self, offset, data):
        """WRITE BINARY avec timing"""
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF
        length = len(data)
        apdu = f"A 00D0{offset_high:02X}{offset_low:02X}{length:02X}{data.hex().upper()}\r\n"
        return self.send_command(apdu.encode(), wait_time=0.5, read_timeout=3)

    def read_binary(self, offset, length):
        """READ BINARY avec timing"""
        offset_high = (offset >> 8) & 0xFF
        offset_low = offset & 0xFF
        apdu = f"A 00B0{offset_high:02X}{offset_low:02X}{length:02X}\r\n"
        return self.send_command(apdu.encode(), wait_time=0.3, read_timeout=2)

    def check_success(self, response):
        """Vérifie si la réponse est un succès (9000)"""
        if response is None:
            return False
        return b'9000' in response

    def init_hsm(self):
        """Initialise le HSM (OFF, ON, SELECT, PIN)"""
        print_info("Initialisation HSM...")

        # OFF
        self.send_command(CMD_OFF, wait_time=0.5)

        # ON
        resp, _ = self.send_command(CMD_ON, wait_time=4, read_timeout=5)
        if not resp:
            print_fail("ON timeout")
            return False

        # SELECT
        resp, _ = self.send_command(CMD_SELECT_CC, wait_time=1.5)
        if not self.check_success(resp):
            print_fail("SELECT failed")
            return False

        # VERIFY PIN
        resp, _ = self.send_command(CMD_VERIFY_PIN, wait_time=1)
        if not self.check_success(resp):
            print_fail("VERIFY PIN failed")
            return False

        print_ok("HSM initialisé")
        return True

    # ==================== TESTS ====================

    def test_6_1_baseline_latency(self):
        """Test 6.1: Mesure de la latence baseline"""
        print_info("Mesure latence READ (10 lectures)...")

        times = []
        successes = 0

        for i in range(10):
            resp, elapsed = self.read_binary(TEST_OFFSET, 16)
            times.append(elapsed)
            if self.check_success(resp):
                successes += 1

        self.results['6.1'] = successes == 10
        print_stats("Latence READ", times)
        print_ok(f"{successes}/10 lectures réussies")

        return times

    def test_6_2_burst_write(self):
        """Test 6.2: Burst WRITE rapide (20 écritures)"""
        print_info("Burst WRITE (20 écritures consécutives)...")

        times = []
        successes = 0
        errors = []

        for i in range(20):
            data = bytes([i % 256] * 16)  # Pattern différent à chaque fois
            offset = TEST_OFFSET + (i * 16)

            resp, elapsed = self.write_binary(offset, data)
            times.append(elapsed)

            if self.check_success(resp):
                successes += 1
            else:
                errors.append((i, resp))
                self.error_count += 1

        self.results['6.2'] = successes >= 18  # 90% minimum
        print_stats("Latence WRITE", times)
        print_ok(f"{successes}/20 écritures réussies")

        if errors:
            print_warn(f"{len(errors)} erreurs détectées")
            for idx, resp in errors[:3]:  # Afficher max 3
                resp_str = resp.decode('utf-8', errors='ignore')[:50] if resp else "None"
                print_warn(f"  Op {idx}: {resp_str}")

        return times

    def test_6_3_burst_read(self):
        """Test 6.3: Burst READ rapide (50 lectures)"""
        print_info("Burst READ (50 lectures consécutives)...")

        times = []
        successes = 0

        for i in range(50):
            offset = TEST_OFFSET + ((i % 20) * 16)
            resp, elapsed = self.read_binary(offset, 16)
            times.append(elapsed)

            if self.check_success(resp):
                successes += 1
            else:
                self.error_count += 1

        self.results['6.3'] = successes >= 45  # 90% minimum
        print_stats("Latence READ", times)
        print_ok(f"{successes}/50 lectures réussies")

        return times

    def test_6_4_alternating(self):
        """Test 6.4: Alternance WRITE/READ (30 cycles)"""
        print_info("Alternance WRITE/READ (30 cycles)...")

        write_times = []
        read_times = []
        data_matches = 0

        for i in range(30):
            # WRITE
            data = bytes([i % 256] * 8)
            offset = TEST_OFFSET + 0x100 + (i * 8)

            resp_w, time_w = self.write_binary(offset, data)
            write_times.append(time_w)

            if not self.check_success(resp_w):
                self.error_count += 1
                continue

            # READ immédiat
            resp_r, time_r = self.read_binary(offset, 8)
            read_times.append(time_r)

            if self.check_success(resp_r):
                # Vérifier les données
                try:
                    resp_str = resp_r.decode('utf-8', errors='ignore')
                    if data.hex().upper() in resp_str.upper():
                        data_matches += 1
                except:
                    pass

        self.results['6.4'] = data_matches >= 27  # 90%
        print_stats("Latence WRITE", write_times)
        print_stats("Latence READ", read_times)
        print_ok(f"{data_matches}/30 cycles avec données correctes")

        return write_times, read_times

    def test_6_5_endurance(self):
        """Test 6.5: Endurance longue (100 cycles)"""
        print_info("Test d'endurance (100 cycles WRITE+READ)...")

        successes = 0
        errors_by_phase = {'early': 0, 'mid': 0, 'late': 0}
        times = []

        for i in range(100):
            # Phase classification
            if i < 33:
                phase = 'early'
            elif i < 66:
                phase = 'mid'
            else:
                phase = 'late'

            # WRITE
            data = bytes([(i * 7) % 256] * 4)
            offset = TEST_OFFSET + 0x200 + (i % 50) * 4

            start = time.time()
            resp_w, _ = self.write_binary(offset, data)
            resp_r, _ = self.read_binary(offset, 4)
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)

            if self.check_success(resp_w) and self.check_success(resp_r):
                successes += 1
            else:
                errors_by_phase[phase] += 1
                self.error_count += 1

            # Progress indicator tous les 25
            if (i + 1) % 25 == 0:
                print_info(f"  Progress: {i+1}/100 ({successes} OK)")

        self.results['6.5'] = successes >= 90  # 90%
        print_stats("Latence cycle", times)
        print_ok(f"{successes}/100 cycles réussis")

        if any(errors_by_phase.values()):
            print_info(f"Erreurs par phase: early={errors_by_phase['early']}, mid={errors_by_phase['mid']}, late={errors_by_phase['late']}")

        return successes

    def test_6_6_error_threshold(self):
        """Test 6.6: Détection seuil d'erreur (opérations très rapides)"""
        print_info("Détection seuil d'erreur (ops ultra-rapides)...")

        # Réduire progressivement le délai entre opérations
        delays = [0.2, 0.1, 0.05, 0.02, 0.01]
        results_by_delay = {}

        for delay in delays:
            successes = 0
            for i in range(10):
                resp, _ = self.read_binary(TEST_OFFSET, 8)
                if self.check_success(resp):
                    successes += 1
                time.sleep(delay)

            results_by_delay[delay] = successes
            status = "OK" if successes >= 8 else "DEGRADED" if successes >= 5 else "FAIL"
            print_info(f"  Délai {delay*1000:.0f}ms: {successes}/10 ({status})")

        # Trouver le seuil
        threshold = None
        for delay in delays:
            if results_by_delay[delay] < 8:
                threshold = delay
                break

        if threshold:
            print_warn(f"Seuil d'erreur détecté: délai < {threshold*1000:.0f}ms")
            self.results['6.6'] = True
        else:
            print_ok("Aucun seuil d'erreur détecté (HSM robuste)")
            self.results['6.6'] = True

        return results_by_delay

    def test_6_7_recovery(self):
        """Test 6.7: Récupération après erreur"""
        print_info("Test de récupération après timeout forcé...")

        # Forcer un timeout en utilisant un très court read_timeout
        old_timeout = self.serial.timeout
        self.serial.timeout = 0.001  # 1ms - va échouer

        # Essayer une opération qui va échouer
        self.serial.reset_input_buffer()
        self.serial.write(b'A 00B0020010\r\n')
        time.sleep(0.001)
        failed_resp = self.serial.read(100)

        # Restaurer timeout normal
        self.serial.timeout = old_timeout
        time.sleep(0.5)  # Pause pour récupération

        # Vider le buffer
        self.serial.reset_input_buffer()

        # Test de récupération
        recovery_success = 0
        for i in range(5):
            resp, _ = self.read_binary(TEST_OFFSET, 8)
            if self.check_success(resp):
                recovery_success += 1
            time.sleep(0.3)

        self.results['6.7'] = recovery_success >= 4

        if recovery_success >= 4:
            print_ok(f"Récupération réussie: {recovery_success}/5 ops OK après erreur")
        else:
            print_fail(f"Récupération partielle: {recovery_success}/5 ops OK")

        return recovery_success

    def test_6_8_pin_stress(self):
        """Test 6.8: Stress test PIN (vérifications répétées)"""
        print_info("Stress test VERIFY PIN (20 vérifications)...")

        times = []
        successes = 0

        for i in range(20):
            resp, elapsed = self.send_command(CMD_VERIFY_PIN, wait_time=0.5, read_timeout=2)
            times.append(elapsed)

            if self.check_success(resp):
                successes += 1

        self.results['6.8'] = successes == 20
        print_stats("Latence VERIFY PIN", times)
        print_ok(f"{successes}/20 vérifications PIN réussies")

        return times

    def test_6_9_performance_summary(self):
        """Test 6.9: Résumé de performance globale"""
        print_info("Calcul des métriques de performance...")

        # Mesurer throughput réel
        start = time.time()
        ops_count = 0

        # 10 secondes de test
        test_duration = 5  # secondes
        while (time.time() - start) < test_duration:
            resp, _ = self.read_binary(TEST_OFFSET, 16)
            if self.check_success(resp):
                ops_count += 1

        elapsed = time.time() - start
        throughput = ops_count / elapsed

        print_info(f"Throughput: {throughput:.1f} ops/sec")
        print_info(f"Total ops session: {self.total_ops}")
        print_info(f"Erreurs totales: {self.error_count}")

        error_rate = (self.error_count / self.total_ops * 100) if self.total_ops > 0 else 0
        print_info(f"Taux d'erreur: {error_rate:.2f}%")

        self.results['6.9'] = error_rate < 5  # Moins de 5% d'erreurs

        if error_rate < 1:
            print_ok("Performance excellente (< 1% erreurs)")
        elif error_rate < 5:
            print_ok("Performance acceptable (< 5% erreurs)")
        else:
            print_warn(f"Performance dégradée ({error_rate:.1f}% erreurs)")

        return throughput, error_rate

    def run_all_tests(self):
        """Exécute tous les tests de stress"""
        print_hsm(self.hsm_name, self.port)

        if not self.connect():
            return self.results

        try:
            if not self.init_hsm():
                return self.results

            self.test_6_1_baseline_latency()
            self.test_6_2_burst_write()
            self.test_6_3_burst_read()
            self.test_6_4_alternating()
            self.test_6_5_endurance()
            self.test_6_6_error_threshold()
            self.test_6_7_recovery()
            self.test_6_8_pin_stress()
            self.test_6_9_performance_summary()

        finally:
            self.disconnect()

        return self.results


def print_summary(results_all):
    """Affiche le résumé des tests"""
    print_header("RÉSUMÉ DES TESTS - Phase A6 Stress")

    tests = [
        ('6.1', 'Latence baseline'),
        ('6.2', 'Burst WRITE (20 ops)'),
        ('6.3', 'Burst READ (50 ops)'),
        ('6.4', 'Alternance W/R (30 cycles)'),
        ('6.5', 'Endurance (100 cycles)'),
        ('6.6', 'Seuil d\'erreur'),
        ('6.7', 'Récupération'),
        ('6.8', 'Stress PIN'),
        ('6.9', 'Performance globale')
    ]

    print(f"\n{'Test':<8} {'Description':<25} {'DRONE':<12} {'GCS':<12}")
    print("-" * 60)

    for test_id, desc in tests:
        drone_result = results_all.get('DRONE', {}).get(test_id, None)
        gcs_result = results_all.get('GCS', {}).get(test_id, None)

        drone_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if drone_result else f"{Colors.RED}FAIL{Colors.ENDC}" if drone_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"
        gcs_str = f"{Colors.GREEN}PASS{Colors.ENDC}" if gcs_result else f"{Colors.RED}FAIL{Colors.ENDC}" if gcs_result is False else f"{Colors.YELLOW}N/A{Colors.ENDC}"

        print(f"{test_id:<8} {desc:<25} {drone_str:<20} {gcs_str:<20}")

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
    print_header("Phase A6: Stress Tests HSM")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"HSM testés: DRONE ({HSM_PORTS[0]}), GCS ({HSM_PORTS[1]})")
    print(f"{Colors.YELLOW}⚠ Ce test peut prendre plusieurs minutes{Colors.ENDC}")

    results_all = {}

    for idx, (port, name) in enumerate(zip(HSM_PORTS, HSM_NAMES)):
        print_test(f"A6.{idx+1}", f"Stress Tests HSM {name}")

        tester = HSMStressTester(port, name)
        results = tester.run_all_tests()
        results_all[name] = results

        if idx < len(HSM_PORTS) - 1:
            print(f"\n{Colors.CYAN}Pause 3s avant prochain HSM...{Colors.ENDC}")
            time.sleep(3)

    print_summary(results_all)

    # Conclusion
    all_passed = all(
        all(v for v in results.values())
        for results in results_all.values()
        if results
    )

    print("\n" + "=" * 60)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}Phase A6 COMPLÈTE - Stress tests passés!{Colors.ENDC}")
        print(f"{Colors.GREEN}Les deux HSM sont robustes sous charge.{Colors.ENDC}")
        print(f"\n→ Prêt pour Phase B: Tests d'Intégration ArduPilot")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}Phase A6 COMPLÈTE avec avertissements{Colors.ENDC}")
        print(f"{Colors.YELLOW}Vérifiez les résultats ci-dessus.{Colors.ENDC}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
