#!/bin/bash
# Test HSM avec PLUSIEURS délais différents pour trouver le timing optimal
# Ce script teste progressivement des délais croissants

echo "=============================================="
echo "  Test HSM: SCAN des Délais Optimaux"
echo "=============================================="
echo ""
echo "⚠️  IMPORTANT: Débranchez/rebranchez le HSM MAINTENANT!"
echo "   Attendez 10 secondes après avoir rebranché"
echo ""
read -p "Appuyez sur ENTER quand le HSM est prêt..."

# Vérifier HSM
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ /dev/ttyUSB0 non trouvé!"
    exit 1
fi
echo "✅ HSM détecté"
echo ""

# Créer répertoire pour les résultats
mkdir -p feature3/timing_tests
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULT_DIR="feature3/timing_tests/scan_$TIMESTAMP"
mkdir -p "$RESULT_DIR"

echo "📁 Résultats seront dans: $RESULT_DIR"
echo ""

# Fonction pour tester un délai spécifique
test_delay() {
    local delay_on=$1
    local delay_after_atr=$2
    local delay_before_select=$3
    local test_name=$4

    echo ""
    echo "================================================"
    echo "  TEST: $test_name"
    echo "================================================"
    echo "  Délai après ON: ${delay_on}ms"
    echo "  Délai après ATR: ${delay_after_atr}ms"
    echo "  Délai avant SELECT: ${delay_before_select}ms"
    echo "  Total attente: $((delay_on + delay_after_atr + delay_before_select))ms"
    echo ""

    # Modifier temporairement AP_HSM.cpp
    local cpp_file="libraries/AP_HSM/AP_HSM.cpp"
    local backup_file="${cpp_file}.backup_timing"

    # Backup original
    cp "$cpp_file" "$backup_file"

    # Modifier les délais
    sed -i "s/hal\.scheduler->delay(2500);  \/\/ Augmenté de 1500 à 2500ms/hal.scheduler->delay($delay_on);  \/\/ Test delay/" "$cpp_file"
    sed -i "s/while ((AP_HAL::millis() - start) < 3000 && !atr_complete) {/while ((AP_HAL::millis() - start) < $delay_after_atr \&\& !atr_complete) {/" "$cpp_file"
    sed -i "s/hal\.scheduler->delay(500);/hal.scheduler->delay($delay_before_select);/" "$cpp_file"

    echo "⚙️  Recompilation avec nouveaux délais..."
    ./waf copter > /dev/null 2>&1

    if [ $? -ne 0 ]; then
        echo "❌ Erreur de compilation!"
        cp "$backup_file" "$cpp_file"
        return 1
    fi

    echo "✅ Compilation OK"

    # Lancer test
    local logfile="$RESULT_DIR/${test_name}.log"
    echo "🚀 Lancement ArduCopter (timeout 12s)..."

    timeout 12s build/sitl/bin/arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 --console > "$logfile" 2>&1

    # Restaurer fichier original
    cp "$backup_file" "$cpp_file"

    # Analyser résultat
    echo ""
    echo "📊 RÉSULTAT:"

    if grep -q "✓ Feature 1 complétée avec succès" "$logfile"; then
        echo "   ✅✅✅ Feature 1: SUCCÈS!"

        if grep -q "✓ Feature 2 complétée avec succès" "$logfile"; then
            echo "   ✅✅✅ Feature 2: SUCCÈS!"

            if grep -q "✓ Feature 3 complétée avec succès" "$logfile"; then
                echo "   ✅✅✅ Feature 3: SUCCÈS!"
                echo ""
                echo "   🎉🎉🎉 TOUS LES TESTS RÉUSSIS! 🎉🎉🎉"
                echo "   ✨ Délais optimaux trouvés! ✨"
                return 0
            fi
        fi
        return 0
    else
        echo "   ❌ Feature 1: ÉCHEC"

        # Afficher les erreurs
        if grep -q "Timeout SELECT" "$logfile"; then
            echo "      → Timeout sur SELECT applet CC"
        fi
        if grep -q "ERROR No Command" "$logfile"; then
            echo "      → HSM répond 'ERROR No Command'"
        fi

        return 1
    fi
}

# Attendre que l'utilisateur soit prêt
echo "⏳ Attente 2 secondes avant de commencer..."
sleep 2

# SÉRIE DE TESTS PROGRESSIFS
echo ""
echo "╔════════════════════════════════════════╗"
echo "║  DÉBUT DU SCAN DES DÉLAIS OPTIMAUX    ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Test 1: Délais courts (baseline actuel qui échoue)
test_delay 2500 3000 500 "test1_baseline_2.5s"
RESULT1=$?

if [ $RESULT1 -eq 0 ]; then
    echo ""
    echo "🎉 Délais actuels suffisants!"
    exit 0
fi

sleep 2

# Test 2: Augmenter délai après ON à 3.5s
test_delay 3500 3000 500 "test2_on_3.5s"
RESULT2=$?

if [ $RESULT2 -eq 0 ]; then
    echo ""
    echo "✅ SOLUTION TROUVÉE: Délai après ON = 3500ms"
    exit 0
fi

sleep 2

# Test 3: Augmenter délai après ON à 4s
test_delay 4000 3000 500 "test3_on_4s"
RESULT3=$?

if [ $RESULT3 -eq 0 ]; then
    echo ""
    echo "✅ SOLUTION TROUVÉE: Délai après ON = 4000ms"
    exit 0
fi

sleep 2

# Test 4: Augmenter délai ATR à 4s
test_delay 4000 4000 500 "test4_atr_4s"
RESULT4=$?

if [ $RESULT4 -eq 0 ]; then
    echo ""
    echo "✅ SOLUTION TROUVÉE: Délai après ON = 4000ms, ATR = 4000ms"
    exit 0
fi

sleep 2

# Test 5: Augmenter délai avant SELECT à 1s
test_delay 4000 4000 1000 "test5_before_select_1s"
RESULT5=$?

if [ $RESULT5 -eq 0 ]; then
    echo ""
    echo "✅ SOLUTION TROUVÉE: ON=4s, ATR=4s, avant SELECT=1s"
    exit 0
fi

sleep 2

# Test 6: Délais TRÈS longs pour être sûr
test_delay 5000 5000 1500 "test6_very_long_5s"
RESULT6=$?

if [ $RESULT6 -eq 0 ]; then
    echo ""
    echo "✅ SOLUTION TROUVÉE: Délais longs nécessaires (ON=5s, ATR=5s, SELECT=1.5s)"
    exit 0
fi

# Si on arrive ici, aucun délai n'a fonctionné
echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  ⚠️  AUCUN DÉLAI N'A FONCTIONNÉ              ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "Problème plus profond que les délais:"
echo "  1. HSM toujours en état instable malgré reset"
echo "  2. Problème matériel avec le HSM"
echo "  3. Conflit avec autre processus"
echo ""
echo "📁 Logs de tous les tests: $RESULT_DIR"
echo ""
echo "Actions suggérées:"
echo "  1. Débrancher le HSM pendant 30 secondes (pas 10)"
echo "  2. Vérifier: lsof /dev/ttyUSB0"
echo "  3. Vérifier: dmesg | tail -50"

exit 1
