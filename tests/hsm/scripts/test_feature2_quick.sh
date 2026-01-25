#!/bin/bash
# Test rapide Feature 2 uniquement pour comparaison avec Feature 3

echo "================================================"
echo "  Test Feature 2 UNIQUEMENT (pour debug)"
echo "================================================"
echo ""
echo "Objectif: Vérifier si Feature 2 fonctionne toujours"
echo "Si oui → Problème spécifique à Feature 3"
echo "Si non → HSM devenu instable depuis"
echo ""

# Vérifier HSM
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ /dev/ttyUSB0 non trouvé!"
    exit 1
fi
echo "✅ HSM détecté sur /dev/ttyUSB0"
echo ""

# Créer log
mkdir -p feature2/logs
LOGFILE="feature2/logs/test_quick_$(date +%Y%m%d_%H%M%S).log"

echo "Lancement ArduCopter (timeout 15s)..."
echo "Log: $LOGFILE"
echo ""

# Lancer test
timeout 15s build/sitl/bin/arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 --console 2>&1 | tee "$LOGFILE"

echo ""
echo "================================================"
echo "  ANALYSE DU RÉSULTAT"
echo "================================================"
echo ""

# Analyser Feature 1
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 1: SUCCÈS"
    F1_OK=1
else
    echo "❌ Feature 1: ÉCHEC"
    F1_OK=0

    # Afficher les messages HSM
    echo ""
    echo "Messages HSM:"
    grep "HSM:" "$LOGFILE" | head -20
fi

echo ""

# Analyser Feature 2
if grep -q "✓ Feature 2 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 2: SUCCÈS"
    F2_OK=1

    # Afficher la clé publique
    echo ""
    echo "Clé publique récupérée:"
    grep "HSM: Public key (64 bytes):" "$LOGFILE"
else
    echo "❌ Feature 2: ÉCHEC"
    F2_OK=0
fi

echo ""
echo "================================================"
echo "  CONCLUSION"
echo "================================================"
echo ""

if [ $F1_OK -eq 1 ] && [ $F2_OK -eq 1 ]; then
    echo "🎉 Feature 2 FONCTIONNE TOUJOURS!"
    echo ""
    echo "➡️  Cela signifie:"
    echo "   • Le HSM est OK"
    echo "   • La communication UART est OK"
    echo "   • Features 1-2 sont stables"
    echo ""
    echo "⚠️  Le problème est donc SPÉCIFIQUE à Feature 3:"
    echo "   • Peut-être un bug dans le nouveau code"
    echo "   • Peut-être les délais Feature 3 sont trop courts"
    echo "   • Peut-être les écritures EEPROM de Feature 3 causent problème"
    echo ""
    echo "📋 PROCHAINE ÉTAPE:"
    echo "   1. Comparer le code Feature 2 vs Feature 3"
    echo "   2. Augmenter les délais dans Feature 3"
    echo "   3. Vérifier les WRITE BINARY dans Feature 3"

elif [ $F1_OK -eq 1 ] && [ $F2_OK -eq 0 ]; then
    echo "⚠️  Feature 1 OK mais Feature 2 ÉCHOUE"
    echo ""
    echo "➡️  Cela signifie:"
    echo "   • HSM communique (Feature 1 OK)"
    echo "   • Problème avec génération/lecture keypair"
    echo "   • Peut-être EEPROM corrompue"
    echo ""
    echo "📋 PROCHAINE ÉTAPE:"
    echo "   1. Vérifier READ BINARY offset 0x0100"
    echo "   2. Régénérer une keypair"

else
    echo "❌ Feature 1 ÉCHOUE"
    echo ""
    echo "➡️  Cela signifie:"
    echo "   • HSM ne répond plus correctement"
    echo "   • État instable confirmé"
    echo "   • Reset physique NÉCESSAIRE"
    echo ""
    echo "📋 ACTION REQUISE:"
    echo "   1. DÉBRANCHER le HSM"
    echo "   2. ATTENDRE 10 secondes"
    echo "   3. REBRANCHER le HSM"
    echo "   4. Relancer ce test"
fi

echo ""
echo "Log complet: $LOGFILE"
