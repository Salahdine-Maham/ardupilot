#!/bin/bash
# Test Feature 3 avec timeout suffisant pour EEPROM writes

killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 2

LOG=/tmp/hsm_feature3_final.log

echo "Lancement ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > $LOG 2>&1 &
PID=$!

sleep 3

echo "Lancement MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 > /dev/null 2>&1 &

echo "Attente 30 secondes (pour Feature 1+2+3 complets avec EEPROM writes)..."
sleep 30

echo ""
echo "=== LOGS HSM Feature 3 ==="
grep "HSM:" $LOG | tail -50

echo ""
echo "=== Résultat final ===="
if grep -q "HSM: ✓ DEK wrappée stockée avec succès dans HSM" $LOG; then
    echo "✅ Feature 3: SUCCESS - DEK wrappée stockée dans HSM"
elif grep -q "HSM: Erreur - Timeout WRITE" $LOG; then
    echo "❌ Feature 3: FAILED - Timeout WRITE"
    grep "HSM: Erreur.*WRITE" $LOG
elif grep -q "HSM: Erreur.*WRITE.*échoué" $LOG; then
    echo "❌ Feature 3: FAILED - WRITE error"
    grep "HSM: Erreur.*WRITE" $LOG
elif grep -q "HSM: ✓ Feature 3 complétée avec succès" $LOG; then
    echo "✅ Feature 3: SUCCESS (read-only mode)"
else
    echo "⚠️  Feature 3: Status inconnu"
fi

echo ""
kill -9 $PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true
echo "Done."
