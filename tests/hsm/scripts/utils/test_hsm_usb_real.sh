#!/bin/bash
# Test RÉEL avec HSM LeMonolith connecté sur USB
# Le HSM doit être branché sur /dev/ttyUSB0

echo "=========================================="
echo "  TEST HSM RÉEL VIA USB"
echo "=========================================="
echo ""

# Vérifier que le HSM est connecté
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ ERREUR: /dev/ttyUSB0 non trouvé"
    echo "   Vérifier que le HSM LeMonolith est branché en USB"
    echo ""
    echo "Périphériques série disponibles:"
    ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  Aucun"
    exit 1
fi

echo "✅ HSM détecté sur /dev/ttyUSB0"
echo ""

# Vérifier permissions
if [ ! -w /dev/ttyUSB0 ]; then
    echo "⚠️  Pas de permission d'écriture sur /dev/ttyUSB0"
    echo "   Votre groupe: $(groups | grep -o dialout || echo 'pas dans dialout')"
    echo ""
    echo "Pour corriger:"
    echo "  sudo usermod -a -G dialout $USER"
    echo "  Puis se déconnecter/reconnecter"
    exit 1
fi

echo "✅ Permissions OK (groupe dialout)"
echo ""

# Nettoyer processus existants
pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

echo "Configuration:"
echo "  - HSM Port: /dev/ttyUSB0"
echo "  - HSM Baud: 115200"
echo "  - SITL: ArduCopter"
echo "  - Test: Features 1-4"
echo ""

echo "=========================================="
echo ""

# Lancer ArduCopter avec connexion série au HSM
# Note: En SITL, --serial1 permet de spécifier le port physique
echo "[1/3] Lancement ArduCopter avec connexion HSM USB..."
build/sitl/bin/arducopter \
    --model + \
    --speedup 1 \
    --serial1=uart:/dev/ttyUSB0:115200 \
    > /tmp/test_hsm_usb.log 2>&1 &
ACP=$!

echo "      ArduCopter PID: $ACP"
sleep 5

# Lancer MAVProxy pour trafic MAVLink
echo "[2/3] Lancement MAVProxy..."
timeout 45s mavproxy.py --master=tcp:127.0.0.1:5760 > /tmp/mavproxy_hsm.log 2>&1 &
MVP=$!
echo "      MAVProxy PID: $MVP"

echo "[3/3] Attente 45 secondes pour tests Features 1-4..."
echo ""

for i in {1..45}; do
    echo -ne "\r      Temps: ${i}s / 45s"
    sleep 1
done
echo ""
echo ""

echo "=========================================="
echo "  ANALYSE DES RÉSULTATS"
echo "=========================================="
echo ""

# Feature 1: Initialisation HSM
echo "=== FEATURE 1: Initialisation HSM ==="
echo ""

if grep -q "✓ Feature 1 complétée avec succès" /tmp/test_hsm_usb.log; then
    echo "✅ FEATURE 1: SUCCÈS"
    grep "Feature 1\|init_monolith\|SELECT.*CC\|PIN.*OK" /tmp/test_hsm_usb.log | head -10
    F1_OK=1
else
    echo "❌ FEATURE 1: ÉCHEC"
    echo ""
    echo "Logs HSM:"
    grep "HSM:" /tmp/test_hsm_usb.log | head -20

    if grep -q "Timeout\|Erreur" /tmp/test_hsm_usb.log; then
        echo ""
        echo "Problèmes détectés:"
        grep -i "timeout\|erreur\|error" /tmp/test_hsm_usb.log | head -5
    fi
    F1_OK=0
fi

echo ""
echo "=== FEATURE 2: Génération Keypair ECDSA ==="
echo ""

if grep -q "✓ Feature 2 complétée\|Keypair P-256.*succès" /tmp/test_hsm_usb.log; then
    echo "✅ FEATURE 2: SUCCÈS"
    grep "Feature 2\|Keypair\|ECDSA\|P-256" /tmp/test_hsm_usb.log | head -10
    F2_OK=1
else
    if [ "$F1_OK" -eq 0 ]; then
        echo "⚠️  FEATURE 2: Non exécutée (dépend de Feature 1)"
    else
        echo "❌ FEATURE 2: ÉCHEC"
        grep "Feature 2\|keypair" /tmp/test_hsm_usb.log | head -5
    fi
    F2_OK=0
fi

echo ""
echo "=== FEATURE 3: Génération DEK ==="
echo ""

if grep -q "✓ Feature 3 complétée\|DEK.*disponible\|Mode RAM-only" /tmp/test_hsm_usb.log; then
    echo "✅ FEATURE 3: SUCCÈS"
    grep "Feature 3\|DEK.*générée\|Mode RAM-only" /tmp/test_hsm_usb.log | head -10
    F3_OK=1
    DEK_OK=1
else
    if [ "$F2_OK" -eq 0 ]; then
        echo "⚠️  FEATURE 3: Non exécutée (dépend de Features 1-2)"
    else
        echo "❌ FEATURE 3: ÉCHEC"
        grep "Feature 3\|DEK" /tmp/test_hsm_usb.log | head -5
    fi
    F3_OK=0
    DEK_OK=0
fi

echo ""
echo "=== FEATURE 4: Encryption MAVLink ==="
echo ""

ENCRYPTED=$(grep -c "Encrypted PAYLOAD" /tmp/test_hsm_usb.log 2>/dev/null || echo "0")
ACTIVATION=$(grep -c "PAYLOAD-ONLY activée" /tmp/test_hsm_usb.log 2>/dev/null || echo "0")

echo "Statistiques:"
echo "  - Messages d'activation: $ACTIVATION"
echo "  - Payloads chiffrés:     $ENCRYPTED"
echo ""

if [ "$ENCRYPTED" -gt 0 ]; then
    echo "✅ FEATURE 4: SUCCÈS ($ENCRYPTED payloads chiffrés)"
    echo ""
    echo "Exemples:"
    grep "Encrypted PAYLOAD" /tmp/test_hsm_usb.log | head -5
    F4_OK=1
else
    if [ "$DEK_OK" -eq 0 ]; then
        echo "⚠️  FEATURE 4: Inactive (DEK non disponible)"
    else
        echo "❌ FEATURE 4: Pas d'encryption détectée"
        echo "   Vérifier MAV_ENCRYPT=1"
    fi
    F4_OK=0
fi

echo ""
echo "=========================================="
echo "  CONNECTIVITÉ MAVLINK"
echo "=========================================="
echo ""

if grep -q "heartbeat\|APM.*Copter" /tmp/mavproxy_hsm.log; then
    echo "✅ MAVProxy connecté"
    if [ "$ENCRYPTED" -gt 0 ]; then
        echo "   ⚠️  Header lisible mais payload chiffré (correct!)"
    else
        echo "   - Communication normale (encryption inactive)"
    fi
else
    echo "⚠️  MAVProxy: Pas de heartbeat"
fi

echo ""
echo "=========================================="
echo "  VERDICT FINAL"
echo "=========================================="
echo ""

TOTAL=$((F1_OK + F2_OK + F3_OK + F4_OK))

if [ "$TOTAL" -eq 4 ]; then
    echo "🎉🎉🎉 PARFAIT! TOUTES LES FEATURES FONCTIONNENT! 🎉🎉🎉"
    echo ""
    echo "✅ Feature 1: HSM initialisé via USB"
    echo "✅ Feature 2: Keypair ECDSA générée"
    echo "✅ Feature 3: DEK disponible"
    echo "✅ Feature 4: $ENCRYPTED payloads chiffrés"
    echo ""
    echo "🚀 TEST USB RÉEL: 100% SUCCÈS!"

elif [ "$F1_OK" -eq 1 ]; then
    echo "✅ Communication HSM USB fonctionne!"
    echo ""
    echo "État des features:"
    [ "$F1_OK" -eq 1 ] && echo "✅ Feature 1: HSM Init" || echo "❌ Feature 1"
    [ "$F2_OK" -eq 1 ] && echo "✅ Feature 2: Keypair" || echo "❌ Feature 2"
    [ "$F3_OK" -eq 1 ] && echo "✅ Feature 3: DEK" || echo "❌ Feature 3"
    [ "$F4_OK" -eq 1 ] && echo "✅ Feature 4: Encryption" || echo "❌ Feature 4"

    echo ""
    echo "Features partiellement fonctionnelles - vérifier logs"

else
    echo "❌ COMMUNICATION HSM ÉCHOUÉE"
    echo ""
    echo "Diagnostics:"
    echo ""
    echo "1. Vérifier branchement USB:"
    ls -l /dev/ttyUSB0 2>/dev/null || echo "   ❌ /dev/ttyUSB0 non trouvé"

    echo ""
    echo "2. Tester communication manuelle:"
    echo "   screen /dev/ttyUSB0 115200"
    echo "   Puis taper: on"
    echo "   (devrait afficher ATR du HSM)"

    echo ""
    echo "3. Vérifier firmware HSM:"
    echo "   - Firmware ESP32 installé?"
    echo "   - Baudrate correct (115200)?"

    echo ""
    echo "4. Logs détaillés:"
    echo "   cat /tmp/test_hsm_usb.log | grep HSM"
fi

echo ""
echo "=========================================="
echo ""

# Cleanup
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo "Logs complets:"
echo "  - ArduCopter: /tmp/test_hsm_usb.log"
echo "  - MAVProxy:   /tmp/mavproxy_hsm.log"
echo ""
echo "Analyse manuelle:"
echo "  grep 'HSM:' /tmp/test_hsm_usb.log"
echo "  grep 'Feature' /tmp/test_hsm_usb.log"
echo "  grep 'Encrypted' /tmp/test_hsm_usb.log"
echo ""
echo "Done!"
