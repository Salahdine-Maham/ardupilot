#!/usr/bin/env python3
"""
Script de test pour communiquer avec le LeMonolith HSM
Feature 1: Test d'initialisation et SELECT applet CC
"""

import sys
import time

# Fix import conflict between 'serial' package and 'pyserial'
sys.path.insert(0, '/usr/lib/python3/dist-packages')

# Import pyserial correctement
try:
    from serial import Serial, SerialException
except ImportError:
    print("Erreur: pyserial non installé. Installez avec: pip3 install pyserial")
    sys.exit(1)

# Configuration
PORT = '/dev/ttyUSB0'
BAUDRATE = 115200
TIMEOUT = 2  # secondes

# APDU Commands pour Application CC
APDU_SELECT_CC = '00A4040006010203040601'  # SELECT Application CC
APDU_VERIFY_PIN = '00200001043030303030'   # VERIFY PIN User: "0000"

def send_command(ser, cmd, description=""):
    """Envoie une commande et affiche la réponse"""
    print(f"\n{'='*60}")
    if description:
        print(f"Test: {description}")
    print(f"Envoi: {cmd}")

    # Flush buffers
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # Envoi commande avec terminaison \r\n
    ser.write((cmd + '\r\n').encode('utf-8'))
    ser.flush()

    # Attendre réponse
    time.sleep(0.3)

    # Lecture réponse
    response = ser.read_all().decode('utf-8', errors='ignore').strip()

    if response:
        print(f"Réponse: {response}")
        # Vérifier SW (Status Word)
        if len(response) >= 4:
            sw = response[-4:]
            if sw == '9000':
                print("✅ SW 9000 - Succès")
                return True, response
            else:
                print(f"❌ SW {sw} - Erreur")
                return False, response
    else:
        print("❌ Pas de réponse (timeout)")
        return False, ""

    return False, response

def main():
    print("="*60)
    print("Test Communication LeMonolith HSM - Feature 1")
    print("="*60)

    try:
        # Ouvrir port série
        print(f"\nOuverture du port {PORT} à {BAUDRATE} bauds...")
        ser = Serial(PORT, BAUDRATE, timeout=TIMEOUT)
        print(f"✅ Port ouvert avec succès")

        # Test 1: OFF (désactivation SE)
        success, _ = send_command(ser, "off", "Désactivation Secure Element")
        time.sleep(0.2)

        # Test 2: ON (activation SE)
        # Note: Le firmware LeMonolith sélectionne automatiquement l'applet CC lors du "on"
        success, response = send_command(ser, "on", "Activation Secure Element + Auto-SELECT CC")
        time.sleep(0.5)  # Attendre stabilisation

        # Vérifier que le SELECT automatique a réussi (SW 9000 dans la réponse)
        if '9000' in response:
            print("✅ Application CC auto-sélectionnée par le firmware")

            # Test 3: VERIFY PIN
            success_pin, _ = send_command(ser, APDU_VERIFY_PIN, "VERIFY User PIN (0000)")

            if success_pin:
                print("\n✅ PIN vérifié avec succès")
                print("\n" + "="*60)
                print("🎉 Feature 1 - Initialisation: SUCCÈS")
                print("="*60)
                print("\nRésumé:")
                print("  ✅ Communication UART établie")
                print("  ✅ Secure Element activé")
                print("  ✅ Application CC auto-sélectionnée")
                print("  ✅ PIN User vérifié")
                print("\n📋 Détails techniques:")
                print(f"  - Port: {PORT}")
                print(f"  - Baudrate: {BAUDRATE}")
                print(f"  - AID Application CC: 010203040601")
                print(f"  - PIN User: 0000 (30303030)")
                return 0
            else:
                print("\n⚠️ Erreur de vérification PIN")
                return 1
        else:
            print("\n❌ Application CC non sélectionnée automatiquement")
            print("Vérifiez le firmware du LeMonolith")
            return 1

        # Fermeture propre
        ser.close()
        return 1

    except SerialException as e:
        print(f"\n❌ Erreur série: {e}")
        print("Vérifiez:")
        print("  1. Le HSM est bien connecté sur /dev/ttyUSB0")
        print("  2. Vous êtes dans le groupe dialout: groups")
        print("  3. Le port n'est pas utilisé par un autre processus")
        return 1

    except KeyboardInterrupt:
        print("\n\nInterruption utilisateur")
        return 1

    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
