#!/bin/bash
# Extended Feature 2 test with longer wait time

pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

echo "Starting ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/feature2_long.log 2>&1 &
ACP=$!

sleep 5

echo "Starting MAVProxy (will stay connected)..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console --aircraft test 2>&1 | tee /tmp/mavproxy_long.log &
MVP=$!

echo "ArduCopter PID: $ACP, MAVProxy PID: $MVP"
echo "Waiting 30 seconds for full initialization..."
sleep 30

echo ""
echo "=========================================="
echo "  Feature 2: HSM Test Results"
echo "=========================================="
echo ""

# Extract HSM logs
HSM_LOGS=$(strings /tmp/feature2_long.log | grep "HSM:")
if [ -n "$HSM_LOGS" ]; then
    echo "$HSM_LOGS"
else
    echo "No HSM logs found yet. Checking last 100 lines of log..."
    strings /tmp/feature2_long.log | tail -100
fi

echo ""
echo "=========================================="
echo ""
echo "Cleaning up..."
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo "Done! Full log at: /tmp/feature2_long.log"
