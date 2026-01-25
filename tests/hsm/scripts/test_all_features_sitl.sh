#!/bin/bash

################################################################################
# Test Complet Features 1-4 avec SITL
#
# Valide séquentiellement:
# - Feature 1: Initialisation HSM (OFF/ON/SELECT/VERIFY)
# - Feature 2: Keypair ECDSA P-256 + Storage EEPROM
# - Feature 3: DEK ChaCha20-256 (ECDH + HKDF + Wrap)
# - Feature 4: Encryption MAVLink payload-only
#
# Condition: Chaque feature doit PASSER avant de tester la suivante
################################################################################

set -e  # Exit on error

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ARDUPILOT_ROOT="/home/samwitwity/Code_Sources/ardupilot_claude"
HSM_DEVICE="/dev/ttyUSB0"
HSM_BAUD="115200"
SITL_WAIT_BOOT=15  # Secondes pour boot complet
TEST_DURATION=30   # Secondes pour observer chaque feature

# Logs
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGDIR="$ARDUPILOT_ROOT/test_logs"
LOGFILE="$LOGDIR/test_features_sitl_${TIMESTAMP}.log"
mkdir -p "$LOGDIR"

# Compteurs résultats
FEATURES_PASSED=0
FEATURES_FAILED=0

################################################################################
# Fonctions Utilitaires
################################################################################

print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

cleanup() {
    print_info "Nettoyage processus..."
    pkill -9 arducopter 2>/dev/null || true
    pkill -9 mavproxy 2>/dev/null || true
    sleep 2

    # Vérifier que UART est libre
    if lsof "$HSM_DEVICE" >/dev/null 2>&1; then
        print_warning "UART $HSM_DEVICE encore utilisé"
        lsof "$HSM_DEVICE"
    fi
}

check_hsm() {
    if [ ! -e "$HSM_DEVICE" ]; then
        print_error "HSM non détecté sur $HSM_DEVICE"
        exit 1
    fi

    if lsof "$HSM_DEVICE" >/dev/null 2>&1; then
        print_warning "HSM $HSM_DEVICE déjà utilisé par:"
        lsof "$HSM_DEVICE"
        print_info "Nettoyage..."
        cleanup
    fi

    print_success "HSM détecté sur $HSM_DEVICE"
}

################################################################################
# Build ArduCopter
################################################################################

build_arducopter() {
    print_header "ÉTAPE 0: Build ArduCopter"

    cd "$ARDUPILOT_ROOT"

    print_info "Configuration waf..."
    ./waf configure --board sitl 2>&1 | tee -a "$LOGFILE"

    print_info "Compilation ArduCopter..."
    ./waf copter 2>&1 | tee -a "$LOGFILE"

    if [ $? -eq 0 ]; then
        print_success "Compilation réussie"
        ls -lh build/sitl/bin/arducopter | tee -a "$LOGFILE"
        return 0
    else
        print_error "Échec compilation"
        return 1
    fi
}

################################################################################
# Lancement SITL
################################################################################

start_sitl() {
    print_header "LANCEMENT SITL + HSM"

    cd "$ARDUPILOT_ROOT"

    # Lancer ArduCopter en background
    print_info "Démarrage ArduCopter SITL..."
    build/sitl/bin/arducopter \
        --model + \
        --serial1 "uart:${HSM_DEVICE}:${HSM_BAUD}" \
        --defaults Tools/autotest/default_params/copter.parm \
        > "$LOGFILE" 2>&1 &

    ARDUCOPTER_PID=$!
    echo "ArduCopter PID: $ARDUCOPTER_PID" | tee -a "$LOGFILE"

    print_info "Attente boot ArduCopter ($SITL_WAIT_BOOT secondes)..."
    sleep "$SITL_WAIT_BOOT"

    # Vérifier qu'ArduCopter tourne toujours
    if ! kill -0 $ARDUCOPTER_PID 2>/dev/null; then
        print_error "ArduCopter s'est arrêté prématurément"
        tail -50 "$LOGFILE"
        return 1
    fi

    print_success "ArduCopter SITL en cours (PID: $ARDUCOPTER_PID)"

    # Lancer MAVProxy en background (pour générer trafic)
    print_info "Démarrage MAVProxy..."
    mavproxy.py \
        --master=tcp:127.0.0.1:5760 \
        --out=udp:127.0.0.1:14550 \
        --daemon \
        > /dev/null 2>&1 &

    MAVPROXY_PID=$!
    echo "MAVProxy PID: $MAVPROXY_PID" | tee -a "$LOGFILE"

    sleep 3

    print_success "SITL démarré avec succès"
    return 0
}

################################################################################
# Test Feature 1: Initialisation HSM
################################################################################

test_feature1() {
    print_header "TEST FEATURE 1: Initialisation HSM"

    print_info "Recherche logs Feature 1..."
    sleep 2

    # Vérifier séquence complète
    local checks=(
        "HSM: Démarrage initialisation LeMonolith"
        "HSM: SE désactivé"
        "HSM: SE activé"
        "HSM: Application CC sélectionnée"
        "HSM: PIN User vérifié avec succès"
        "✓ Feature 1 complétée avec succès"
    )

    local all_ok=true
    for check in "${checks[@]}"; do
        if grep -q "$check" "$LOGFILE"; then
            print_success "Trouvé: $check"
        else
            print_error "Manquant: $check"
            all_ok=false
        fi
    done

    if $all_ok; then
        print_success "FEATURE 1: SUCCÈS ✅"
        ((FEATURES_PASSED++))
        return 0
    else
        print_error "FEATURE 1: ÉCHEC ❌"
        ((FEATURES_FAILED++))

        print_info "Logs HSM disponibles:"
        grep "HSM:" "$LOGFILE" | tail -20

        return 1
    fi
}

################################################################################
# Test Feature 2: Keypair ECDSA P-256
################################################################################

test_feature2() {
    print_header "TEST FEATURE 2: Keypair ECDSA P-256"

    print_info "Recherche logs Feature 2..."
    sleep 2

    local checks=(
        "HSM: Génération keypair P-256 avec micro-ecc"
        "HSM: Clé privée stockée dans HSM"
        "HSM: Clé publique (64 bytes)"
        "✓ Feature 2 complétée avec succès"
    )

    local all_ok=true
    for check in "${checks[@]}"; do
        if grep -q "$check" "$LOGFILE"; then
            print_success "Trouvé: $check"
        else
            print_error "Manquant: $check"
            all_ok=false
        fi
    done

    # Vérifier que clé publique est affichée (64 bytes hex)
    if grep "Public key (64 bytes):" "$LOGFILE" | grep -E "[0-9A-F]{128}" >/dev/null; then
        print_success "Clé publique P-256 (64 bytes) générée"
    else
        print_warning "Clé publique format invalide"
        all_ok=false
    fi

    if $all_ok; then
        print_success "FEATURE 2: SUCCÈS ✅"
        ((FEATURES_PASSED++))
        return 0
    else
        print_error "FEATURE 2: ÉCHEC ❌"
        ((FEATURES_FAILED++))

        print_info "Logs Feature 2 disponibles:"
        grep -A 5 "Feature 2" "$LOGFILE" | tail -20

        return 1
    fi
}

################################################################################
# Test Feature 3: DEK ChaCha20-256
################################################################################

test_feature3() {
    print_header "TEST FEATURE 3: DEK ChaCha20-256"

    print_info "Recherche logs Feature 3..."
    sleep 2

    local checks=(
        "HSM: Génération DEK (32 bytes)"
        "HSM: ECDH avec clé publique remote"
        "HSM: HKDF-SHA256 dérivation wrapping key"
        "HSM: Wrap DEK avec wrapping key"
        "HSM: DEK (32 bytes):"
        "✓ Feature 3 complétée avec succès"
    )

    local all_ok=true
    for check in "${checks[@]}"; do
        if grep -q "$check" "$LOGFILE"; then
            print_success "Trouvé: $check"
        else
            # Feature 3 storage peut échouer (mode RAM-only)
            if [[ "$check" == *"stockée"* ]] || [[ "$check" == *"WRITE"* ]]; then
                print_warning "Optionnel manquant: $check (mode RAM-only OK)"
            else
                print_error "Manquant: $check"
                all_ok=false
            fi
        fi
    done

    # Vérifier DEK générée (32 bytes hex = 64 caractères)
    if grep "DEK (32 bytes):" "$LOGFILE" | grep -E "[0-9A-F]{64}" >/dev/null; then
        print_success "DEK ChaCha20-256 (32 bytes) générée"
    else
        print_warning "DEK format invalide ou manquant"
        all_ok=false
    fi

    # Vérifier mode RAM-only si storage échoue
    if grep "Mode RAM-only activé" "$LOGFILE" >/dev/null; then
        print_warning "Mode RAM-only détecté (DEK non persistante)"
        print_info "C'est acceptable - DEK disponible en cache pour Feature 4"
    fi

    if $all_ok; then
        print_success "FEATURE 3: SUCCÈS ✅"
        ((FEATURES_PASSED++))
        return 0
    else
        print_error "FEATURE 3: ÉCHEC ❌"
        ((FEATURES_FAILED++))

        print_info "Logs Feature 3 disponibles:"
        grep -A 10 "Feature 3" "$LOGFILE" | tail -30

        return 1
    fi
}

################################################################################
# Test Feature 4: Encryption MAVLink
################################################################################

test_feature4() {
    print_header "TEST FEATURE 4: Encryption MAVLink"

    print_info "Attente trafic MAVLink ($TEST_DURATION secondes)..."

    # Compter appels comm_send_buffer AVANT
    local calls_before=$(grep -c "comm_send_buffer called" "$LOGFILE" 2>/dev/null || echo "0")

    # Attendre génération trafic
    sleep "$TEST_DURATION"

    # Compter appels comm_send_buffer APRÈS
    local calls_after=$(grep -c "comm_send_buffer called" "$LOGFILE" 2>/dev/null || echo "0")
    local calls_diff=$((calls_after - calls_before))

    print_info "Analyse logs Feature 4..."

    # Checks principaux
    local checks_critical=(
        "Encryption MAVLink PAYLOAD-ONLY activée"
    )

    local checks_optional=(
        "Encrypted PAYLOAD"
        "comm_send_buffer called"
    )

    local critical_ok=true
    for check in "${checks_critical[@]}"; do
        if grep -q "$check" "$LOGFILE"; then
            print_success "Trouvé: $check"
        else
            print_warning "Manquant (critique): $check"
            critical_ok=false
        fi
    done

    # Vérifier logs encryption
    local encryption_count=$(grep -c "Encrypted PAYLOAD" "$LOGFILE" 2>/dev/null || echo "0")

    if [ "$encryption_count" -gt 0 ]; then
        print_success "Messages chiffrés détectés: $encryption_count"

        # Montrer exemples
        print_info "Exemples logs encryption:"
        grep "Encrypted PAYLOAD" "$LOGFILE" | head -5 | tee -a "$LOGFILE"

        print_success "FEATURE 4: SUCCÈS ✅"
        ((FEATURES_PASSED++))
        return 0

    elif [ "$calls_diff" -gt 0 ]; then
        print_warning "comm_send_buffer appelée $calls_diff fois"
        print_warning "Mais aucun log 'Encrypted PAYLOAD' détecté"

        print_info "Causes possibles:"
        echo "  1. MAV_ENCRYPT=0 (vérifier param set MAV_ENCRYPT 1)"
        echo "  2. DEK non disponible (vérifier Feature 3 OK)"
        echo "  3. Logs noyés (augmenter durée test)"

        print_error "FEATURE 4: ÉCHEC PARTIEL ⚠️"
        print_info "Code encryption implémenté mais pas activé"
        ((FEATURES_FAILED++))
        return 1

    else
        print_error "Aucun trafic MAVLink détecté"
        print_info "comm_send_buffer jamais appelée"

        print_info "Solutions:"
        echo "  1. Utiliser sim_vehicle.py (SITL complet avec GPS/IMU)"
        echo "  2. Forcer trafic avec commandes MAVProxy"
        echo "  3. Augmenter TEST_DURATION"

        print_error "FEATURE 4: ÉCHEC ❌"
        ((FEATURES_FAILED++))
        return 1
    fi
}

################################################################################
# Génération Rapport Final
################################################################################

generate_report() {
    print_header "RAPPORT FINAL"

    echo ""
    echo "┌─────────────────────────────────────────────────┐"
    echo "│         RÉSULTATS TESTS FEATURES 1-4           │"
    echo "├─────────────────────────────────────────────────┤"

    printf "│ Features passées:  %-27s │\n" "$FEATURES_PASSED/4"
    printf "│ Features échouées: %-27s │\n" "$FEATURES_FAILED/4"

    local percentage=$((FEATURES_PASSED * 100 / 4))
    printf "│ Pourcentage:       %-27s │\n" "$percentage%"

    echo "├─────────────────────────────────────────────────┤"

    if [ $FEATURES_PASSED -eq 4 ]; then
        echo "│ 🎉 SUCCÈS COMPLET - Prêt pour hardware réel   │"
    elif [ $FEATURES_PASSED -eq 3 ]; then
        echo "│ ⚠️  SUCCÈS PARTIEL - Feature 4 à débugger      │"
    elif [ $FEATURES_PASSED -ge 2 ]; then
        echo "│ ⚠️  SUCCÈS PARTIEL - Features avancées KO      │"
    else
        echo "│ ❌ ÉCHEC - Problème initialisation HSM         │"
    fi

    echo "└─────────────────────────────────────────────────┘"
    echo ""

    print_info "Log complet: $LOGFILE"

    # Statistiques
    local total_lines=$(wc -l < "$LOGFILE")
    local hsm_lines=$(grep -c "HSM:" "$LOGFILE" || echo "0")
    local error_lines=$(grep -c "Erreur" "$LOGFILE" || echo "0")

    echo ""
    echo "Statistiques Log:"
    echo "  - Lignes totales: $total_lines"
    echo "  - Lignes HSM: $hsm_lines"
    echo "  - Erreurs: $error_lines"

    # Recommandations
    echo ""
    print_info "RECOMMANDATIONS:"

    if [ $FEATURES_PASSED -eq 4 ]; then
        echo "  ✅ Toutes features validées en SITL"
        echo "  ✅ Prêt pour tests hardware réel"
        echo "  ➡️  Prochaine étape: Test sur drone physique"
    elif [ $FEATURES_PASSED -eq 3 ]; then
        echo "  ✅ Features 1-3 validées"
        echo "  ⚠️  Feature 4 nécessite investigation:"
        echo "     1. Vérifier MAV_ENCRYPT=1"
        echo "     2. Tester avec sim_vehicle.py (SITL complet)"
        echo "     3. Forcer trafic MAVLink"
        echo "  ➡️  Prochaine étape: Débug Feature 4 avant hardware"
    else
        echo "  ❌ Problèmes avec Features de base"
        echo "  ➡️  NE PAS passer au hardware réel"
        echo "  ➡️  Débugger Features échouées d'abord"
        echo "     - Vérifier HSM connecté"
        echo "     - Vérifier timings (délais suffisants)"
        echo "     - Reset HSM hardware (30-60s)"
    fi
}

################################################################################
# MAIN
################################################################################

main() {
    print_header "TEST COMPLET FEATURES 1-4 AVEC SITL"

    echo "Configuration:"
    echo "  - ArduPilot: $ARDUPILOT_ROOT"
    echo "  - HSM Device: $HSM_DEVICE"
    echo "  - HSM Baud: $HSM_BAUD"
    echo "  - Log File: $LOGFILE"
    echo "  - Test Duration: $TEST_DURATION secondes"
    echo ""

    # Trap pour cleanup
    trap cleanup EXIT

    # Étape 0: Vérifications préalables
    check_hsm
    cleanup

    # Étape 1: Build
    if ! build_arducopter; then
        print_error "Échec build - Abandon"
        exit 1
    fi

    echo ""

    # Étape 2: Démarrage SITL
    if ! start_sitl; then
        print_error "Échec démarrage SITL - Abandon"
        exit 1
    fi

    echo ""

    # Étape 3: Test Feature 1
    if ! test_feature1; then
        print_error "Feature 1 échouée - Abandon tests suivants"
        generate_report
        exit 1
    fi

    echo ""

    # Étape 4: Test Feature 2
    if ! test_feature2; then
        print_error "Feature 2 échouée - Abandon tests suivants"
        generate_report
        exit 1
    fi

    echo ""

    # Étape 5: Test Feature 3
    if ! test_feature3; then
        print_error "Feature 3 échouée - Abandon tests suivants"
        generate_report
        exit 1
    fi

    echo ""

    # Étape 6: Test Feature 4 (non bloquant si échec)
    test_feature4
    # On continue même si Feature 4 échoue (peut nécessiter SITL complet)

    echo ""

    # Rapport final
    generate_report

    # Code de sortie
    if [ $FEATURES_PASSED -eq 4 ]; then
        exit 0
    elif [ $FEATURES_PASSED -eq 3 ]; then
        exit 10  # Code spécial: Features 1-3 OK, Feature 4 KO
    else
        exit 1
    fi
}

# Lancer main
main "$@"
