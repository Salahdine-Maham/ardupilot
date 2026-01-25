#!/bin/bash
# Test rapide HSM

killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 2

LOG=/tmp/hsm_quick.log

echo "Lancement ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > $LOG 2>&1 &
PID=$!

sleep 3

echo "Lancement MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 > /dev/null 2>&1 &

echo "Attente 12 secondes..."
sleep 12

echo ""
echo "=== LOGS HSM ==="
grep "HSM:" $LOG || echo "Aucun log HSM trouvé"

echo ""
kill -9 $PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true
echo "Done."
