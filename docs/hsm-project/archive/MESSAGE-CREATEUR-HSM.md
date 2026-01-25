# Message pour le Créateur du HSM LeMonolith

---

**Objet:** Problème WRITE BINARY timeout après tests multiples - HSM LeMonolith v0.6

---

Bonjour,

Je vous contacte concernant un problème que je rencontre avec le **HSM LeMonolith v0.6** dans le cadre d'un projet d'intégration avec **ArduPilot** (logiciel de pilotage automatique pour drones).

## 📋 Contexte du Projet

J'ai intégré votre HSM LeMonolith dans ArduPilot pour sécuriser les communications MAVLink entre un drone et une station de contrôle au sol. Le projet utilise:

- **Microcontrôleur**: ArduPilot SITL (Software In The Loop)
- **Communication**: UART 115200 baud via /dev/ttyUSB0
- **Secure Element**: ATECC608B (applet CC, AID: 010203040601)
- **Opérations**: Génération clés ECDSA P-256, stockage EEPROM, chiffrement DEK

## ✅ Ce qui Fonctionne Parfaitement

Le HSM fonctionne **très bien** pour toutes les opérations de base:

1. **Initialisation**: OFF → ON → SELECT → VERIFY PIN ✅
2. **READ BINARY**: Lecture EEPROM rapide et fiable (~50ms) ✅
3. **Génération keypair**: P-256 avec stockage clé privée ✅
4. **Tests isolés**: Premier test de la journée fonctionne toujours ✅

Le crypto end-to-end (ECDH, HKDF, wrap/unwrap DEK) fonctionne parfaitement.

## ❌ Problème Rencontré

Après **10-15 tests rapides** (espacés de 2-5 secondes), le HSM entre dans un **état instable** qui persiste:

### Symptômes:

1. **WRITE BINARY timeout** systématique (commande `A 00D6...`)
   - Délai avant commande: 1000ms (récupération EEPROM)
   - Délai après commande: 3000ms (écriture EEPROM)
   - Timeout lecture réponse: 5000ms
   - **Total: 9 secondes d'attente, mais pas de réponse "9000"**

2. **READ BINARY continue de fonctionner** (lecture seulement)

3. **État persistant même après**:
   - Software reset (OFF → delay 5s → ON)
   - Hardware reset USB (débrancher 30-60s)
   - Les Features basiques (SELECT, VERIFY PIN) repassent
   - Mais WRITE BINARY continue de timeout

4. **Test direct en bash** montre:
   ```
   Réponse HSM: "ERROR No Command" répété en boucle
   ```

### Séquence de Dégradation:

```
Tests 1-5:   ✅✅✅✅✅ Tous réussis (WRITE OK)
Tests 6-10:  ✅⚠️✅❌❌ Dégradation progressive
Tests 11-15: ❌❌❌❌❌ WRITE timeout systématique
Tests 16+:   ❌❌❌❌❌ État instable persistant
```

## 🔬 Tests Effectués

J'ai effectué **40+ tests** avec différentes configurations:

### Scan de Timings:

| Configuration | Délai ON | Délai ATR | Délai Avant SELECT | Résultat WRITE |
|---------------|----------|-----------|-------------------|----------------|
| Baseline      | 2.5s     | 3s        | 0.5s              | ❌ Timeout     |
| Test 2        | 3.5s     | 3s        | 0.5s              | ❌ Timeout     |
| Test 3        | 4s       | 3s        | 0.5s              | ❌ Timeout     |
| Test 4        | 4s       | 4s        | 0.5s              | ❌ Timeout     |
| Test 5        | 4s       | 4s        | 1s                | ❌ Timeout     |
| Test 6        | 5s       | 5s        | 1.5s              | ❌ Timeout     |

**Aucun délai n'a résolu le problème** après que le HSM soit entré en état instable.

### Configuration Finale Validée (pour init):

- **OFF**: 200ms
- **ON**: 4000ms (augmenté de 2500ms)
- **ATR read**: 5000ms (augmenté de 3000ms)
- **Avant SELECT**: 1000ms (augmenté de 500ms)
- **WRITE delay**: 3000ms (augmenté de 2000ms)
- **WRITE timeout lecture**: 5000ms (augmenté de 3000ms)

**Résultat:** Features 1-2 passent (READ), mais Feature 3 WRITE échoue encore.

## 📊 Observations Détaillées

### 1. Pattern d'Utilisation qui Provoque le Problème:

```
Séquence type (répétée 10-15 fois):
1. OFF → delay 200ms
2. ON → delay 4000ms → read ATR 5000ms
3. SELECT CC → delay 1000ms
4. VERIFY PIN → delay 100ms
5. WRITE clé privée (32 bytes, offset 0x0100) → ✅ Succès (premiers tests)
6. READ clé privée → ✅ Succès (toujours)
7. WRITE DEK wrappée (32 bytes, offset 0x0120) → ❌ Timeout (après test 10+)
8. WRITE auth tag (32 bytes, offset 0x0140) → ❌ Timeout

Pause entre tests: 2-10 secondes
```

### 2. Commandes WRITE qui Timeout:

```
APDU envoyé:
A 00D6012020<64_caractères_hex_wrapped_dek>
A 00D6014020<64_caractères_hex_auth_tag>

Réponse attendue: "9000"
Réponse reçue: [TIMEOUT après 5 secondes]

Note: Même commande fonctionne aux tests 1-5
```

### 3. État des Buffers:

Le code ArduPilot fait:
```cpp
flush_input();                    // Vider buffer UART
uart->printf("A 00D6...\r\n");   // Envoyer WRITE
delay(3000);                      // Attendre EEPROM write
// Lire réponse avec timeout 5000ms
```

Malgré le flush et les délais, pas de réponse après test 10+.

### 4. Test Direct Bash (HSM seul):

```bash
(echo "off\r"; sleep 1;
 echo "on\r"; sleep 6;
 echo "A 00A4040006010203040601\r"; sleep 1;  # SELECT
 echo "A 00200001083030303030303030\r"; sleep 1;  # VERIFY PIN
 echo "A 00D6012020AAAA...AAAA\r") > /dev/ttyUSB0  # WRITE

Sortie:
OK                                   # OFF
9000                                 # ON
9000                                 # SELECT
9000                                 # VERIFY PIN
[TIMEOUT ou ERROR No Command]       # WRITE (après 15 tests)
```

## 🤔 Hypothèses

### 1. EEPROM Protection/Wear Leveling:

Le SE ATECC608B entre-t-il en mode "protection" après trop d'écritures rapides?
- Tests 1-5: OK
- Tests 6-15: Progressivement KO
- Suggère un seuil interne ou buffer saturation

### 2. ESP32 Buffer/State Machine:

L'ESP32 (qui gère UART ↔ I2C vers SE) pourrait:
- Accumuler des commandes dans un buffer interne
- Entrer dans un état "bloqué" de sa state machine
- Ne plus parser correctement les commandes APDU

### 3. Timing I2C Interne:

Si le SE prend plus de temps que prévu (4-5s au lieu de 2-3s):
- ESP32 pourrait timeout en interne
- Ne retournerait pas "9000" même si SE a réussi
- READ plus rapide → pas de problème

## 🎯 Questions au Créateur

1. **Y a-t-il une limitation connue** sur le nombre d'écritures EEPROM consécutives dans l'ATECC608B ou l'applet CC?

2. **Le firmware ESP32 a-t-il un buffer** qui pourrait saturer après tests multiples?

3. **Existe-t-il une commande de "reset soft"** du HSM (sans débrancher USB) pour vider les buffers et reset l'état interne?

4. **Les délais suivants sont-ils suffisants** pour votre implémentation:
   - WRITE delay: 3000ms
   - WRITE timeout: 5000ms
   - Ou faut-il 6-8 secondes?

5. **Y a-t-il des logs/debug** disponibles côté ESP32 pour comprendre ce qui se passe en interne? (via UART ou autre port de debug)

6. **Est-ce un comportement connu/documenté?** Y a-t-il un patch firmware ou une meilleure pratique?

## 💻 Script de Simulation

J'ai créé un **script Python** qui simule le problème et peut vous aider à le reproduire. Le script est disponible dans le fichier joint `simulate_hsm_write_issue.py`.

Le script:
- Simule 20 tests consécutifs
- Montre la dégradation progressive après test 10
- Reproduit les timeouts WRITE
- Génère des logs détaillés

**Pour l'exécuter:**
```bash
python3 simulate_hsm_write_issue.py
```

## 📁 Documentation Fournie

J'ai documenté tout le projet et le problème dans ces fichiers (disponibles sur demande):

1. **EXPLICATION-WRITE-FAILED.md** - Analyse détaillée du problème
2. **DIAGNOSTIC-HSM-INSTABLE.md** - Diagnostic complet
3. **build_skill/hsm_skills.md** - Guide complet utilisation HSM (24 KB)
4. **Logs de tests** - 40+ tests avec résultats

## 🚀 Impact sur le Projet

Malgré ce problème, **95% du projet fonctionne**:
- ✅ Initialisation HSM
- ✅ Génération/stockage keypair P-256
- ✅ Lecture EEPROM (READ BINARY)
- ✅ Crypto end-to-end (ECDH, HKDF, wrap/unwrap)
- ⏳ **Seul le stockage DEK échoue** (WRITE après 10 tests)

**Workaround actuel:** Mode RAM-only (DEK en cache, pas de persistance)

## 🙏 Demande d'Assistance

Pourriez-vous:
1. **Confirmer** si c'est un comportement connu
2. **Suggérer** des délais ou commandes que je n'ai pas essayés
3. **Fournir** une mise à jour firmware si disponible
4. **Expliquer** le comportement interne du HSM lors de WRITE multiples

Je suis disponible pour:
- Fournir tous les logs détaillés
- Tester des configurations spécifiques
- Faire des tests avec votre équipe en remote
- Mettre à jour le firmware HSM si nécessaire

## 📞 Contact

**Email:** [votre_email]
**Projet:** ArduPilot + HSM LeMonolith
**HSM Version:** LeMonolith v0.6
**Secure Element:** ATECC608B
**Applet:** CC (AID: 010203040601)

Merci beaucoup pour votre temps et votre aide!

Cordialement,
[Votre Nom]

---

**P.S.:** Le projet ArduPilot + HSM est très prometteur et votre HSM fonctionne excellemment pour 95% des cas. Une solution à ce problème le rendrait parfait pour la production!

**Pièces jointes suggérées:**
- simulate_hsm_write_issue.py (script simulation)
- Logs de tests (extrait représentatif)
- EXPLICATION-WRITE-FAILED.md (analyse complète)
