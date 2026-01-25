#!/bin/bash
# Test final Feature 2 - Version propre sans debug

set -e

echo "=========================================="
echo "  Feature 2: Test Final HSM Keypair P-256"
echo "=========================================="
echo ""

# Nettoyer processus précédents
echo "1. Nettoyage processus précédents..."
killall -9 arducopter 2>/dev/null || true
killall -9 mavproxy.py 2>/dev/null || true
sleep 2

# Vérifications
echo "2. Vérifications..."
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ Erreur: /dev/ttyUSB0 non trouvé"
    exit 1
fi
echo "   ✅ HSM trouvé sur /dev/ttyUSB0"

if [ ! -f build/sitl/bin/arducopter ]; then
    echo "❌ Erreur: build/sitl/bin/arducopter non trouvé"
    exit 1
fi
echo "   ✅ Binaire ArduCopter SITL trouvé"
echo ""

# Fichier de log
LOG_FILE="feature2/test_final_$(date +%Y%m%d_%H%M%S).log"
echo "3. Logs seront dans: $LOG_FILE"
echo ""

# Lancement ArduCopter
echo "4. Lancement ArduCopter SITL..."
build/sitl/bin/arducopter \
    --model + \
    --speedup 1 \
    --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults Tools/autotest/default_params/copter.parm \
    > "$LOG_FILE" 2>&1 &

ARDUPILOT_PID=$!
echo "   ArduCopter PID: $ARDUPILOT_PID"
sleep 4

# Lancement MAVProxy
echo ""
echo "5. Lancement MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /dev/null 2>&1 &
MAVPROXY_PID=$!
echo "   MAVProxy PID: $MAVPROXY_PID"
echo ""

# Attendre initialisation
echo "6. Attente initialisation HSM (15 secondes)..."
sleep 15

# Afficher résultats
echo ""
echo "=========================================="
echo "  RÉSULTATS"
echo "=========================================="
echo ""

# Extraire logs HSM
HSM_LOGS=$(strings "$LOG_FILE" | grep "HSM:" | grep -v "Démarrage\|désactivé\|activé\|Stockage\|Récupération\|Recalcul")

if [ -n "$HSM_LOGS" ]; then
    echo "$HSM_LOGS"
else
    echo "⚠️  Aucun log HSM trouvé"
fi

echo ""
echo "=========================================="
echo ""

# Nettoyage
echo "7. Nettoyage..."
kill -9 $ARDUPILOT_PID $MAVPROXY_PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 1

echo ""
echo "✅ Test terminé! Log complet: $LOG_FILE"
echo ""
echo "Pour voir tous les détails:"
echo "  cat $LOG_FILE | strings | grep 'HSM:'"
echo ""
