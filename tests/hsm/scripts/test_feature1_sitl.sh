#!/bin/bash

################################################################################
# TEST FEATURE 1: Initialisation HSM LeMonolith
#
# Environnement: SITL avec sim_vehicle.py + GCS (MAVProxy)
#
# Critères de succès Feature 1:
#   - SE désactivé (off)
#   - SE activé (on)
#   - Application CC sélectionnée (SELECT AID 010203040601)
#   - PIN User vérifié (VERIFY PIN 00000000)
#   - Message "✓ Feature 1 complétée avec succès"
#
# Usage: ./test_feature1_sitl.sh
################################################################################

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
ARDUPILOT_ROOT="/home/samwitwity/Code_Sources/ardupilot_claude"
HSM_DEVICE="/dev/ttyUSB0"
HSM_BAUD="115200"
BOOT_WAIT=20  # Temps pour boot complet et Feature 1

# Logs
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGDIR="$ARDUPILOT_ROOT/tests/hsm/logs"
LOGFILE="$LOGDIR/test_feature1_${TIMESTAMP}.log"
mkdir -p "$LOGDIR"

print_header() {
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════${NC}"
}

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
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
    print_info "Arrêt des processus..."
    pkill -9 -f "arducopter" 2>/dev/null || true
    pkill -9 -f "mavproxy" 2>/dev/null || true
    pkill -9 -f "sim_vehicle" 2>/dev/null || true
    sleep 2
}

print_header "TEST FEATURE 1: INITIALISATION HSM"

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  Feature 1: Initialisation fiable et robuste du HSM    │"
echo "│                                                         │"
echo "│  Séquence attendue:                                     │"
echo "│    1. Désactivation SE (off)                            │"
echo "│    2. Activation SE (on)                                │"
echo "│    3. SELECT Application CC (AID: 010203040601)         │"
echo "│    4. VERIFY PIN User (00000000)                        │"
echo "└─────────────────────────────────────────────────────────┘"
echo ""
echo "Configuration:"
echo "  - HSM Device: $HSM_DEVICE"
echo "  - Baudrate: $HSM_BAUD"
echo "  - Boot wait: ${BOOT_WAIT}s"
echo "  - Log: $LOGFILE"
echo ""

trap cleanup EXIT

# ═══════════════════════════════════════════════════════════════
# ÉTAPE 1: Vérification préalables
# ═══════════════════════════════════════════════════════════════
print_header "ÉTAPE 1: Vérifications Préalables"

print_step "Vérification HSM..."
if [ ! -e "$HSM_DEVICE" ]; then
    print_error "HSM non détecté sur $HSM_DEVICE"
    echo ""
    echo "Actions requises:"
    echo "  1. Connecter le HSM LeMonolith"
    echo "  2. Vérifier: ls -la /dev/ttyUSB*"
    echo "  3. Permissions: sudo usermod -a -G dialout \$USER"
    exit 1
fi
print_success "HSM détecté sur $HSM_DEVICE"

print_step "Vérification binaire ArduCopter..."
if [ ! -f "$ARDUPILOT_ROOT/build/sitl/bin/arducopter" ]; then
    print_error "Binaire non trouvé"
    echo "Exécutez: ./waf copter"
    exit 1
fi
print_success "Binaire ArduCopter OK"

# Nettoyage préalable
cleanup

# ═══════════════════════════════════════════════════════════════
# ÉTAPE 2: Lancement SITL ArduCopter
# ═══════════════════════════════════════════════════════════════
print_header "ÉTAPE 2: Lancement SITL"

cd "$ARDUPILOT_ROOT"

print_step "Démarrage ArduCopter SITL avec HSM sur SERIAL1..."

# Lancer ArduCopter avec stdbuf pour désactiver le buffering stdout
stdbuf -oL -eL build/sitl/bin/arducopter \
    --model quad \
    --serial1=uart:${HSM_DEVICE}:${HSM_BAUD} \
    --defaults Tools/autotest/default_params/copter.parm \
    --speedup 1 \
    -I0 > "$LOGFILE" 2>&1 &

SIM_PID=$!
echo "  PID: $SIM_PID"

# Attendre que le serveur TCP soit prêt
print_step "Attente serveur TCP (3s)..."
sleep 3

# Vérifier que ArduCopter tourne
if ! kill -0 $SIM_PID 2>/dev/null; then
    print_error "ArduCopter s'est arrêté"
    cat "$LOGFILE"
    exit 1
fi

# Se connecter pour déclencher l'init HSM (setup() continue après connexion)
print_step "Connexion TCP pour déclencher init HSM..."
nc localhost 5760 > /dev/null 2>&1 &
NC_PID=$!

print_step "Attente initialisation HSM (${BOOT_WAIT}s max)..."

# Attendre et vérifier
for i in $(seq 1 $BOOT_WAIT); do
    echo -ne "\r  Progression: $i/${BOOT_WAIT}s "

    # Sortir tôt si Feature 1 est complétée
    if grep -q "Feature 1 complétée" "$LOGFILE" 2>/dev/null; then
        echo ""
        print_success "Feature 1 détectée !"
        break
    fi

    sleep 1
done
echo ""

# Arrêter les processus
kill $NC_PID 2>/dev/null || true
kill $SIM_PID 2>/dev/null || true
sleep 1

print_success "Phase boot terminée"

# ═══════════════════════════════════════════════════════════════
# ÉTAPE 3: Validation Feature 1
# ═══════════════════════════════════════════════════════════════
print_header "ÉTAPE 3: Validation Feature 1"

echo ""
print_step "Analyse des logs HSM..."
echo ""

# Extraire tous les messages HSM
echo "Messages HSM détectés:"
echo "─────────────────────────────────────────────────────────"
grep "HSM:" "$LOGFILE" 2>/dev/null | head -30 || echo "(aucun message HSM)"
echo "─────────────────────────────────────────────────────────"
echo ""

# Validation des étapes Feature 1
FEATURE1_OK=true

print_step "Vérification étape 1: Désactivation SE..."
if grep -q "HSM: SE désactivé" "$LOGFILE"; then
    print_success "SE désactivé"
else
    print_error "SE désactivation non détectée"
    FEATURE1_OK=false
fi

print_step "Vérification étape 2: Activation SE..."
if grep -q "HSM: SE activé" "$LOGFILE"; then
    print_success "SE activé"
else
    print_error "SE activation non détectée"
    FEATURE1_OK=false
fi

print_step "Vérification étape 3: SELECT Application CC..."
if grep -q "HSM: Application CC sélectionnée" "$LOGFILE"; then
    print_success "Application CC sélectionnée (AID: 010203040601)"
else
    print_error "SELECT Application CC échoué"
    FEATURE1_OK=false
fi

print_step "Vérification étape 4: VERIFY PIN..."
if grep -q "HSM: PIN User vérifié avec succès" "$LOGFILE"; then
    print_success "PIN User vérifié (00000000)"
else
    print_error "VERIFY PIN échoué"
    FEATURE1_OK=false
fi

print_step "Vérification message final Feature 1..."
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    print_success "Feature 1 complétée avec succès"
else
    print_error "Message de succès Feature 1 non trouvé"
    FEATURE1_OK=false
fi

# ═══════════════════════════════════════════════════════════════
# RÉSULTAT FINAL
# ═══════════════════════════════════════════════════════════════
print_header "RÉSULTAT FINAL"

if $FEATURE1_OK; then
    echo ""
    echo -e "${GREEN}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${GREEN}│                                                         │${NC}"
    echo -e "${GREEN}│   🎉 FEATURE 1: SUCCÈS COMPLET ✅                       │${NC}"
    echo -e "${GREEN}│                                                         │${NC}"
    echo -e "${GREEN}│   Le HSM LeMonolith est correctement initialisé:        │${NC}"
    echo -e "${GREEN}│   • Communication UART établie                          │${NC}"
    echo -e "${GREEN}│   • Secure Element activé                               │${NC}"
    echo -e "${GREEN}│   • Application CC sélectionnée                         │${NC}"
    echo -e "${GREEN}│   • PIN User vérifié                                    │${NC}"
    echo -e "${GREEN}│                                                         │${NC}"
    echo -e "${GREEN}│   ➡️  Prêt pour test Feature 2                          │${NC}"
    echo -e "${GREEN}│                                                         │${NC}"
    echo -e "${GREEN}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    # Arrêter SITL proprement
    cleanup

    echo "Log complet: $LOGFILE"
    exit 0
else
    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│                                                         │${NC}"
    echo -e "${RED}│   ❌ FEATURE 1: ÉCHEC                                   │${NC}"
    echo -e "${RED}│                                                         │${NC}"
    echo -e "${RED}│   L'initialisation HSM a échoué.                        │${NC}"
    echo -e "${RED}│                                                         │${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    print_info "Diagnostics:"
    echo ""

    # Vérifier erreurs spécifiques
    if grep -q "Erreur - UART" "$LOGFILE"; then
        print_error "Problème UART détecté"
        grep "Erreur - UART" "$LOGFILE"
    fi

    if grep -q "Timeout" "$LOGFILE"; then
        print_error "Timeout détecté"
        grep "Timeout" "$LOGFILE"
    fi

    echo ""
    print_info "Actions recommandées:"
    echo "  1. Vérifier connexion HSM: ls -la /dev/ttyUSB0"
    echo "  2. Reset HSM: débrancher 10s puis rebrancher"
    echo "  3. Vérifier permissions: groups \$USER | grep dialout"
    echo "  4. Consulter log complet: $LOGFILE"
    echo ""

    exit 1
fi
