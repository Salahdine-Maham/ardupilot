#!/bin/bash
set -e

killall -9 arducopter 2>/dev/null || true
killall -9 mavproxy.py 2>/dev/null || true
sleep 2

echo "Launching ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/simple.log 2>&1 &
PID1=$!

sleep 5

echo "Launching MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 > /dev/null 2>&1 &
PID2=$!

echo "Waiting 20 seconds..."
sleep 20

echo "Checking logs..."
strings /tmp/simple.log | grep -E "DEBUG|HSM:"

echo "Killing..."
kill -9 $PID1 $PID2 2>/dev/null || true
killall -9 arducopter 2>/dev/null || true
killall -9 mavproxy.py 2>/dev/null || true
