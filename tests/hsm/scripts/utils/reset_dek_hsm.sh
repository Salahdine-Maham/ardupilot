#!/bin/bash
# Efface la zone DEK dans le HSM (offset 0x0120, 64 bytes)

killall -9 arducopter mavproxy.py 2>/dev/null || true
sleep 2

echo "Lancement ArduCopter pour effacer DEK..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/reset_dek.log 2>&1 &
PID=$!

sleep 5

# Écrire 64 bytes à zéro à l'offset 0x0120
echo "Envoi commande WRITE BINARY pour effacer DEK..."

# Construction manuelle de l'APDU via Python
python3 << 'PYEOF'
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=2)
time.sleep(0.5)

# Flush
ser.reset_input_buffer()
ser.reset_output_buffer()

# APDU: A 00D6012040 + 64 bytes de zéros (128 caractères hex '00')
apdu = "A 00D6012040" + "00" * 64 + "\r\n"
ser.write(apdu.encode())
time.sleep(1)

response = ser.read(1000).decode('utf-8', errors='ignore')
print("Réponse HSM:", response)

ser.close()
PYEOF

sleep 2

echo "Nettoyage..."
kill -9 $PID 2>/dev/null || true
killall -9 arducopter mavproxy.py 2>/dev/null || true

echo "Done! Zone DEK effacée."
