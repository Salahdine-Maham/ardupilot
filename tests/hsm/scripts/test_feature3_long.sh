#!/bin/bash
# Test Feature 3 avec timeout long pour écritures EEPROM

killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 2

LOG=/tmp/hsm_feature3_long.log

echo "Lancement ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > $LOG 2>&1 &
PID=$!

sleep 3

echo "Lancement MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 > /dev/null 2>&1 &

echo "Attente 25 secondes (pour délais EEPROM)..."
sleep 25

echo ""
echo "=== LOGS HSM Feature 3 ==="
grep "HSM:" $LOG | grep -A 100 "Feature 3" || echo "Aucun log HSM trouvé"

echo ""
echo "=== Résultat final ==="
if grep -q "HSM: ✓ DEK wrappée stockée avec succès dans HSM" $LOG; then
    echo "✅ Feature 3: SUCCESS - DEK stockée dans HSM"
elif grep -q "HSM: Erreur - Timeout WRITE" $LOG; then
    echo "❌ Feature 3: FAILED - Timeout WRITE"
    grep "HSM: Erreur - Timeout" $LOG
elif grep -q "HSM: ✗ Feature 3 échouée" $LOG; then
    echo "❌ Feature 3: FAILED"
else
    echo "⚠️  Feature 3: Status inconnu"
fi

echo ""
kill -9 $PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true
echo "Done."
