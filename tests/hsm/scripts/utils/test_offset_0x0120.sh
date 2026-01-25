#!/bin/bash
# Test direct de l'offset 0x0120 dans le HSM

killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 2

echo "Lancement ArduCopter pour initialiser HSM..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/test_offset.log 2>&1 &
PID=$!

sleep 8

echo "ArduCopter lancé. Test direct de l'offset 0x0120..."

# Test 1: Essayer de lire à 0x0120
echo ""
echo "=== Test 1: READ à 0x0120 (32 bytes) ==="
python3 << 'PYEOF'
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=2)
time.sleep(0.5)

ser.reset_input_buffer()
ser.reset_output_buffer()

# APDU: A 00 B0 01 20 20 (READ BINARY offset 0x0120, 32 bytes)
apdu = "A 00B0012020\r\n"
print(f"Envoi READ 0x0120: {apdu.strip()}")
ser.write(apdu.encode())
time.sleep(2)

response = ser.read(2000).decode('utf-8', errors='ignore')
print(f"Réponse: {response}")

if "9000" in response:
    print("✅ READ 0x0120 SUCCESS")
elif "6A82" in response:
    print("❌ READ 0x0120 FAILED - File not found (0x6A82)")
elif "6B00" in response:
    print("❌ READ 0x0120 FAILED - Wrong offset (0x6B00)")
else:
    print("⚠️  READ 0x0120 - Status inconnu")

ser.close()
PYEOF

sleep 1

# Test 2: Essayer d'écrire à 0x0120
echo ""
echo "=== Test 2: WRITE à 0x0120 (4 bytes de test: DEADBEEF) ==="
python3 << 'PYEOF'
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=5)
time.sleep(0.5)

ser.reset_input_buffer()
ser.reset_output_buffer()

# APDU: A 00 D6 01 20 04 DEADBEEF (WRITE BINARY offset 0x0120, 4 bytes)
apdu = "A 00D6012004DEADBEEF\r\n"
print(f"Envoi WRITE 0x0120: {apdu.strip()}")
ser.write(apdu.encode())
time.sleep(3)  # Attendre longtemps pour EEPROM

response = ser.read(2000).decode('utf-8', errors='ignore')
print(f"Réponse: {response}")

if "9000" in response:
    print("✅ WRITE 0x0120 SUCCESS")
elif "6A82" in response:
    print("❌ WRITE 0x0120 FAILED - File not found (0x6A82)")
elif "6B00" in response:
    print("❌ WRITE 0x0120 FAILED - Wrong offset (0x6B00)")
elif "6700" in response:
    print("❌ WRITE 0x0120 FAILED - Wrong length (0x6700)")
else:
    print("⚠️  WRITE 0x0120 - Status inconnu ou timeout")

ser.close()
PYEOF

echo ""
kill -9 $PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true
echo "Done."
