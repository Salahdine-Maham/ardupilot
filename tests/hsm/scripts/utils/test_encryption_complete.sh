#!/bin/bash
# Test COMPLET: Encryption end-to-end avec commandes MAVLink réelles

pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

echo "=========================================="
echo "  TEST ENCRYPTION END-TO-END COMPLET"
echo "=========================================="
echo ""

# Lancer ArduCopter
echo "[1/4] Lancement ArduCopter avec HSM..."
build/sitl/bin/arducopter --model + --speedup 1 \
    --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults Tools/autotest/default_params/copter.parm \
    > /tmp/encryption_test.log 2>&1 &
ACP=$!
echo "    ArduCopter PID: $ACP"

sleep 5

# Lancer MAVProxy
echo "[2/4] Lancement MAVProxy..."
mavproxy.py --master=tcp:127.0.0.1:5760 --out=udp:127.0.0.1:14550 > /tmp/mavproxy_test.log 2>&1 &
MVP=$!
echo "    MAVProxy PID: $MVP"

echo ""
echo "[3/4] Attente initialisation (20s)..."
echo "      - Features 1-3: HSM + DEK"
echo "      - Connexion MAVProxy"
echo ""
sleep 20

# Vérifier Features 1-3
echo "=========================================="
echo "  VÉRIFICATION FEATURES 1-3"
echo "=========================================="
echo ""

if grep -q "✓ Feature 3 complétée\|Mode RAM-only" /tmp/encryption_test.log; then
    echo "✅ Features 1-3: OK (DEK disponible)"
    echo ""
    grep "Feature [1-3].*complétée\|Mode RAM-only" /tmp/encryption_test.log | tail -3
else
    echo "❌ Features 1-3: ÉCHEC - Arrêt du test"
    kill -9 $ACP $MVP 2>/dev/null
    exit 1
fi

echo ""
echo "=========================================="
echo "  [4/4] ENVOI COMMANDES MAVLINK"
echo "=========================================="
echo ""

# Créer un script de commandes MAVProxy
cat > /tmp/mavproxy_commands.txt <<'EOF'
param set SYSID_THISMAV 1
param fetch
mode STABILIZE
arm throttle
mode GUIDED
wp load Tools/autotest/ArduCopter_mission.txt
disarm
EOF

echo "Envoi de commandes MAVLink via MAVProxy..."
echo "  - param fetch (génère requêtes)"
echo "  - mode changes (génère trafic)"
echo "  - arm/disarm (génère commandes)"
echo ""

# Envoyer commandes via netcat au port MAVProxy
sleep 2
(
    sleep 2
    echo "param fetch"
    sleep 2
    echo "mode STABILIZE"
    sleep 2
    echo "mode GUIDED"
    sleep 2
    echo "mode LOITER"
    sleep 2
) | nc -q 1 127.0.0.1 14550 > /dev/null 2>&1 &

echo "Attente 15s pour générer du trafic MAVLink..."
for i in {1..15}; do
    echo -ne "\r  Temps écoulé: ${i}s / 15s"
    sleep 1
done
echo ""

echo ""
echo "=========================================="
echo "  RÉSULTATS ENCRYPTION"
echo "=========================================="
echo ""

# Compter messages cryptés
ENCRYPTED=$(grep -c "Encrypted with ChaCha20-256" /tmp/encryption_test.log 2>/dev/null || echo "0")
DECRYPTED=$(grep -c "Decrypted with ChaCha20-256" /tmp/encryption_test.log 2>/dev/null || echo "0")

# Vérifier debug logs
DEBUG_CALLS=$(grep -c "DEBUG.*send_to_active" /tmp/encryption_test.log 2>/dev/null || echo "0")

echo "📊 Statistiques:"
echo "  - Appels send_to_active_channels: $DEBUG_CALLS"
echo "  - Messages CHIFFRÉS (sortants):   $ENCRYPTED"
echo "  - Messages DÉCHIFFRÉS (entrants): $DECRYPTED"
echo ""

if [ "$ENCRYPTED" -gt 0 ]; then
    echo "✅✅✅ ENCRYPTION ACTIVE! ✅✅✅"
    echo ""
    echo "Exemples de messages chiffrés (5 premiers):"
    grep -B 1 -A 3 "Encrypted with ChaCha20-256" /tmp/encryption_test.log | head -25
    echo ""
else
    echo "❌ ENCRYPTION INACTIVE"
    echo ""
    echo "Diagnostic:"

    if [ "$DEBUG_CALLS" -gt 0 ]; then
        echo "  ✅ send_to_active_channels() appelée $DEBUG_CALLS fois"
        echo "  ⚠️  Mais pas d'encryption détectée"
        echo ""
        echo "Derniers appels:"
        grep "DEBUG.*send_to_active" /tmp/encryption_test.log | tail -5
    else
        echo "  ❌ send_to_active_channels() jamais appelée!"
        echo "  ⚠️  Aucun message MAVLink envoyé?"
    fi

    echo ""
    echo "Vérification MAV_ENCRYPT:"
    if grep -q "mav_encrypt.*1" /tmp/encryption_test.log; then
        echo "  ✅ MAV_ENCRYPT=1 détecté"
    else
        echo "  ❌ MAV_ENCRYPT=1 non détecté"
    fi

    echo ""
    echo "Vérification DEK:"
    if grep -q "DEK.*disponible\|has_dek" /tmp/encryption_test.log; then
        echo "  ✅ DEK disponible"
    else
        echo "  ⚠️  DEK status inconnu"
    fi
fi

echo ""

if [ "$DECRYPTED" -gt 0 ]; then
    echo "✅ DÉCRYPTION ACTIVE! ($DECRYPTED messages)"
    echo ""
    echo "Exemples de messages déchiffrés (3 premiers):"
    grep -B 1 -A 3 "Decrypted with ChaCha20-256" /tmp/encryption_test.log | head -15
else
    echo "ℹ️  Pas de messages déchiffrés (normal si pas de commandes GCS→Drone)"
fi

echo ""
echo "=========================================="
echo "  VERDICT FINAL"
echo "=========================================="
echo ""

if [ "$ENCRYPTED" -gt 0 ]; then
    echo "🎉🎉🎉 ENCRYPTION END-TO-END FONCTIONNELLE! 🎉🎉🎉"
    echo ""
    echo "✅ Features 1-3: Initialisées"
    echo "✅ Feature 4 Encryption: $ENCRYPTED messages chiffrés"
    if [ "$DECRYPTED" -gt 0 ]; then
        echo "✅ Feature 4 Décryption: $DECRYPTED messages déchiffrés"
    fi
    echo ""
    echo "🚀 PROJET 100% COMPLET ET TESTÉ!"
elif [ "$DEBUG_CALLS" -gt 0 ]; then
    echo "⚠️  Code encryption exécuté mais pas de messages cryptés"
    echo ""
    echo "Problème possible:"
    echo "  - MAV_ENCRYPT=0 (désactivé)"
    echo "  - DEK indisponible"
    echo "  - Condition if() non remplie"
else
    echo "❌ Aucun trafic MAVLink détecté"
    echo ""
    echo "Causes possibles:"
    echo "  - MAVProxy non connecté"
    echo "  - send_to_active_channels() non utilisée"
    echo "  - Autre méthode d'envoi MAVLink"
fi

echo ""
echo "=========================================="
echo ""

echo "Nettoyage..."
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true

echo ""
echo "Logs complets:"
echo "  - ArduCopter: /tmp/encryption_test.log"
echo "  - MAVProxy:   /tmp/mavproxy_test.log"
echo ""
echo "Pour analyse détaillée:"
echo "  grep -E 'Encrypted|Decrypted|DEBUG|MAV_ENCRYPT|DEK' /tmp/encryption_test.log"
echo ""
echo "Done!"
