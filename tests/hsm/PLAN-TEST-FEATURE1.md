# Plan de Test - Feature 1: Key Orchestrator

**Date**: 2026-01-24
**Feature**: Key Orchestrator (Hiérarchie MK → WK → DEK)
**Status**: En cours

---

## Objectif

Valider que KeyOrchestrator fonctionne correctement dans ArduCopter:
1. Initialisation des clés au boot
2. Communication avec HSM LeMonolith
3. Stockage/restauration des clés wrappées
4. Logs visibles dans MAVProxy

---

## Prérequis

### 1. Code à intégrer

- [ ] `libraries/AP_HSM/KeyOrchestrator.h` - déjà créé
- [ ] `libraries/AP_HSM/KeyOrchestrator.cpp` - déjà créé
- [ ] `libraries/AP_HSM/AP_HSM.cpp` - doit appeler KeyOrchestrator
- [ ] `libraries/AP_HSM/wscript` - doit inclure KeyOrchestrator

### 2. Intégration dans ArduCopter

- [ ] `AP_Vehicle::init_ardupilot()` doit initialiser HSM + KeyOrchestrator
- [ ] Paramètre `HSM_ENABLE` pour activer/désactiver
- [ ] Paramètre `HSM_SERIAL` pour choisir le port série

### 3. Hardware

- [ ] HSM LeMonolith connecté sur `/dev/ttyUSB0`
- [ ] HSM fonctionnel (test avec `test_key_orchestrator_hsm.py` OK)

---

## Phase 1: Test SITL + HSM Réel

### Étape 1.1: Compilation

```bash
cd /home/samwitwity/Code_Sources/ardupilot_claude

# Nettoyer build précédent
./waf clean

# Configurer pour SITL
./waf configure --board sitl

# Compiler ArduCopter
./waf copter

# Vérifier que le binaire existe
ls -la build/sitl/bin/arducopter
```

**Critère de succès**: Compilation sans erreur

### Étape 1.2: Lancer SITL avec HSM

```bash
# Terminal 1: Lancer ArduCopter SITL
cd /home/samwitwity/Code_Sources/ardupilot_claude
build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 \
    --defaults Tools/autotest/default_params/copter.parm \
    2>&1 | tee /tmp/sitl_hsm_feature1.log &

# Attendre démarrage
sleep 5

# Terminal 2: Lancer MAVProxy
mavproxy.py --master=tcp:127.0.0.1:5760 --console
```

**Alternative avec sim_vehicle.py:**
```bash
cd Tools/autotest
./sim_vehicle.py -v ArduCopter --console --map \
    -A "--serial1=uart:/dev/ttyUSB0:115200"
```

### Étape 1.3: Vérifier les logs

**Dans MAVProxy, chercher:**
```
HSM: Initializing...
HSM: SE activated
HSM: Application CC selected
HSM: PIN verified
HSM: Feature 1 - KeyOrchestrator starting...
HSM: Master Key generated (32 bytes)
HSM: Wrapper Key derived via HKDF
HSM: DEK generated (32 bytes)
HSM: Keys wrapped and stored to HSM
HSM: Feature 1 completed successfully
```

**Commande MAVProxy pour voir les messages:**
```
# Dans console MAVProxy
module load log
log list
```

**Ou dans le fichier log:**
```bash
grep -i "HSM\|Feature 1\|KeyOrchestrator" /tmp/sitl_hsm_feature1.log
```

### Étape 1.4: Test de persistance (reboot simulé)

```bash
# Arrêter SITL
pkill -f arducopter

# Relancer
build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &
sleep 5
mavproxy.py --master=tcp:127.0.0.1:5760 --console
```

**Logs attendus au 2ème boot:**
```
HSM: Feature 1 - KeyOrchestrator starting...
HSM: Existing keys found in HSM
HSM: Master Key loaded (32 bytes)
HSM: Wrapper Key unwrapped successfully
HSM: DEK unwrapped successfully
HSM: Feature 1 completed (restored from HSM)
```

---

## Critères de Succès - Phase 1

| Test | Critère | Status |
|------|---------|--------|
| Compilation | `./waf copter` sans erreur | ❌ |
| Boot HSM | "HSM: SE activated" dans logs | ❌ |
| Init Keys | "Master Key generated" dans logs | ❌ |
| Store HSM | "Keys wrapped and stored" dans logs | ❌ |
| Restore | "restored from HSM" au 2ème boot | ❌ |

---

## Phase 2: Test Hardware Pixhawk 5X

### Étape 2.1: Compilation pour Pixhawk 5X

```bash
cd /home/samwitwity/Code_Sources/ardupilot_claude

# Configurer pour Pixhawk 5X
./waf configure --board Pixhawk5X

# Compiler
./waf copter

# Le firmware est dans:
# build/Pixhawk5X/bin/arducopter.apj
```

### Étape 2.2: Flash du firmware

```bash
# Avec uploader.py (Pixhawk en mode bootloader)
python3 Tools/scripts/uploader.py build/Pixhawk5X/bin/arducopter.apj

# Ou avec MAVProxy
# mavproxy.py --master=/dev/ttyACM0
# MAVFTP> ftp put arducopter.apj @ROMFS/APM/
```

### Étape 2.3: Configuration paramètres

Dans MAVProxy:
```
# Activer HSM
param set HSM_ENABLE 1

# Configurer port série (SERIAL2 = TELEM2)
param set SERIAL2_PROTOCOL 28    # Protocol HSM (à définir)
param set SERIAL2_BAUD 115200

# Sauvegarder
param save
```

### Étape 2.4: Test avec Pixhawk

```bash
# Connecter:
# - Pixhawk 5X sur /dev/ttyACM0 (USB)
# - HSM sur TELEM2 du Pixhawk (ou /dev/ttyUSB0 si via ordinateur)

mavproxy.py --master=/dev/ttyACM0 --baudrate=115200 --console
```

**Vérifier les mêmes logs que Phase 1**

---

## Critères de Succès - Phase 2

| Test | Critère | Status |
|------|---------|--------|
| Compilation | `./waf copter` pour Pixhawk5X | ❌ |
| Flash | Firmware installé sur Pixhawk | ❌ |
| Boot HSM | "HSM: SE activated" dans logs | ❌ |
| Init Keys | "Master Key generated" dans logs | ❌ |
| Restore | "restored from HSM" au reboot | ❌ |

---

## Problèmes Potentiels et Solutions

### Problème: "HSM: Timeout SELECT"
**Solution**: Vérifier délais dans AP_HSM.cpp (3.5s après ON)

### Problème: "HSM: WRITE failed"
**Solution**: Utiliser INS=D0 (pas D6) pour WRITE BINARY

### Problème: Compilation échoue
**Solution**: Vérifier wscript inclut tous les fichiers

### Problème: SERIAL1 pas disponible en SITL
**Solution**: Utiliser `--serial1=uart:/dev/ttyUSB0:115200`

---

## Scripts de Test Automatisé

Créer: `tests/hsm/scripts/test_feature1_sitl.sh`

```bash
#!/bin/bash
# Test automatisé Feature 1 avec SITL

set -e

echo "=== Test Feature 1 - SITL + HSM ==="

# 1. Vérifier HSM connecté
if [ ! -e /dev/ttyUSB0 ]; then
    echo "ERREUR: HSM non connecté sur /dev/ttyUSB0"
    exit 1
fi

# 2. Compiler
echo "[1/4] Compilation..."
cd /home/samwitwity/Code_Sources/ardupilot_claude
./waf configure --board sitl
./waf copter

# 3. Lancer SITL
echo "[2/4] Lancement SITL..."
build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 \
    > /tmp/sitl_feature1.log 2>&1 &
SITL_PID=$!
sleep 10

# 4. Vérifier logs
echo "[3/4] Vérification logs..."
if grep -q "Feature 1 completed" /tmp/sitl_feature1.log; then
    echo "✅ Feature 1 PASS"
    RESULT=0
else
    echo "❌ Feature 1 FAIL"
    echo "Logs:"
    grep -i "HSM\|error\|fail" /tmp/sitl_feature1.log | tail -20
    RESULT=1
fi

# 5. Cleanup
echo "[4/4] Cleanup..."
kill $SITL_PID 2>/dev/null || true

exit $RESULT
```

---

## Prochaines Actions

1. [ ] Vérifier que KeyOrchestrator est intégré dans AP_HSM
2. [ ] Ajouter les logs GCS_SEND_TEXT dans KeyOrchestrator
3. [ ] Compiler et tester Phase 1
4. [ ] Si Phase 1 OK, passer à Phase 2

---

**Dernière mise à jour**: 2026-01-24
