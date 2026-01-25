#!/bin/bash
# Teste différents offsets pour trouver les zones accessibles en écriture

killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 2

echo "Lancement ArduCopter pour initialiser HSM..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/test_offsets.log 2>&1 &
PID=$!

sleep 8

echo "Test des offsets accessibles en écriture..."

for offset in "0080" "00C0" "0100" "0120" "0140" "0160" "0180" "01C0" "0200"; do
    echo ""
    echo "=== Test WRITE offset 0x${offset} ==="

    python3 << PYEOF
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=5)
time.sleep(0.3)

ser.reset_input_buffer()
ser.reset_output_buffer()

# APDU: A 00 D6 <offset> 04 DEADBEEF (4 bytes test)
apdu = "A 00D6${offset}04DEADBEEF\r\n"
print(f"Envoi: A 00D6${offset}04DEADBEEF")
ser.write(apdu.encode())
time.sleep(2)

response = ser.read(2000).decode('utf-8', errors='ignore')

if "9000" in response:
    print("  ✅ SUCCESS - Offset 0x${offset} est accessible en WRITE")
elif "6D00" in response:
    print("  ❌ FAILED - 0x${offset}: Instruction not allowed (6D00)")
elif "6A82" in response:
    print("  ❌ FAILED - 0x${offset}: File not found (6A82)")
elif "6B00" in response:
    print("  ❌ FAILED - 0x${offset}: Wrong offset (6B00)")
else:
    print(f"  ⚠️  Status inconnu: {response[:50]}")

ser.close()
PYEOF

    sleep 0.5
done

echo ""
echo "=== Résumé ==="
echo "Vérifiez les offsets marqués ✅ SUCCESS ci-dessus."
echo ""

kill -9 $PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true
echo "Done."
