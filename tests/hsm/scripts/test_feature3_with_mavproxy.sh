#!/bin/bash
# Test complet Features 1-2-3 avec MAVProxy (SOLUTION TROUVÉE!)

echo "================================================"
echo "  Test Features 1+2+3 avec MAVProxy"
echo "================================================"
echo ""
echo "Nettoyage des processus..."
pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

# Créer log
LOGFILE="feature3/test_with_mavproxy_$(date +%Y%m%d_%H%M%S).log"

echo "Lancement ArduCopter (en arrière-plan)..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > "$LOGFILE" 2>&1 &
ACP=$!
echo "ArduCopter PID: $ACP"

sleep 4

echo "Lancement MAVProxy (en arrière-plan)..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /tmp/mavproxy.log 2>&1 &
MVP=$!
echo "MAVProxy PID: $MVP"

echo ""
echo "Attente 45 secondes pour initialisation complète..."
echo "(Features 1+2+3 avec génération DEK, ECDH, HKDF, wrap/store + écritures EEPROM)"
sleep 45

echo ""
echo "================================================"
echo "  RÉSULTATS"
echo "================================================"
echo ""

# Vérifier Feature 1
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 1: SUCCÈS"
else
    echo "❌ Feature 1: ÉCHEC"
fi

# Vérifier Feature 2
if grep -q "✓ Feature 2 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 2: SUCCÈS"
    echo ""
    echo "Clé publique:"
    grep "HSM: Public key (64 bytes):" "$LOGFILE"
else
    echo "❌ Feature 2: ÉCHEC"
fi

# Vérifier Feature 3
if grep -q "✓ Feature 3 complétée avec succès" "$LOGFILE"; then
    echo "✅✅✅ Feature 3: SUCCÈS COMPLET!"
    echo ""
    echo "DEK générée:"
    grep "HSM: DEK (32 bytes):" "$LOGFILE" | head -1
    echo ""
    echo "Wrapped DEK stockée:"
    grep "HSM: Wrapped DEK (32 bytes):" "$LOGFILE" | head -1
else
    echo "❌ Feature 3: ÉCHEC ou incomplète"
fi

echo ""
echo "================================================"
echo "  CONCLUSION"
echo "================================================"
echo ""

# Compter les succès
SUCCESSES=$(grep -c "complétée avec succès" "$LOGFILE" || echo "0")

if [ "$SUCCESSES" -eq 3 ]; then
    echo "🎉🎉🎉 TOUTES LES FEATURES RÉUSSIES! 🎉🎉🎉"
    echo ""
    echo "✅ Feature 1: Initialisation HSM + Keypair P-256"
    echo "✅ Feature 2: Gestion Keypair P-256"
    echo "✅ Feature 3: DEK ChaCha20-256 + ECDH + HKDF + Wrap/Store"
    echo ""
    echo "Le projet est COMPLET!"
elif [ "$SUCCESSES" -gt 0 ]; then
    echo "⚠️  Partiellement réussi: $SUCCESSES/3 features"
    echo ""
    echo "Regardez le log pour détails: $LOGFILE"
else
    echo "❌ Aucune feature n'a réussi"
    echo ""
    echo "Messages HSM:"
    grep "HSM:" "$LOGFILE" | tail -20
fi

echo ""
echo "Log complet: $LOGFILE"
echo ""
echo "Nettoyage..."
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo "Done!"
