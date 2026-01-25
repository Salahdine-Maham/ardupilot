#!/bin/bash
# Test Features 1-2-3 avec MAVProxy lancé APRÈS initialisation HSM

echo "================================================"
echo "  Test Features 1+2+3 (MAVProxy retardé)"
echo "================================================"
echo ""
echo "Nettoyage..."
pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

# Créer log
LOGFILE="feature3/test_delayed_mavproxy_$(date +%Y%m%d_%H%M%S).log"

echo "Lancement ArduCopter (en arrière-plan)..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > "$LOGFILE" 2>&1 &
ACP=$!
echo "ArduCopter PID: $ACP"

echo ""
echo "⏳ Attente 15 secondes pour initialisation HSM COMPLÈTE..."
echo "   (OFF → ON → SELECT → VERIFY PIN → Features 1-2-3)"
sleep 15

# Vérifier que l'initialisation HSM a réussi AVANT de lancer MAVProxy
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 1 détectée - HSM initialisé!"
else
    echo "⚠️  Feature 1 pas encore détectée, attente 5s supplémentaires..."
    sleep 5
fi

echo "Lancement MAVProxy (APRÈS initialisation HSM)..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /tmp/mavproxy.log 2>&1 &
MVP=$!
echo "MAVProxy PID: $MVP"

echo ""
echo "⏳ Attente 30 secondes pour Features 2 et 3..."
sleep 30

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
    grep "HSM: Public key (64 bytes):" "$LOGFILE" | tail -1
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
    echo "Wrapped DEK:"
    grep "HSM: Wrapped DEK (32 bytes):" "$LOGFILE" | head -1
else
    echo "❌ Feature 3: ÉCHEC ou incomplète"
    echo ""
    echo "Derniers messages Feature 3:"
    grep "Feature 3" "$LOGFILE" -A 20 | tail -15
fi

echo ""
echo "================================================"
echo "  CONCLUSION"
echo "================================================"
echo ""

# Compter les succès
SUCCESSES=$(grep -c "complétée avec succès" "$LOGFILE" 2>/dev/null || echo "0")

if [ "$SUCCESSES" -eq 3 ]; then
    echo "🎉🎉🎉 TOUTES LES FEATURES RÉUSSIES! 🎉🎉🎉"
    echo ""
    echo "✅ Feature 1: Initialisation HSM + Keypair P-256"
    echo "✅ Feature 2: Gestion Keypair P-256"
    echo "✅ Feature 3: DEK ChaCha20-256 + ECDH + HKDF + Wrap/Store"
    echo ""
    echo "🚀 Le projet ArduPilot+HSM est COMPLET!"
elif [ "$SUCCESSES" -gt 0 ]; then
    echo "⚠️  Partiellement réussi: $SUCCESSES/3 features"
    echo ""
    echo "Regardez le log pour détails: $LOGFILE"
else
    echo "❌ Aucune feature n'a réussi"
    echo ""
    echo "Messages HSM:"
    grep "HSM:" "$LOGFILE" | tail -30
fi

echo ""
echo "Log complet: $LOGFILE"
echo ""
echo "Nettoyage..."
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo "Done!"
