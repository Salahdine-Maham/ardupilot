#!/bin/bash
# Test complet Feature 1 avec SITL ArduCopter + LeMonolith HSM
# Ce script lance ArduCopter en mode SITL avec le HSM connecté sur /dev/ttyUSB0

set -e

echo "=========================================="
echo "  Feature 1: Test SITL avec HSM réel"
echo "=========================================="
echo ""

# Vérification HSM
echo "1. Vérification du HSM sur /dev/ttyUSB0..."
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ Erreur: /dev/ttyUSB0 non trouvé"
    echo "   Vérifiez que le LeMonolith est connecté"
    exit 1
fi
echo "✅ HSM trouvé sur /dev/ttyUSB0"
echo ""

# Vérification binaire ArduCopter
echo "2. Vérification du binaire ArduCopter SITL..."
if [ ! -f build/sitl/bin/arducopter ]; then
    echo "❌ Erreur: build/sitl/bin/arducopter non trouvé"
    echo "   Compilez d'abord avec: ./waf copter"
    exit 1
fi
echo "✅ Binaire ArduCopter SITL trouvé"
echo ""

# Création fichier de log
LOG_FILE="feature1/test_sitl_$(date +%Y%m%d_%H%M%S).log"
echo "3. Logs seront sauvegardés dans: $LOG_FILE"
echo ""

echo "4. Lancement ArduCopter SITL avec HSM..."
echo "   (Appuyez sur Ctrl+C pour arrêter)"
echo "   Recherche des logs 'HSM:' ..."
echo ""
echo "=========================================="
echo ""

# Lancer ArduCopter et filtrer les logs HSM
build/sitl/bin/arducopter \
    --model + \
    --speedup 1 \
    --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults Tools/autotest/default_params/copter.parm \
    2>&1 | tee "$LOG_FILE" | grep --line-buffered -E "HSM|Initialisation|Feature"

