#!/bin/bash
# Quick debug test

pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

echo "Starting ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/ard_test.log 2>&1 &
ARD_PID=$!

sleep 4

echo "Starting MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /tmp/mav_test.log 2>&1 &
MAV_PID=$!

sleep 10

echo "=== Debug output ==="
grep -E "DEBUG|HSM|APDU" /tmp/ard_test.log | head -50

echo ""
echo "=== Killing processes ==="
kill -9 $ARD_PID $MAV_PID 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true
