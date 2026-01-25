# 📊 Test Scan Timing HSM - Explication Complète

## 🎯 OBJECTIF

Trouver les **délais optimaux** pour la communication avec le HSM LeMonolith en testant **progressivement** différentes configurations de timing.

---

## 🤔 POURQUOI CE TEST?

### Problème Actuel
```
HSM: SE désactivé ✅
HSM: SE activé ✅
HSM: Erreur - Timeout SELECT applet CC ❌  ← PROBLÈME ICI
```

**Hypothèse**: Le HSM a besoin de **PLUS DE TEMPS** pour s'initialiser complètement après la commande "ON".

### Les 3 Délais Critiques

Dans `AP_HSM.cpp`, il y a **3 délais** qui contrôlent le timing:

```cpp
// 1. Délai après ON
uart_hsm->printf("on\r\n");
hal.scheduler->delay(2500);  // ← Délai 1: Après envoi "ON"

// 2. Délai pour lire ATR
while ((AP_HAL::millis() - start) < 3000) {  // ← Délai 2: Lecture ATR
    if (uart_hsm->available() > 0) {
        uart_hsm->read();
    }
}

// 3. Délai avant SELECT
flush_input();
hal.scheduler->delay(500);  // ← Délai 3: Avant SELECT applet

// 4. Envoyer SELECT
send_apdu("A 00A4040006010203040601", response);
```

**Question**: Quels sont les délais optimaux pour que le HSM réponde correctement?

---

## 📝 PLAN DE TEST PROGRESSIF

### Test 1: Baseline (Délais Actuels)
```
Délai après ON:      2500ms (2.5s)
Délai ATR:           3000ms (3s)
Délai avant SELECT:   500ms (0.5s)
Total attente:       6000ms (6s)

Résultat attendu: ÉCHEC (on sait qu'il échoue)
```

### Test 2: Augmenter ON à 3.5s
```
Délai après ON:      3500ms (3.5s)  ← +1s
Délai ATR:           3000ms (3s)
Délai avant SELECT:   500ms (0.5s)
Total attente:       7000ms (7s)

Hypothèse: Le HSM a besoin de plus de temps après "ON"
```

### Test 3: Augmenter ON à 4s
```
Délai après ON:      4000ms (4s)    ← +1.5s
Délai ATR:           3000ms (3s)
Délai avant SELECT:   500ms (0.5s)
Total attente:       7500ms (7.5s)

Hypothèse: Peut-être 4s est le seuil?
```

### Test 4: Augmenter ATR à 4s aussi
```
Délai après ON:      4000ms (4s)
Délai ATR:           4000ms (4s)    ← +1s
Délai avant SELECT:   500ms (0.5s)
Total attente:       8500ms (8.5s)

Hypothèse: Peut-être que l'ATR prend aussi plus de temps
```

### Test 5: Augmenter délai avant SELECT
```
Délai après ON:      4000ms (4s)
Délai ATR:           4000ms (4s)
Délai avant SELECT:  1000ms (1s)    ← +0.5s
Total attente:       9000ms (9s)

Hypothèse: Peut-être qu'il faut plus de temps entre ATR et SELECT
```

### Test 6: Délais TRÈS longs (test extrême)
```
Délai après ON:      5000ms (5s)    ← Maximum raisonnable
Délai ATR:           5000ms (5s)
Délai avant SELECT:  1500ms (1.5s)
Total attente:      11500ms (11.5s)

Hypothèse: Si ça ne marche pas avec ça, le problème n'est PAS les délais
```

---

## 🔬 COMMENT ÇA FONCTIONNE?

### Étape par Étape

#### 1. Préparation (Backup)
```bash
# Sauvegarder le fichier original
cp libraries/AP_HSM/AP_HSM.cpp libraries/AP_HSM/AP_HSM.cpp.backup_timing
```

#### 2. Modification des Délais
```bash
# Remplacer les délais dans le code source
sed -i "s/delay(2500)/delay(3500)/" libraries/AP_HSM/AP_HSM.cpp
```

#### 3. Recompilation
```bash
# Recompiler ArduCopter avec les nouveaux délais
./waf copter
```

#### 4. Test
```bash
# Lancer ArduCopter pendant 12s
timeout 12s arducopter --serial1 uart:/dev/ttyUSB0:115200 --console
```

#### 5. Analyse
```bash
# Chercher "✓ Feature 1 complétée avec succès" dans le log
if grep -q "✓ Feature 1" logfile; then
    echo "SUCCÈS!"
fi
```

#### 6. Restauration
```bash
# Restaurer le fichier original
cp libraries/AP_HSM/AP_HSM.cpp.backup_timing libraries/AP_HSM/AP_HSM.cpp
```

#### 7. Pause entre Tests
```bash
# Attendre 2 secondes entre chaque test
sleep 2
```

**Pourquoi la pause?** Pour laisser le HSM "respirer" entre les tests.

---

## 📊 INTERPRÉTATION DES RÉSULTATS

### Résultat 1: Test 1 ou 2 réussit
```
✅ Solution: Le HSM a juste besoin d'un peu plus de temps
   → Les délais actuels sont presque bons
   → Augmentation mineure suffit (3-3.5s)
```

### Résultat 2: Test 3-4 réussit
```
✅ Solution: Le HSM est lent à s'initialiser
   → Délais de 4s nécessaires
   → Normal pour certains HSM
```

### Résultat 3: Test 5-6 réussit
```
⚠️  Solution: Le HSM est TRÈS lent
   → Délais de 5s+ nécessaires
   → Peut indiquer un problème matériel mineur
   → Mais le HSM fonctionne
```

### Résultat 4: Aucun test ne réussit
```
❌ Problème plus grave que les délais:
   1. HSM vraiment en état instable
   2. Problème hardware
   3. Conflit logiciel

   Actions:
   → Débrancher HSM 30s (pas 10s)
   → Vérifier lsof /dev/ttyUSB0
   → Vérifier dmesg pour erreurs USB
```

---

## 💡 CE QUE NOUS APPRENONS

### Scénario A: Succès avec Test 2 (3.5s)
```
Conclusion: Le timing de 2.5s était juste un peu court
Application: Mettre 3.5s en production
Impact: +1s au boot, acceptable
```

### Scénario B: Succès avec Test 4 (4s/4s)
```
Conclusion: Le HSM a besoin de 4s pour s'initialiser complètement
Application: Mettre 4s pour ON et ATR
Impact: +2s au boot, toujours acceptable
```

### Scénario C: Succès avec Test 6 (5s/5s/1.5s)
```
Conclusion: Ce HSM spécifique est lent (variation hardware)
Application: Mettre des délais longs par défaut
Impact: +5s au boot, mais stable
Note: Peut être un défaut mineur du HSM, mais fonctionnel
```

### Scénario D: Aucun succès
```
Conclusion: Le problème N'EST PAS les délais
Investigation suivante:
  1. État HSM corrompu malgré reset
  2. Firmware HSM bugué
  3. Communication UART défectueuse
  4. Conflit ressources système
```

---

## 📁 STRUCTURE DES RÉSULTATS

Le script crée un répertoire avec tous les logs:

```
feature3/timing_tests/scan_20260123_110000/
├── test1_baseline_2.5s.log      ← Délais actuels
├── test2_on_3.5s.log            ← ON augmenté à 3.5s
├── test3_on_4s.log              ← ON augmenté à 4s
├── test4_atr_4s.log             ← ON + ATR à 4s
├── test5_before_select_1s.log   ← + délai avant SELECT
└── test6_very_long_5s.log       ← Délais très longs
```

**Vous pouvez:**
- Comparer les logs pour voir exactement où ça bloque
- Identifier le pattern de succès
- Documenter le timing optimal pour ce HSM spécifique

---

## 🎬 EXEMPLE DE SORTIE CONSOLE

### Si Test 3 Réussit:

```bash
$ ./test_hsm_timing_scan.sh

==============================================
  Test HSM: SCAN des Délais Optimaux
==============================================

⚠️  IMPORTANT: Débranchez/rebranchez le HSM MAINTENANT!
   Attendez 10 secondes après avoir rebranché

Appuyez sur ENTER quand le HSM est prêt...
✅ HSM détecté

📁 Résultats seront dans: feature3/timing_tests/scan_20260123_110000

╔════════════════════════════════════════╗
║  DÉBUT DU SCAN DES DÉLAIS OPTIMAUX    ║
╚════════════════════════════════════════╝


================================================
  TEST: test1_baseline_2.5s
================================================
  Délai après ON: 2500ms
  Délai après ATR: 3000ms
  Délai avant SELECT: 500ms
  Total attente: 6000ms

⚙️  Recompilation avec nouveaux délais...
✅ Compilation OK
🚀 Lancement ArduCopter (timeout 12s)...

📊 RÉSULTAT:
   ❌ Feature 1: ÉCHEC
      → Timeout sur SELECT applet CC


================================================
  TEST: test2_on_3.5s
================================================
  Délai après ON: 3500ms
  Délai après ATR: 3000ms
  Délai avant SELECT: 500ms
  Total attente: 7000ms

⚙️  Recompilation avec nouveaux délais...
✅ Compilation OK
🚀 Lancement ArduCopter (timeout 12s)...

📊 RÉSULTAT:
   ❌ Feature 1: ÉCHEC
      → Timeout sur SELECT applet CC


================================================
  TEST: test3_on_4s
================================================
  Délai après ON: 4000ms
  Délai après ATR: 3000ms
  Délai avant SELECT: 500ms
  Total attente: 7500ms

⚙️  Recompilation avec nouveaux délais...
✅ Compilation OK
🚀 Lancement ArduCopter (timeout 12s)...

📊 RÉSULTAT:
   ✅✅✅ Feature 1: SUCCÈS!
   ✅✅✅ Feature 2: SUCCÈS!
   ✅✅✅ Feature 3: SUCCÈS!

   🎉🎉🎉 TOUS LES TESTS RÉUSSIS! 🎉🎉🎉
   ✨ Délais optimaux trouvés! ✨

✅ SOLUTION TROUVÉE: Délai après ON = 4000ms
```

**🎉 VICTOIRE!** On sait maintenant que le HSM a besoin de **4 secondes** après "ON"!

---

## 🛠️ UTILISATION DU SCRIPT

### Commande:
```bash
./test_hsm_timing_scan.sh
```

### Prérequis:
1. ✅ HSM débranché puis rebranché (reset physique)
2. ✅ Attendre 10 secondes après rebranchement
3. ✅ Aucun processus n'utilise /dev/ttyUSB0

### Durée:
- **~2-3 minutes** si succès rapide (Test 2-3)
- **~5-6 minutes** si succès tardif (Test 6)
- Le script s'arrête dès qu'un test réussit

### Résultat:
- Identifie les **délais optimaux** pour votre HSM
- Sauvegarde tous les logs pour analyse
- Applique automatiquement la solution trouvée

---

## 🎯 APRÈS LE TEST

### Si un test réussit:

1. **Noter les délais qui marchent**
   ```
   Exemple: ON=4000ms, ATR=3000ms, SELECT=500ms
   ```

2. **Appliquer définitivement dans le code**
   ```bash
   # Éditer libraries/AP_HSM/AP_HSM.cpp
   # Mettre les délais trouvés
   ```

3. **Recompiler**
   ```bash
   ./waf copter
   ```

4. **Tester avec test_feature3.sh**
   ```bash
   ./test_feature3.sh
   ```

5. **Documenter dans travaille-feature3-realisation.md**
   ```
   Délais optimaux trouvés:
   - ON: 4000ms
   - ATR: 3000ms
   - SELECT: 500ms
   Total: 7.5s d'initialisation
   ```

### Si aucun test ne réussit:

1. **Débrancher HSM 60 secondes** (vraiment longtemps)
2. **Vérifier dmesg**: `dmesg | tail -50`
3. **Vérifier lsof**: `lsof /dev/ttyUSB0`
4. **Tester avec minicom**:
   ```bash
   minicom -D /dev/ttyUSB0 -b 115200
   # Taper: on
   # Observer la réponse
   ```

---

## 📚 RÉFÉRENCES

- **HSM Doc**: LeMonolith6.pdf pages 15-20 (timing specs)
- **Feature 1 Doc**: [feature1/travaille-feature1.md](../feature1/travaille-feature1.md)
- **Bug APDU**: [feature2/BLOCAGE-micro-ecc.md](../feature2/BLOCAGE-micro-ecc.md)

---

**Prêt à lancer le scan? Débranchez le HSM maintenant!** 🚀
