#!/bin/bash
# Test script pour Feature 1: Initialisation du HSM avec ArduCopter SITL

echo "=== Test Feature 1: Initialisation LeMonolith HSM ==="
echo ""
echo "Vérification du HSM sur /dev/ttyUSB0..."
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ Erreur: /dev/ttyUSB0 non trouvé"
    echo "Vérifiez que le LeMonolith est connecté"
    exit 1
fi

echo "✅ HSM trouvé sur /dev/ttyUSB0"
echo ""
echo "Lancement ArduCopter SITL avec HSM..."
echo "Logs ci-dessous (attendez les messages 'HSM:'):"
echo "------------------------------------------------------"

# Lancer arducopter et filtrer les logs HSM
build/sitl/bin/arducopter \
    --model + \
    --speedup 1 \
    --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults Tools/autotest/default_params/copter.parm \
    2>&1 | grep --line-buffered "HSM\|Initialisation"

