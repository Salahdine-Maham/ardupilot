#!/usr/bin/env python3
"""
Mission chiffrée: Décollage 20m, Cercle 100m, RTL, Atterrissage
Toutes les commandes sont chiffrées via HSM
"""

import sys
import os
import time
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from gcs_kep_client import GCSKeyExchangeClient, log

# MAVLink command IDs
MAV_CMD_NAV_TAKEOFF = 22
MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_DO_CHANGE_SPEED = 178
MAV_CMD_COMPONENT_ARM_DISARM = 400
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_DO_SET_MODE = 176

# Flight modes
GUIDED_MODE = 4
CIRCLE_MODE = 7
RTL_MODE = 6
LAND_MODE = 9


def run_mission(hsm_port: str, mavlink_url: str = "tcp:127.0.0.1:5760"):
    """Exécute la mission chiffrée"""

    print("=" * 60)
    print("  MISSION CHIFFRÉE HSM")
    print("  Décollage 20m → Cercle 100m → RTL → Atterrissage")
    print("=" * 60)

    # Créer le client
    client = GCSKeyExchangeClient(
        mavlink_connection=mavlink_url,
        hsm_port=hsm_port,
        gcs_sysid=255,
        gcs_compid=190,
        verbose=False
    )

    # Initialiser et faire l'échange de clés
    log("Initialisation et échange de clés...")
    success = client.run()

    if not success or not client.dde or not client.dde.is_ready():
        log("Échec de l'échange de clés!", "ERROR")
        return False

    log("Échange de clés réussi! DualDekEngine prêt.")
    time.sleep(2)

    # ==================== MISSION ====================

    # 1. Mode GUIDED
    log(">>> [1/7] Mode GUIDED")
    client.send_encrypted_set_mode(1, GUIDED_MODE, target_sysid=1)
    time.sleep(2)

    # 2. ARM
    log(">>> [2/7] ARM")
    client.send_encrypted_command(
        MAV_CMD_COMPONENT_ARM_DISARM,
        param1=1,  # 1 = arm
        target_sysid=1
    )
    time.sleep(3)

    # 3. TAKEOFF 20m
    log(">>> [3/7] TAKEOFF 20m")
    client.send_encrypted_command(
        MAV_CMD_NAV_TAKEOFF,
        param7=20,  # altitude
        target_sysid=1
    )
    log("Attente montée à 20m...")
    time.sleep(15)

    # 4. Aller à 100m au Nord pour le centre du cercle
    log(">>> [4/7] Navigation vers point à 100m")
    # On envoie une position relative (100m Nord)
    # Pour SITL, la position home est généralement autour de -35.363261, 149.165230
    # On va à 100m au nord
    home_lat = -35.363261
    home_lon = 149.165230
    # 100m nord = environ 0.0009 degrés
    target_lat = home_lat + 0.0009
    target_lon = home_lon

    client.send_encrypted_command(
        MAV_CMD_NAV_WAYPOINT,
        param5=target_lat,  # latitude
        param6=target_lon,  # longitude
        param7=20,          # altitude
        target_sysid=1
    )
    log("Attente arrivée au waypoint...")
    time.sleep(20)

    # 5. Mode CIRCLE
    log(">>> [5/7] Mode CIRCLE (rayon 100m)")
    # D'abord configurer le rayon du cercle via paramètre
    # CIRCLE_RADIUS = 100m (on utilise le paramètre par défaut ou on le set)
    client.send_encrypted_set_mode(1, CIRCLE_MODE, target_sysid=1)
    log("Cercle en cours (30 secondes)...")
    time.sleep(30)

    # 6. RTL
    log(">>> [6/7] RTL - Retour à la maison")
    client.send_encrypted_set_mode(1, RTL_MODE, target_sysid=1)
    log("Retour en cours...")
    time.sleep(25)

    # 7. LAND (normalement RTL atterrit automatiquement, mais on force)
    log(">>> [7/7] LAND")
    client.send_encrypted_set_mode(1, LAND_MODE, target_sysid=1)
    log("Atterrissage en cours...")
    time.sleep(15)

    # Statistiques finales
    print("\n" + "=" * 60)
    print("  MISSION TERMINÉE")
    print("=" * 60)
    if client.dde:
        client.dde.print_status()
    print(f"\nStatistiques crypto:")
    print(f"  Commandes TX chiffrées: {client.dde._stats['tx_encrypted'] if client.dde else 0}")
    print(f"  Messages RX déchiffrés: {client._crypto_stats['decrypted_ok']}")
    print("=" * 60)

    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mission chiffrée HSM")
    parser.add_argument("--hsm", default="/dev/ttyUSB1", help="Port HSM")
    parser.add_argument("--mavlink", default="tcp:127.0.0.1:5760", help="MAVLink URL")
    args = parser.parse_args()

    run_mission(args.hsm, args.mavlink)
