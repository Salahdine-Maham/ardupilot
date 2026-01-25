#!/bin/bash
# Test HSM après reset physique
# À lancer APRÈS avoir débranché/rebranché le HSM

echo "=== Test HSM Après Reset Physique ==="
echo ""
echo "⚠️  AVEZ-VOUS DÉBRANCHÉ/REBRANCHÉ LE HSM? (5 secondes)"
echo "   Si non, faites-le MAINTENANT et relancez ce script!"
echo ""
read -p "Appuyez sur ENTER pour continuer..."

# Vérifier que le HSM est détecté
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ Erreur: /dev/ttyUSB0 non trouvé"
    echo "   Le HSM n'est pas branché ou pas détecté"
    exit 1
fi

echo "✅ HSM détecté sur /dev/ttyUSB0"
echo ""

# Test avec timeout court (10s)
echo "Lancement test court (10s)..."
LOGFILE="feature3/test_after_reset_$(date +%Y%m%d_%H%M%S).log"

timeout 10s build/sitl/bin/arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 --console 2>&1 | tee "$LOGFILE"

echo ""
echo "=== Analyse ==="

# Vérifier si Feature 1 a réussi
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    echo "🎉 ✅ Feature 1: SUCCÈS!"
else
    echo "❌ Feature 1: Échec"
    echo ""
    echo "Messages HSM:"
    grep "HSM:" "$LOGFILE" | head -20
fi

# Vérifier si Feature 2 a réussi
if grep -q "✓ Feature 2 complétée avec succès" "$LOGFILE"; then
    echo "🎉 ✅ Feature 2: SUCCÈS!"
fi

# Vérifier si Feature 3 a réussi
if grep -q "✓ Feature 3 complétée avec succès" "$LOGFILE"; then
    echo "🎉 ✅✅✅ Feature 3: SUCCÈS COMPLET!"
    echo ""
    echo "DEK générée:"
    grep "HSM: DEK (32 bytes):" "$LOGFILE" | head -1
fi

echo ""
echo "Log complet: $LOGFILE"
