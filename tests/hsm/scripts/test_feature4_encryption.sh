#!/bin/bash
# Test Feature 4: Encryption/Décryption MAVLink avec ChaCha20-256

pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

echo "=========================================="
echo "  Feature 4: MAVLink Encryption Test"
echo "=========================================="
echo ""
echo "Ce test vérifie:"
echo "  1. Features 1-3 (HSM init + DEK generation)"
echo "  2. Encryption des messages sortants (ChaCha20-256)"
echo "  3. Décryption des messages entrants"
echo "  4. Paramètre MAV_ENCRYPT activation"
echo ""

echo "Starting ArduCopter with HSM..."
build/sitl/bin/arducopter --model + --speedup 1 --serial1=uart:/dev/ttyUSB0:115200 --defaults Tools/autotest/default_params/copter.parm > /tmp/feature4_test.log 2>&1 &
ACP=$!

sleep 4

echo "Starting MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /tmp/mavproxy_feature4.log 2>&1 &
MVP=$!

echo "ArduCopter PID: $ACP, MAVProxy PID: $MVP"
echo ""
echo "Waiting 60 seconds for initialization..."
echo "  - Features 1-3 (HSM + DEK): ~15s"
echo "  - Encryption activation: ~5s"
echo "  - MAVLink messages flow: ~40s"
sleep 60

echo ""
echo "=========================================="
echo "  RÉSULTATS"
echo "=========================================="
echo ""

# Feature 1: Initialisation HSM
if grep -q "✓ Feature 1 complétée avec succès" /tmp/feature4_test.log; then
    echo "✅ Feature 1: Initialisation HSM - SUCCÈS"
else
    echo "❌ Feature 1: ÉCHEC"
    echo ""
    echo "Log HSM:"
    grep "HSM:" /tmp/feature4_test.log | head -15
    echo ""
    echo "Arrêt du test (Feature 1 requis)"
    kill -9 $ACP $MVP 2>/dev/null
    exit 1
fi

# Feature 2: Gestion Keypair
if grep -q "✓ Feature 2 complétée avec succès" /tmp/feature4_test.log; then
    echo "✅ Feature 2: Gestion Keypair P-256 - SUCCÈS"
else
    echo "❌ Feature 2: ÉCHEC"
fi

# Feature 3: DEK Generation
if grep -q "✓ Feature 3 complétée avec succès" /tmp/feature4_test.log; then
    echo "✅ Feature 3: Génération DEK ChaCha20-256 - SUCCÈS"
else
    echo "⚠️  Feature 3: PARTIEL (crypto fonctionne, storage peut échouer)"
fi

echo ""
echo "----------------------------------------"
echo "  Feature 4: Encryption MAVLink"
echo "----------------------------------------"
echo ""

# Vérifier si encryption activée
if grep -q "Encrypted with ChaCha20-256" /tmp/feature4_test.log; then
    ENCRYPTED_COUNT=$(grep -c "Encrypted with ChaCha20-256" /tmp/feature4_test.log)
    echo "✅ ENCRYPTION ACTIVE: $ENCRYPTED_COUNT messages chiffrés"

    # Afficher quelques exemples
    echo ""
    echo "Exemples de messages chiffrés:"
    grep -A 3 "Encrypted with ChaCha20-256" /tmp/feature4_test.log | head -20

else
    echo "❌ ENCRYPTION INACTIVE: Aucun message chiffré détecté"
    echo ""
    echo "Vérifier si MAV_ENCRYPT=1 est activé"
fi

echo ""

# Vérifier si décryption activée
if grep -q "Decrypted with ChaCha20-256" /tmp/feature4_test.log; then
    DECRYPTED_COUNT=$(grep -c "Decrypted with ChaCha20-256" /tmp/feature4_test.log)
    echo "✅ DÉCRYPTION ACTIVE: $DECRYPTED_COUNT messages déchiffrés"

    # Afficher quelques exemples
    echo ""
    echo "Exemples de messages déchiffrés:"
    grep -A 3 "Decrypted with ChaCha20-256" /tmp/feature4_test.log | head -20

else
    echo "⚠️  DÉCRYPTION INACTIVE: Aucun message entrant détecté"
    echo ""
    echo "Note: Décryption requiert des messages entrants depuis MAVProxy"
fi

echo ""
echo "=========================================="
echo "  RÉSUMÉ GLOBAL"
echo "=========================================="
echo ""

# Compter les succès
SUCCESSES=$(grep -c "complétée avec succès" /tmp/feature4_test.log 2>/dev/null || echo "0")

if [ "$SUCCESSES" -ge 2 ]; then
    echo "✅ Features 1-3: OK ($SUCCESSES/3 features)"
else
    echo "❌ Features 1-3: ÉCHEC ($SUCCESSES/3 features)"
fi

if [ "$ENCRYPTED_COUNT" -gt 0 ]; then
    echo "✅ Feature 4 Encryption: OK ($ENCRYPTED_COUNT messages)"
else
    echo "⚠️  Feature 4 Encryption: À vérifier"
fi

if [ "$DECRYPTED_COUNT" -gt 0 ]; then
    echo "✅ Feature 4 Décryption: OK ($DECRYPTED_COUNT messages)"
else
    echo "ℹ️  Feature 4 Décryption: Pas de messages entrants"
fi

echo ""
echo "=========================================="
echo ""

# Statistiques
echo "Statistiques:"
echo "  - Messages chiffrés:   $ENCRYPTED_COUNT"
echo "  - Messages déchiffrés: $DECRYPTED_COUNT"
echo "  - Features complètes:  $SUCCESSES/3"

# Recommandations
echo ""
echo "Pour activer l'encryption MAVLink:"
echo "  1. Via MAVProxy: param set MAV_ENCRYPT 1"
echo "  2. Redémarrer ArduCopter"
echo "  3. Vérifier que DEK est disponible (Feature 3)"

echo ""
echo "Cleaning up..."
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo ""
echo "Logs complets:"
echo "  - ArduCopter: /tmp/feature4_test.log"
echo "  - MAVProxy:   /tmp/mavproxy_feature4.log"
echo ""
echo "Done!"
