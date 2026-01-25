#!/bin/bash
# Test rapide encryption - Attente 45s

pkill -9 arducopter mavproxy 2>/dev/null
sleep 2

echo "Lancement ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 > /tmp/encrypt_quick.log 2>&1 &
ACP=$!

sleep 5

echo "Lancement MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 > /tmp/mavproxy_quick.log 2>&1 &
MVP=$!

echo "PID: ArduCopter=$ACP, MAVProxy=$MVP"
echo ""
echo "Attente 45 secondes (Features 1-3 + trafic MAVLink)..."

for i in {1..45}; do
    echo -ne "\rTemps: $i/45s"
    sleep 1
done

echo ""
echo ""
echo "=========================================="
echo "  RÉSULTATS"
echo "=========================================="
echo ""

# Features
echo "Features backend:"
grep -q "Feature 1.*succès" /tmp/encrypt_quick.log && echo "  ✅ Feature 1" || echo "  ❌ Feature 1"
grep -q "Feature 2.*succès" /tmp/encrypt_quick.log && echo "  ✅ Feature 2" || echo "  ❌ Feature 2"
if grep -q "Feature 3.*succès\|Mode RAM-only" /tmp/encrypt_quick.log; then
    echo "  ✅ Feature 3 (DEK disponible)"
elif grep -q "DEK.*prête\|DEK.*disponible" /tmp/encrypt_quick.log; then
    echo "  ⏳ Feature 3 (en cours, DEK en cache)"
else
    echo "  ❌ Feature 3"
fi

echo ""

# Encryption
ENCRYPTED=$(grep -c "Encrypted with ChaCha20-256" /tmp/encrypt_quick.log 2>/dev/null || echo "0")
DECRYPTED=$(grep -c "Decrypted with ChaCha20-256" /tmp/encrypt_quick.log 2>/dev/null || echo "0")
DEBUG=$(grep -c "DEBUG.*send_to_active" /tmp/encrypt_quick.log 2>/dev/null || echo "0")

echo "Feature 4 - Encryption:"
echo "  - Debug calls:     $DEBUG"
echo "  - Messages chiffrés:   $ENCRYPTED"
echo "  - Messages déchiffrés: $DECRYPTED"
echo ""

if [ "$ENCRYPTED" -gt 0 ]; then
    echo "✅✅✅ ENCRYPTION FONCTIONNE! ✅✅✅"
    echo ""
    echo "Exemples:"
    grep -B 1 -A 2 "Encrypted with ChaCha20" /tmp/encrypt_quick.log | head -15
else
    echo "❌ Pas d'encryption détectée"
    echo ""

    if [ "$DEBUG" -gt 0 ]; then
        echo "⚠️  send_to_active_channels() appelée mais pas d'encryption"
        echo ""
        grep "DEBUG.*send_to_active.*mav_encrypt" /tmp/encrypt_quick.log | head -3
    else
        echo "❌ send_to_active_channels() jamais appelée"
    fi
fi

echo ""
echo "Nettoyage..."
kill -9 $ACP $MVP 2>/dev/null
pkill -9 arducopter mavproxy 2>/dev/null

echo ""
echo "Logs: /tmp/encrypt_quick.log"
echo ""
echo "Done!"
