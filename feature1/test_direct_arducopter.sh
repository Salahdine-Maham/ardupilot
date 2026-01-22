#!/bin/bash
# Test direct ArduCopter avec capture des logs HSM

echo "=== Test Direct ArduCopter avec HSM ==="
echo ""

# Créer un fichier de paramètres minimal
cat > /tmp/test_hsm_params.parm << EOF
SERIAL1_PROTOCOL 0
SERIAL1_BAUD 115
EOF

echo "Lancement ArduCopter (5 secondes)..."
echo "Logs HSM ci-dessous:"
echo "-----------------------------------"

# Lancer avec timeout et capturer stderr aussi
timeout 5 build/sitl/bin/arducopter \
    --model + \
    --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults /tmp/test_hsm_params.parm \
    2>&1 | tee feature1/direct_test.log

echo ""
echo "-----------------------------------"
echo "Recherche de 'HSM' dans les logs:"
grep -i "HSM" feature1/direct_test.log || echo "Aucun log HSM trouvé"

echo ""
echo "Fichier de log complet: feature1/direct_test.log"
