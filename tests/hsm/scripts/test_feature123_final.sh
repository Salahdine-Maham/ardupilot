#!/bin/bash
# Test Features 1+2+3 - Même méthode que test_feature2_final.sh qui MARCHAIT

pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

echo "Starting ArduCopter..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/feature123_test.log 2>&1 &
ACP=$!

sleep 4

echo "Starting MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /tmp/mavproxy_test.log 2>&1 &
MVP=$!

echo "ArduCopter PID: $ACP, MAVProxy PID: $MVP"
echo "Waiting 50 seconds for initialization (Features 1+2+3 + EEPROM writes)..."
sleep 50

echo ""
echo "=========================================="
echo "  Feature 1+2+3: HSM Test Results"
echo "=========================================="
echo ""

# Feature 1
if grep -q "✓ Feature 1 complétée avec succès" /tmp/feature123_test.log; then
    echo "✅ Feature 1: SUCCÈS"
    grep "Application CC sélectionnée" /tmp/feature123_test.log
    grep "PIN User vérifié" /tmp/feature123_test.log
else
    echo "❌ Feature 1: ÉCHEC"
    echo ""
    echo "Messages HSM:"
    grep "HSM:" /tmp/feature123_test.log | head -20
fi

echo ""

# Feature 2
if grep -q "✓ Feature 2 complétée avec succès" /tmp/feature123_test.log; then
    echo "✅ Feature 2: SUCCÈS"
    grep "Public key (64 bytes):" /tmp/feature123_test.log | tail -1
else
    echo "❌ Feature 2: ÉCHEC"
fi

echo ""

# Feature 3
if grep -q "✓ Feature 3 complétée avec succès" /tmp/feature123_test.log; then
    echo "✅✅✅ Feature 3: SUCCÈS COMPLET!"
    echo ""
    grep "DEK (32 bytes):" /tmp/feature123_test.log | head -1
    grep "Wrapped DEK (32 bytes):" /tmp/feature123_test.log | head -1
else
    echo "❌ Feature 3: ÉCHEC ou incomplète"
    echo ""
    echo "Derniers messages Feature 3:"
    grep "Feature 3" /tmp/feature123_test.log -A 30 | tail -20
fi

echo ""
echo "=========================================="
echo "  RÉSULTAT GLOBAL"
echo "=========================================="
echo ""

SUCCESSES=$(grep -c "complétée avec succès" /tmp/feature123_test.log 2>/dev/null || echo "0")

if [ "$SUCCESSES" -eq 3 ]; then
    echo "🎉🎉🎉 TOUTES LES FEATURES RÉUSSIES! 🎉🎉🎉"
    echo ""
    echo "✅ Feature 1: Initialisation HSM + Keypair"
    echo "✅ Feature 2: Gestion Keypair P-256"
    echo "✅ Feature 3: DEK ChaCha20-256 + ECDH + HKDF + Wrap/Store"
    echo ""
    echo "🚀 LE PROJET EST COMPLET!"
elif [ "$SUCCESSES" -gt 0 ]; then
    echo "⚠️  $SUCCESSES/3 features réussies"
else
    echo "❌ Aucune feature réussie"
fi

echo ""
echo "=========================================="
echo ""
echo "Cleaning up..."
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo "Done! Full log at: /tmp/feature123_test.log"
