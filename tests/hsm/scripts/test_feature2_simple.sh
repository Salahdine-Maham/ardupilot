#!/bin/bash
# Test Feature 2 simplifié - démarre ArduCopter et MAVProxy automatiquement

set -e

echo "==========================================="
echo "  Feature 2: Test SITL Keypair P-256"
echo "==========================================="
echo ""

# Nettoyer les processus précédents
echo "1. Nettoyage processus précédents..."
pkill -9 -f "arducopter" 2>/dev/null || true
pkill -9 -f "mavproxy" 2>/dev/null || true
sleep 2

# Vérification HSM
echo "2. Vérification du HSM sur /dev/ttyUSB0..."
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ Erreur: /dev/ttyUSB0 non trouvé"
    exit 1
fi
echo "✅ HSM trouvé sur /dev/ttyUSB0"
echo ""

# Vérification binaire
echo "3. Vérification du binaire ArduCopter SITL..."
if [ ! -f build/sitl/bin/arducopter ]; then
    echo "❌ Erreur: build/sitl/bin/arducopter non trouvé"
    exit 1
fi
echo "✅ Binaire ArduCopter SITL trouvé"
echo ""

# Fichier de log
LOG_FILE="feature2/test_feature2_$(date +%Y%m%d_%H%M%S).log"
echo "4. Logs dans: $LOG_FILE"
echo ""

echo "5. Lancement ArduCopter SITL en arrière-plan..."
build/sitl/bin/arducopter \
    --model + \
    --speedup 1 \
    --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults Tools/autotest/default_params/copter.parm \
    2>&1 | tee "$LOG_FILE" &

ARDUPILOT_PID=$!
echo "   ArduCopter PID: $ARDUPILOT_PID"
sleep 3

echo ""
echo "6. Connexion MAVProxy pour débloquer l'initialisation..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console 2>&1 | tee -a "$LOG_FILE" &

MAVPROXY_PID=$!
echo "   MAVProxy PID: $MAVPROXY_PID"
echo ""

echo "==========================================="
echo "✅ ArduCopter et MAVProxy lancés!"
echo ""
echo "Pour voir les logs HSM en temps réel:"
echo "  tail -f $LOG_FILE | grep --line-buffered -E 'HSM|Feature'"
echo ""
echo "Pour arrêter:"
echo "  kill $ARDUPILOT_PID $MAVPROXY_PID"
echo "==========================================="

# Attendre 10 secondes pour voir les logs HSM
echo ""
echo "Affichage des logs HSM pendant 15 secondes..."
sleep 5
tail -n 100 "$LOG_FILE" | grep -E "HSM|Feature" || echo "⚠️  Aucun log HSM trouvé encore"

echo ""
echo "Pour continuer à observer, lance:"
echo "  tail -f $LOG_FILE | grep --line-buffered -E 'HSM|Feature'"
