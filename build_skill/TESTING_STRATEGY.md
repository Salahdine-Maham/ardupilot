# Stratégie de Test Features 1-4 avec SITL

**Date:** 2026-01-23
**Objectif:** Valider toutes les features en SITL AVANT de passer au hardware réel

---

## 🎯 PRINCIPE FONDAMENTAL

**Condition de passage d'une feature à l'autre:**
> Chaque feature doit PASSER en SITL avant de tester la suivante.
> Si Feature N échoue → NE PAS tester Feature N+1.

**Condition de passage au hardware:**
> Toutes les features (1-4) doivent PASSER en SITL avant tests hardware réel.

---

## 📊 WORKFLOW COMPLET

```
┌─────────────────────────────────────────────────────────┐
│                 START: Build ArduCopter                  │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│        TEST FEATURE 1: Initialisation HSM               │
│        (OFF → ON → SELECT → VERIFY PIN)                 │
└───────────────────────┬─────────────────────────────────┘
                        │
                    ┌───┴───┐
                    │  OK?  │
                    └───┬───┘
                  NON ──┘  OUI
                   │         │
                   ▼         ▼
            ┌──────────┐  ┌─────────────────────────────────┐
            │  STOP    │  │  TEST FEATURE 2: Keypair P-256  │
            │  Débug   │  │  (Generate + Storage EEPROM)    │
            │  F1      │  └────────────┬────────────────────┘
            └──────────┘               │
                                   ┌───┴───┐
                                   │  OK?  │
                                   └───┬───┘
                                 NON ──┘  OUI
                                  │         │
                                  ▼         ▼
                           ┌──────────┐  ┌─────────────────────────────┐
                           │  STOP    │  │  TEST FEATURE 3: DEK        │
                           │  Débug   │  │  (ECDH + HKDF + Wrap)       │
                           │  F2      │  └────────────┬────────────────┘
                           └──────────┘               │
                                                  ┌───┴───┐
                                                  │  OK?  │
                                                  └───┬───┘
                                                NON ──┘  OUI
                                                 │         │
                                                 ▼         ▼
                                          ┌──────────┐  ┌─────────────────────┐
                                          │  STOP    │  │  TEST FEATURE 4:    │
                                          │  Débug   │  │  Encryption MAVLink │
                                          │  F3      │  └──────────┬──────────┘
                                          └──────────┘             │
                                                               ┌───┴───┐
                                                               │  OK?  │
                                                               └───┬───┘
                                                             NON ──┘  OUI
                                                              │         │
                           ┌──────────────────────────────────┴─┐       │
                           │  Feature 4 Partial:                │       │
                           │  - Essayer sim_vehicle.py          │       │
                           │  - Augmenter trafic MAVLink        │       │
                           │  - Vérifier MAV_ENCRYPT=1          │       │
                           └──────────────┬─────────────────────┘       │
                                          │                             │
                                      ┌───┴───┐                         │
                                      │  OK?  │                         │
                                      └───┬───┘                         │
                                    NON ──┘  OUI                        │
                                     │         │                        │
                                     ▼         └────────────────┬───────┘
                              ┌──────────┐                      │
                              │  STOP    │                      ▼
                              │  Débug   │        ┌──────────────────────────┐
                              │  F4      │        │  ✅ SUCCESS COMPLET       │
                              └──────────┘        │  Prêt pour Hardware Réel │
                                                  └──────────────────────────┘
```

---

## 🛠️ SCRIPTS DE TEST

### 1. test_all_features_sitl.sh (SCRIPT PRINCIPAL)

**Usage:**
```bash
./test_all_features_sitl.sh
```

**Ce qu'il fait:**
1. Build ArduCopter
2. Lance SITL avec HSM sur /dev/ttyUSB0
3. Attend boot complet (15s)
4. Test Feature 1 → Si échec: STOP
5. Test Feature 2 → Si échec: STOP
6. Test Feature 3 → Si échec: STOP
7. Test Feature 4 → Continue même si échec (peut nécessiter SITL complet)
8. Génère rapport final

**Codes de sortie:**
- `0` = Toutes features (1-4) OK → **Prêt pour hardware réel** ✅
- `10` = Features 1-3 OK, Feature 4 KO → **Débug Feature 4 avec sim_vehicle** ⚠️
- `1` = Échec Features 1-3 → **NE PAS passer au hardware** ❌

**Logs:**
- Fichier: `test_logs/test_features_sitl_YYYYMMDD_HHMMSS.log`
- Contient tous les logs ArduCopter + HSM
- Recherchable avec `grep "HSM:"` ou `grep "Feature"`

**Exemple output:**
```
================================================
  TEST COMPLET FEATURES 1-4 AVEC SITL
================================================

Configuration:
  - ArduPilot: /home/samwitwity/Code_Sources/ardupilot_claude
  - HSM Device: /dev/ttyUSB0
  - Log File: test_logs/test_features_sitl_20260123_153045.log

✅ HSM détecté
✅ Compilation réussie

================================================
  LANCEMENT SITL + HSM
================================================
ℹ️  Démarrage ArduCopter SITL...
ArduCopter PID: 12345
✅ SITL démarré avec succès

================================================
  TEST FEATURE 1: Initialisation HSM
================================================
✅ Trouvé: HSM: Démarrage initialisation LeMonolith
✅ Trouvé: HSM: SE activé
✅ Trouvé: HSM: Application CC sélectionnée
✅ Trouvé: HSM: PIN User vérifié avec succès
✅ Trouvé: ✓ Feature 1 complétée avec succès
✅ FEATURE 1: SUCCÈS ✅

... (idem pour Features 2, 3, 4)

================================================
  RAPPORT FINAL
================================================

┌─────────────────────────────────────────────────┐
│         RÉSULTATS TESTS FEATURES 1-4           │
├─────────────────────────────────────────────────┤
│ Features passées:  4/4                         │
│ Features échouées: 0/4                         │
│ Pourcentage:       100%                        │
├─────────────────────────────────────────────────┤
│ 🎉 SUCCÈS COMPLET - Prêt pour hardware réel   │
└─────────────────────────────────────────────────┘

RECOMMANDATIONS:
  ✅ Toutes features validées en SITL
  ✅ Prêt pour tests hardware réel
  ➡️  Prochaine étape: Test sur drone physique
```

---

### 2. test_feature4_with_sim_vehicle.sh (SITL COMPLET)

**Usage:**
```bash
./test_feature4_with_sim_vehicle.sh
```

**Quand l'utiliser:**
- Si `test_all_features_sitl.sh` retourne code 10
- Si Feature 4 échoue avec message "Aucun trafic MAVLink"
- Pour tests avec GPS/IMU/sensors simulés

**Ce qu'il fait:**
1. Build ArduCopter
2. Lance `sim_vehicle.py` avec HSM
   - GPS simulé (San Francisco)
   - IMU avec données inertielles
   - Barometer
   - Compass
   - MAVProxy avec console
3. Attend Features 1-3 (15s)
4. Observe Feature 4 pendant 60s
5. Compte messages chiffrés
6. Rapport détaillé

**Avantages sim_vehicle.py:**
- Trafic MAVLink TRÈS intensif (GPS, IMU, heartbeats, etc.)
- Simule environnement réel complet
- Telemetry active automatiquement
- Meilleure validation Feature 4

**Exemple output:**
```
================================================
  TEST FEATURE 4 AVEC SIM_VEHICLE.PY
================================================

✅ Build OK
ℹ️  Démarrage sim_vehicle.py avec HSM...
✅ SITL complet démarré
✅ Features 1-2 OK, Feature 3 OK (RAM-only possible)

ℹ️  Observation Feature 4 pendant 60 secondes...

Résultats Feature 4:
  - Appels comm_send_buffer: 2847
  - Messages chiffrés: 856

✅ ENCRYPTION ACTIVE ! 856 messages chiffrés

ℹ️  Exemples de logs encryption:
HSM: Encrypted PAYLOAD #1 (30 bytes) on chan 0
HSM: Encrypted PAYLOAD #51 (28 bytes) on chan 0
HSM: Encrypted PAYLOAD #101 (9 bytes) on chan 0
...

✅ 🎉 FEATURE 4: SUCCÈS COMPLET ✅

┌─────────────────────────────────────────────────┐
│  ✅ TOUTES LES FEATURES VALIDÉES EN SITL        │
│  ✅ PRÊT POUR TESTS HARDWARE RÉEL               │
└─────────────────────────────────────────────────┘
```

---

## 📋 CHECKLIST PRÉ-TEST

Avant de lancer les tests:

- [ ] HSM LeMonolith v0.6 connecté sur `/dev/ttyUSB0`
- [ ] HSM pas utilisé par autre process (`lsof /dev/ttyUSB0` vide)
- [ ] HSM reposé depuis derniers tests (idéalement 30-60s)
- [ ] ArduPilot dans bon répertoire (`cd ~/Code_Sources/ardupilot_claude`)
- [ ] Processus précédents tués (`pkill -9 arducopter mavproxy`)
- [ ] Espace disque suffisant pour logs (`df -h`)

---

## 🔍 INTERPRÉTATION RÉSULTATS

### Scénario 1: Toutes Features OK (Code 0)

**Output:**
```
Features passées:  4/4
Features échouées: 0/4
Pourcentage:       100%
🎉 SUCCÈS COMPLET - Prêt pour hardware réel
```

**Action:**
✅ **PASSER AU HARDWARE RÉEL**

**Prochaines étapes:**
1. Connecter HSM au drone physique
2. Configurer SERIAL1 pour HSM
3. Flasher binaire ArduCopter sur drone
4. Tester Features 1-4 sur hardware
5. Valider encryption end-to-end avec GCS

---

### Scénario 2: Features 1-3 OK, Feature 4 KO (Code 10)

**Output:**
```
Features passées:  3/4
Features échouées: 1/4
Pourcentage:       75%
⚠️  SUCCÈS PARTIEL - Feature 4 à débugger
```

**Action:**
⚠️ **DÉBUGGER FEATURE 4 AVANT HARDWARE**

**Étapes debug:**

1. **Lancer test avec sim_vehicle.py:**
   ```bash
   ./test_feature4_with_sim_vehicle.sh
   ```

2. **Si toujours échec, vérifier logs:**
   ```bash
   grep "MAV_ENCRYPT" test_logs/*.log
   grep "DEK (32 bytes):" test_logs/*.log
   grep "comm_send_buffer" test_logs/*.log
   ```

3. **Causes possibles:**
   - MAV_ENCRYPT=0 → `param set MAV_ENCRYPT 1`
   - DEK non disponible → Feature 3 échec partiel
   - Trafic MAVLink insuffisant → Utiliser sim_vehicle.py
   - Logs noyés → Augmenter TEST_DURATION

4. **Si sim_vehicle.py échoue aussi:**
   - Ajouter logs temporaires dans `comm_send_buffer()`:
     ```cpp
     printf("DEBUG: comm_send_buffer chan=%d len=%d\n", chan, len);
     ```
   - Recompiler et relancer
   - Vérifier appels de fonction

**NE PAS passer au hardware tant que Feature 4 échoue**

---

### Scénario 3: Features 1-3 Échouées (Code 1)

**Output:**
```
Features passées:  0-2/4
Features échouées: 2-4/4
Pourcentage:       0-50%
❌ ÉCHEC - Problème initialisation HSM
```

**Action:**
❌ **NE PAS PASSER AU HARDWARE - DÉBUGGER D'ABORD**

**Étapes debug selon feature échouée:**

**Si Feature 1 échoue:**
```bash
# Vérifier HSM
ls -la /dev/ttyUSB0
lsof /dev/ttyUSB0

# Test direct HSM
echo -e "on\r" > /dev/ttyUSB0
timeout 5s cat /dev/ttyUSB0

# Logs détaillés
grep "HSM:" test_logs/*.log | tail -50

# Causes:
# - HSM non connecté
# - HSM utilisé par autre process
# - Délais insuffisants (augmenter SITL_WAIT_BOOT)
# - HSM instable (reset 60s)
```

**Si Feature 2 échoue (mais Feature 1 OK):**
```bash
# Vérifier génération clés
grep "keypair P-256" test_logs/*.log

# Vérifier micro-ecc
ls -la libraries/AP_HSM/uECC.h

# Causes:
# - micro-ecc non intégrée
# - Erreur génération clés
# - WRITE EEPROM échoue
```

**Si Feature 3 échoue (mais Features 1-2 OK):**
```bash
# Vérifier DEK
grep "DEK (32 bytes):" test_logs/*.log

# Vérifier mode RAM-only
grep "Mode RAM-only" test_logs/*.log

# Causes:
# - Clé publique remote invalide (hardcodée dans code)
# - ECDH échec
# - HKDF échec
# - Wrap échec

# Note: Si mode RAM-only actif → Feature 3 OK pour Feature 4
```

---

## 📊 MATRICE DÉCISION

| Features OK | Feature 4 | Décision | Action |
|-------------|-----------|----------|--------|
| 4/4 | ✅ | ✅ **GO HARDWARE** | Tests hardware réel |
| 3/4 | ❌ | ⚠️ **DÉBUG F4** | test_feature4_with_sim_vehicle.sh |
| 2/4 ou moins | N/A | ❌ **STOP** | Débugger Features 1-3 |
| 0/4 | N/A | ❌ **STOP** | Vérifier HSM + timings |

---

## 🧪 TESTS AVANCÉS (OPTIONNELS)

### Test Stress Feature 4

**Objectif:** Vérifier encryption sous charge élevée

```bash
# Modifier TEST_DURATION à 300s (5 minutes)
sed -i 's/TEST_DURATION=60/TEST_DURATION=300/' test_feature4_with_sim_vehicle.sh

# Lancer test long
./test_feature4_with_sim_vehicle.sh

# Vérifier:
# - Aucun crash
# - Encryption continue
# - Performance stable
```

### Test Nonce Uniques

**Objectif:** Vérifier que nonces ne se répètent jamais

```bash
# Extraire nonces des logs
grep "Encrypted PAYLOAD" test_logs/*.log | \
    sed 's/.*#\([0-9]*\).*/\1/' | \
    sort -n | uniq -d

# Résultat attendu: aucune ligne (pas de doublons)
```

### Test Overhead Performance

**Objectif:** Mesurer impact CPU encryption

```bash
# Lancer avec encryption
./test_feature4_with_sim_vehicle.sh

# CPU usage pendant test
top -b -n 10 -p $(pgrep arducopter) | \
    grep arducopter | \
    awk '{sum+=$9; count++} END {print "CPU moyen: " sum/count "%"}'

# Attendu: < 2% overhead encryption
```

---

## 📝 LOGS ET DEBUGGING

### Localisation Logs

```
test_logs/
├── test_features_sitl_20260123_153045.log    # Test principal
├── test_feature4_simvehicle_20260123_154230.log  # Test sim_vehicle
└── ...
```

### Commandes Utiles

**Rechercher erreurs:**
```bash
grep -E "(Erreur|Timeout|échoué|FAIL)" test_logs/*.log
```

**Compter succès features:**
```bash
grep -c "✓ Feature.*complétée avec succès" test_logs/test_*.log
```

**Analyser encryption:**
```bash
# Compter messages chiffrés
grep -c "Encrypted PAYLOAD" test_logs/*.log

# Voir premiers/derniers
grep "Encrypted PAYLOAD" test_logs/*.log | head -5
grep "Encrypted PAYLOAD" test_logs/*.log | tail -5
```

**Extraire statistiques:**
```bash
# Total appels comm_send_buffer
grep -c "comm_send_buffer" test_logs/*.log

# Messages chiffrés par seconde
encrypted=$(grep -c "Encrypted PAYLOAD" test_logs/*.log)
duration=60  # TEST_DURATION
echo "Messages/s: $(($encrypted / $duration))"
```

---

## 🎓 TROUBLESHOOTING COMMUN

### Problème: HSM Timeout

**Symptômes:**
```
❌ Erreur - Timeout SELECT applet CC
❌ FEATURE 1: ÉCHEC
```

**Solutions:**
1. Reset HSM (débrancher 60s)
2. Vérifier `/dev/ttyUSB0` existe et accessible
3. Tuer processus utilisant UART: `pkill -9 arducopter`
4. Augmenter `SITL_WAIT_BOOT` à 20s

---

### Problème: Aucun Log Encryption

**Symptômes:**
```
Appels comm_send_buffer: 0
Messages chiffrés: 0
❌ FEATURE 4: ÉCHEC
```

**Solutions:**
1. Utiliser `sim_vehicle.py` au lieu de SITL basique
2. Vérifier MAV_ENCRYPT=1 dans logs
3. Vérifier Feature 3 OK (DEK disponible)
4. Augmenter TEST_DURATION à 120s

---

### Problème: Compilation Échoue

**Symptômes:**
```
❌ Échec build - Abandon
```

**Solutions:**
1. Clean: `./waf clean && ./waf distclean`
2. Reconfigurer: `./waf configure --board sitl`
3. Vérifier dépendances: micro-ecc, AP_Crypto
4. Regarder erreurs compilation dans logs

---

## 📞 SUPPORT

**Documentation:**
- [ardupilot_skills.md](ardupilot_skills.md) - Connaissances ArduPilot
- [hsm_skills.md](hsm_skills.md) - Connaissances HSM
- [FEATURE4_ENCRYPTION_STATUS.md](FEATURE4_ENCRYPTION_STATUS.md) - Feature 4 détails

**Scripts:**
- `test_all_features_sitl.sh` - Test principal
- `test_feature4_with_sim_vehicle.sh` - Test SITL complet

**Aide:**
- Consulter logs dans `test_logs/`
- Chercher erreurs avec `grep "Erreur"`
- Vérifier HSM avec `lsof /dev/ttyUSB0`

---

**Version:** 1.0
**Date:** 2026-01-23
**Auteur:** Équipe ArduPilot+HSM
**Status:** Validé et prêt pour utilisation
