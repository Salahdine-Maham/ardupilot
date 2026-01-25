#!/bin/bash
# Test direct du HSM sans ArduPilot

echo "=== Test Direct HSM LeMonolith ==="
echo ""

# Configuration port série
stty -F /dev/ttyUSB0 115200 raw -echo

# Fonction pour envoyer commande et attendre
send_cmd() {
    local cmd=$1
    local delay=$2
    echo "Envoi: $cmd"
    echo -e "${cmd}\r" > /dev/ttyUSB0
    sleep $delay
    # Lire réponse si disponible
    timeout 0.5s cat /dev/ttyUSB0 2>/dev/null || true
    echo ""
}

echo "1. Désactivation SE..."
send_cmd "off" 0.3

echo "2. Activation SE..."
send_cmd "on" 3

echo "3. SELECT applet CC..."
send_cmd "A 00A4040006010203040601" 2

echo "4. VERIFY PIN..."
send_cmd "A 00200001083030303030303030" 1

echo ""
echo "=== Test terminé ==="
