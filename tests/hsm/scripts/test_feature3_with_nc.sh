#!/bin/bash
# Test complet Features 1-2-3 avec connexion TCP simple (nc)
# Cette méthode garde la connexion ouverte sans se déconnecter

echo "================================================"
echo "  Test Features 1+2+3 avec connexion TCP simple"
echo "================================================"
echo ""
echo "Nettoyage..."
pkill -9 arducopter mavproxy nc 2>/dev/null || true
sleep 2

# Créer log
LOGFILE="feature3/test_with_nc_$(date +%Y%m%d_%H%M%S).log"

echo "Lancement ArduCopter (en arrière-plan)..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > "$LOGFILE" 2>&1 &
ACP=$!
echo "ArduCopter PID: $ACP"

echo "Attente 4 secondes pour bind port 5760..."
sleep 4

echo "Connexion TCP simple avec nc (garde la connexion ouverte)..."
# nc en mode listen, lit tout ce qu'ArduCopter envoie
timeout 60s nc 127.0.0.1 5760 > /dev/null 2>&1 &
NC=$!
echo "NC PID: $NC"

echo ""
echo "Attente 50 secondes pour initialisation complète..."
echo "(Features 1+2+3 avec génération DEK, ECDH, HKDF, wrap/store + écritures EEPROM)"
sleep 50

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
    echo "Wrapped DEK stockée:"
    grep "HSM: Wrapped DEK (32 bytes):" "$LOGFILE" | head -1
    echo ""
    echo "Vérification récupération:"
    grep "✓ DEK unwrappée avec succès" "$LOGFILE" || echo "(Pas encore testée)"
else
    echo "❌ Feature 3: ÉCHEC ou incomplète"
    echo ""
    echo "Derniers messages Feature 3:"
    grep "Feature 3" "$LOGFILE" -A 50 | tail -20
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
    echo "🚀 Le projet ArduPilot+HSM est COMPLET!"
    echo "🔐 Toutes les fonctions crypto sont opérationnelles!"
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
kill -9 $ACP $NC 2>/dev/null || true
pkill -9 arducopter nc 2>/dev/null || true

echo "Done!"
