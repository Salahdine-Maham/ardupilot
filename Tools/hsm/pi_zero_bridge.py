#!/usr/bin/env python3
"""
Pi Zero HSM Bridge - Pont série entre Pixhawk et HSM

Architecture:
  Pixhawk TELEM1 (TTL) <--> Pi Zero <--> HSM (USB)

Connexions:
  - Pixhawk TX (Pin 2) --> Pi GPIO15 (RX) - Pin 10
  - Pixhawk RX (Pin 3) <-- Pi GPIO14 (TX) - Pin 8
  - Pixhawk GND (Pin 6) --> Pi GND - Pin 6
  - HSM USB-C --> Pi USB OTG (via adaptateur)

Usage:
  sudo python3 pi_zero_bridge.py

Configuration préalable sur Pi Zero:
  1. Activer UART: sudo raspi-config -> Interface Options -> Serial Port
     - Login shell over serial: NO
     - Serial port hardware enabled: YES
  2. Reboot
  3. Le port série sera /dev/serial0 ou /dev/ttyAMA0
"""

import serial
import threading
import time
import sys
import os

# Configuration
PIXHAWK_PORT = "/dev/serial0"  # UART GPIO du Pi Zero
PIXHAWK_BAUD = 115200

HSM_PORT = "/dev/ttyUSB0"  # HSM via USB (peut être /dev/ttyACM0)
HSM_BAUD = 115200

DEBUG = True

def log(msg):
    """Affiche un message de debug avec timestamp"""
    if DEBUG:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")

def find_hsm_port():
    """Trouve automatiquement le port USB du HSM"""
    possible_ports = [
        "/dev/ttyUSB0",
        "/dev/ttyUSB1",
        "/dev/ttyACM0",
        "/dev/ttyACM1"
    ]
    for port in possible_ports:
        if os.path.exists(port):
            log(f"HSM trouvé sur {port}")
            return port
    return None

def pixhawk_to_hsm(ser_pixhawk, ser_hsm):
    """Thread: lit depuis Pixhawk, envoie vers HSM"""
    log("Thread Pixhawk->HSM démarré")
    while True:
        try:
            if ser_pixhawk.in_waiting > 0:
                data = ser_pixhawk.read(ser_pixhawk.in_waiting)
                if data:
                    if DEBUG:
                        try:
                            text = data.decode('utf-8', errors='replace').strip()
                            if text:
                                log(f"PIX->HSM: {text[:80]}")
                        except:
                            log(f"PIX->HSM: {data.hex()[:40]}")
                    ser_hsm.write(data)
                    ser_hsm.flush()
            else:
                time.sleep(0.01)  # 10ms pause si rien à lire
        except Exception as e:
            log(f"Erreur Pixhawk->HSM: {e}")
            time.sleep(0.1)

def hsm_to_pixhawk(ser_hsm, ser_pixhawk):
    """Thread: lit depuis HSM, envoie vers Pixhawk"""
    log("Thread HSM->Pixhawk démarré")
    while True:
        try:
            if ser_hsm.in_waiting > 0:
                data = ser_hsm.read(ser_hsm.in_waiting)
                if data:
                    if DEBUG:
                        try:
                            text = data.decode('utf-8', errors='replace').strip()
                            if text:
                                log(f"HSM->PIX: {text[:80]}")
                        except:
                            log(f"HSM->PIX: {data.hex()[:40]}")
                    ser_pixhawk.write(data)
                    ser_pixhawk.flush()
            else:
                time.sleep(0.01)  # 10ms pause si rien à lire
        except Exception as e:
            log(f"Erreur HSM->Pixhawk: {e}")
            time.sleep(0.1)

def main():
    print("=" * 60)
    print("  Pi Zero HSM Bridge")
    print("  Pont série Pixhawk <--> HSM")
    print("=" * 60)

    # Trouver le port HSM
    hsm_port = find_hsm_port()
    if hsm_port is None:
        print("\n[ERREUR] HSM non trouvé!")
        print("Vérifiez que le HSM est connecté via USB OTG")
        print("Ports recherchés: /dev/ttyUSB0, /dev/ttyACM0, etc.")
        sys.exit(1)

    # Vérifier le port Pixhawk
    if not os.path.exists(PIXHAWK_PORT):
        print(f"\n[ERREUR] Port Pixhawk {PIXHAWK_PORT} non trouvé!")
        print("Avez-vous activé l'UART dans raspi-config?")
        print("  sudo raspi-config -> Interface Options -> Serial Port")
        print("  - Login shell: NO")
        print("  - Serial hardware: YES")
        sys.exit(1)

    print(f"\nConfiguration:")
    print(f"  Pixhawk: {PIXHAWK_PORT} @ {PIXHAWK_BAUD} baud")
    print(f"  HSM:     {hsm_port} @ {HSM_BAUD} baud")
    print()

    try:
        # Ouvrir les ports série
        log("Ouverture du port Pixhawk...")
        ser_pixhawk = serial.Serial(
            PIXHAWK_PORT,
            PIXHAWK_BAUD,
            timeout=0.1,
            exclusive=True
        )

        log("Ouverture du port HSM...")
        ser_hsm = serial.Serial(
            hsm_port,
            HSM_BAUD,
            timeout=0.1,
            exclusive=True
        )

        log("Ports ouverts avec succès!")
        print("\n" + "=" * 60)
        print("  PONT ACTIF - Ctrl+C pour arrêter")
        print("=" * 60 + "\n")

        # Démarrer les threads de pont
        thread_pix_to_hsm = threading.Thread(
            target=pixhawk_to_hsm,
            args=(ser_pixhawk, ser_hsm),
            daemon=True
        )
        thread_hsm_to_pix = threading.Thread(
            target=hsm_to_pixhawk,
            args=(ser_hsm, ser_pixhawk),
            daemon=True
        )

        thread_pix_to_hsm.start()
        thread_hsm_to_pix.start()

        # Boucle principale
        while True:
            time.sleep(1)

    except serial.SerialException as e:
        print(f"\n[ERREUR] Erreur série: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nArrêt du pont...")
    except Exception as e:
        print(f"\n[ERREUR] {e}")
        sys.exit(1)
    finally:
        try:
            ser_pixhawk.close()
            ser_hsm.close()
        except:
            pass
        print("Pont arrêté.")

if __name__ == "__main__":
    main()
