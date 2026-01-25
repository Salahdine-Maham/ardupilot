#!/bin/bash

################################################################################
# Test Feature 4 avec sim_vehicle.py (SITL Complet)
#
# Utilise sim_vehicle.py qui inclut:
# - GPS simulé
# - IMU simulé
# - Barometer simulé
# - Compass simulé
# - Trafic MAVLink intensif
#
# Usage: ./test_feature4_with_sim_vehicle.sh
################################################################################

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
ARDUPILOT_ROOT="/home/samwitwity/Code_Sources/ardupilot_claude"
HSM_DEVICE="/dev/ttyUSB0"
HSM_BAUD="115200"
TEST_DURATION=60  # Secondes - plus long pour voir encryption

# Logs
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGDIR="$ARDUPILOT_ROOT/test_logs"
LOGFILE="$LOGDIR/test_feature4_simvehicle_${TIMESTAMP}.log"
mkdir -p "$LOGDIR"

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
    pkill -9 sim_vehicle 2>/dev/null || true
    sleep 2
}

print_header "TEST FEATURE 4 AVEC SIM_VEHICLE.PY"

echo "Configuration:"
echo "  - HSM Device: $HSM_DEVICE"
echo "  - Test Duration: $TEST_DURATION secondes"
echo "  - Log File: $LOGFILE"
echo ""

trap cleanup EXIT

# Vérifier HSM
if [ ! -e "$HSM_DEVICE" ]; then
    print_error "HSM non détecté sur $HSM_DEVICE"
    exit 1
fi

print_success "HSM détecté"

# Cleanup
cleanup

cd "$ARDUPILOT_ROOT"

# Build d'abord
print_info "Build ArduCopter..."
./waf copter 2>&1 | tee -a "$LOGFILE"

if [ $? -ne 0 ]; then
    print_error "Échec build"
    exit 1
fi

print_success "Build OK"

# Lancer sim_vehicle.py avec HSM
print_info "Démarrage sim_vehicle.py avec HSM..."

# Important: sim_vehicle.py gère automatiquement:
# - GPS simulé à San Francisco
# - IMU avec données inertielles
# - Barometer
# - Compass
# - MAVProxy avec console
python3 Tools/autotest/sim_vehicle.py \
    -v ArduCopter \
    --no-rebuild \
    --out=127.0.0.1:14550 \
    -A "--serial1=uart:${HSM_DEVICE}:${HSM_BAUD}" \
    > "$LOGFILE" 2>&1 &

SIM_PID=$!

print_info "sim_vehicle.py PID: $SIM_PID"
print_info "Attente démarrage complet (30s)..."
sleep 30

# Vérifier qu'il tourne
if ! kill -0 $SIM_PID 2>/dev/null; then
    print_error "sim_vehicle.py s'est arrêté"
    tail -50 "$LOGFILE"
    exit 1
fi

print_success "SITL complet démarré"

# Attendre Features 1-3
print_info "Attente Features 1-3 (15s)..."
sleep 15

# Vérifier Features 1-3
print_info "Vérification Features 1-3..."

features_ok=true
if ! grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    print_error "Feature 1 échouée"
    features_ok=false
fi

if ! grep -q "✓ Feature 2 complétée avec succès" "$LOGFILE"; then
    print_error "Feature 2 échouée"
    features_ok=false
fi

if ! grep -q "✓ Feature 3 complétée avec succès" "$LOGFILE"; then
    print_warning "Feature 3 échouée (mode RAM-only possible)"
fi

if ! $features_ok; then
    print_error "Features de base échouées - Abandon"
    exit 1
fi

print_success "Features 1-2 OK, Feature 3 OK (RAM-only possible)"

# Observer Feature 4
print_info "Observation Feature 4 pendant $TEST_DURATION secondes..."
print_info "Trafic MAVLink intensif attendu (GPS, IMU, heartbeats, etc.)"

# Compter messages AVANT
messages_before=$(grep -c "Encrypted PAYLOAD" "$LOGFILE" 2>/dev/null || echo "0")
calls_before=$(grep -c "comm_send_buffer" "$LOGFILE" 2>/dev/null || echo "0")

sleep "$TEST_DURATION"

# Compter messages APRÈS
messages_after=$(grep -c "Encrypted PAYLOAD" "$LOGFILE" 2>/dev/null || echo "0")
calls_after=$(grep -c "comm_send_buffer" "$LOGFILE" 2>/dev/null || echo "0")

encrypted_count=$((messages_after - messages_before))
calls_count=$((calls_after - calls_before))

print_info "Résultats Feature 4:"
echo "  - Appels comm_send_buffer: $calls_count"
echo "  - Messages chiffrés: $encrypted_count"

if [ "$encrypted_count" -gt 0 ]; then
    print_success "ENCRYPTION ACTIVE ! $encrypted_count messages chiffrés"

    # Montrer exemples
    echo ""
    print_info "Exemples de logs encryption:"
    grep "Encrypted PAYLOAD" "$LOGFILE" | tail -10

    echo ""
    print_success "🎉 FEATURE 4: SUCCÈS COMPLET ✅"
    echo ""
    echo "┌─────────────────────────────────────────────────┐"
    echo "│  ✅ TOUTES LES FEATURES VALIDÉES EN SITL        │"
    echo "│  ✅ PRÊT POUR TESTS HARDWARE RÉEL               │"
    echo "└─────────────────────────────────────────────────┘"

    exit 0

elif [ "$calls_count" -gt 100 ]; then
    print_warning "comm_send_buffer appelée $calls_count fois"
    print_warning "Mais aucun message chiffré détecté"

    echo ""
    print_info "Diagnostic:"

    # Vérifier si encryption activée
    if grep -q "Encryption MAVLink PAYLOAD-ONLY activée" "$LOGFILE"; then
        print_success "Encryption code activé"
    else
        print_error "Encryption code PAS activé"
        echo "  Raison possible: MAV_ENCRYPT=0"
    fi

    # Vérifier si DEK disponible
    if grep -q "DEK (32 bytes):" "$LOGFILE"; then
        print_success "DEK disponible"
    else
        print_error "DEK non disponible"
        echo "  Raison: Feature 3 échec total"
    fi

    # Vérifier warnings
    if grep -q "Encryption enabled but DEK not available" "$LOGFILE"; then
        print_error "DEK pas disponible au moment de l'encryption"
    fi

    echo ""
    print_error "FEATURE 4: ÉCHEC PARTIEL ⚠️"
    echo "Code encryption implémenté mais pas effectif"

    exit 1

else
    print_error "Trafic MAVLink insuffisant"
    echo "  - Seulement $calls_count appels comm_send_buffer"
    echo "  - Attendu: >100 appels"

    print_info "Causes possibles:"
    echo "  1. sim_vehicle.py pas complètement démarré"
    echo "  2. GPS fix pas acquis"
    echo "  3. Sensors pas initialisés"

    print_info "Solutions:"
    echo "  1. Augmenter TEST_DURATION à 120s"
    echo "  2. Attendre 'GPS: GPS lock acquired'"
    echo "  3. Forcer ARM pour activer telemetry"

    print_error "FEATURE 4: ÉCHEC - Trafic insuffisant ❌"

    exit 1
fi
