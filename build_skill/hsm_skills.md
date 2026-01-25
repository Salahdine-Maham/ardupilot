# HSM Skills - Connaissances HSM LeMonolith

**Date**: 2026-01-23
**Projet**: Intégration HSM LeMonolith v0.6 avec ArduPilot
**Périphérique**: LeMonolith HSM avec Secure Element ATECC608B
**Utilisation**: Humain ou AI pour projets similaires

---

## 1. CARACTÉRISTIQUES HSM LEMONOLITH

### 1.1 Architecture Hardware

**Composants:**
- **ESP32**: Microcontrôleur principal, gère UART et protocole
- **ATECC608B**: Secure Element (JavaCard)
- **EEPROM**: Stockage persistant (2KB utilisable)
- **Interface**: UART 115200 baud, USB (CH340 ou CP2102)

**Connexion USB:**
```bash
# Vérifier détection
ls -la /dev/ttyUSB0
# Résultat: crw-rw---- 1 root dialout 188, 0 [date] /dev/ttyUSB0

# Qui utilise
lsof /dev/ttyUSB0

# Permissions (ajouter user au groupe dialout si nécessaire)
sudo usermod -a -G dialout $USER
# Puis logout/login
```

### 1.2 Protocole de Communication

**Baudrate fixe:** 115200 baud
**Line ending:** `\r\n` (Carriage Return + Line Feed)
**Format commandes:** ASCII texte

**Commandes de base:**
```
off\r\n    → Désactive Secure Element
on\r\n     → Active Secure Element (retourne ATR)
```

**Commandes APDU (après ON):**
```
Format: "A <APDU_HEX>\r\n"
Exemple: A 00A4040006010203040601\r\n
```

**Réponses multi-lignes:**
```
Tx: <echo commande>
TxT1: <valeur>
Rx[Xms]:
<données hexadécimales>
9000       ← Status Word (succès)
```

### 1.3 États du HSM

**Séquence d'initialisation:**
```
1. OFF  → Secure Element désactivé
2. ON   → Secure Element activé, ATR émis (~3-5 secondes)
3. SELECT applet → Sélection applet CC (Crypto Currency)
4. VERIFY PIN → Authentification avec PIN user
5. READY → Prêt pour opérations READ/WRITE
```

**État après reset USB:**
- Secure Element: OFF
- EEPROM: Données préservées
- Buffers: Vidés

---

## 2. APPLET CRYPTO CURRENCY (CC)

### 2.1 Identification Applet

**AID (Application Identifier):** `010203040601`
**Nom:** Applet CC (Crypto Currency)
**Version:** v0.6

**Commande SELECT:**
```
APDU: A0 A4 04 00 06 01 02 03 04 06 01
Format: A 00A4040006010203040601
Réponse: 9000 (succès)
```

### 2.2 Authentification PIN

**PIN par défaut:** `00000000` (8 caractères ASCII)
**PIN en hex:** `3030303030303030`

**Commande VERIFY PIN:**
```
APDU: A0 20 00 01 08 30 30 30 30 30 30 30 30
Format: A 00200001083030303030303030
Réponse: 9000 (succès)
```

**Codes d'erreur PIN:**
- `9000`: PIN correct
- `63CX`: PIN incorrect, X tentatives restantes
- `6983`: PIN bloqué (trop de tentatives)

### 2.3 Layout EEPROM

**Structure recommandée:**
```
Offset    Taille    Usage
------    ------    -----
0x0100    32 bytes  Clé privée P-256
0x0120    32 bytes  Wrapped DEK (Feature 3)
0x0140    32 bytes  Auth tag HMAC (Feature 3)
0x0160    64 bytes  Clé publique P-256 (si stockée)
0x01A0    ...       Espace libre

Note: Offsets en hexadécimal
Note: Total EEPROM ~2KB, utiliser judicieusement
```

**Important:**
- **Offset 0x0000-0x00FF**: Réservé système (ne pas écrire)
- **Offset 0x0100+**: Utilisable pour données custom
- Aligner sur boundaries 32/64 bytes pour clarté

---

## 3. COMMANDES APDU

### 3.1 READ BINARY

**Lecture depuis EEPROM:**
```
Format: A0 D0 [Offset_High] [Offset_Low] [Length]

Exemples:
# Lire 32 bytes à offset 0x0100
A 00D001002000
   ││││││└─── 0x20 = 32 bytes
   ││││└└──── 0x0100 = offset
   │││└────── D0 = READ BINARY
   ││└─────── A0 = CLA
   │└──────── 00 = INS pour commande SELECT
   └───────── A = Préfixe commande APDU

# Lire 64 bytes à offset 0x0120
A 00D001204000
```

**Réponse:**
```
Tx: 00D001002000
TxT1: ...
Rx[10ms]:
<32 bytes hex>
9000
```

**Temps de réponse:** ~10-50ms

### 3.2 WRITE BINARY

**Écriture vers EEPROM:**
```
Format: A0 D6 [Offset_High] [Offset_Low] [Length] [Data...]

Exemples:
# Écrire 32 bytes à offset 0x0100
A 00D6010020<32_bytes_hex>

# Écrire 64 bytes à offset 0x0120
A 00D6012040<64_bytes_hex>
```

**Important WRITE BINARY:**
- ⚠️  **Temps d'écriture:** 2000-3000ms (2-3 secondes!)
- ⚠️  **Délai OBLIGATOIRE:** Attendre 2s+ après commande
- ⚠️  **Vérifier réponse 9000** avant considérer succès
- ⚠️  **Pas de burst writes:** Attendre fin avant nouvelle écriture

**Code d'implémentation:**
```cpp
bool write_to_hsm(uint16_t offset, const uint8_t* data, uint8_t len) {
    // Construire APDU
    char apdu[256];
    snprintf(apdu, sizeof(apdu), "A 00D6%04X%02X", offset, len);
    for (int i = 0; i < len; i++) {
        char hex[3];
        snprintf(hex, sizeof(hex), "%02X", data[i]);
        strcat(apdu, hex);
    }

    // Envoyer
    uart->printf("%s\r\n", apdu);

    // DÉLAI CRITIQUE pour EEPROM
    hal.scheduler->delay(2000);  // Minimum 2 secondes

    // Lire réponse
    char response[256];
    if (!read_response(response, sizeof(response), 3000)) {
        return false;  // Timeout
    }

    // Vérifier 9000
    return (strstr(response, "9000") != nullptr);
}
```

### 3.3 GENERATE KEY (ECDSA P-256)

**Génération keypair interne:**
```
Format: A0 46 00 00 [params...]
Non documenté en détail dans notre projet

Alternative: Générer avec micro-ecc et stocker
```

**Notre approche (Feature 2):**
```cpp
// Générer avec micro-ecc
uECC_Curve curve = uECC_secp256r1();
uint8_t private_key[32];
uint8_t public_key[64];
uECC_make_key(public_key, private_key, curve);

// Stocker clé privée dans HSM
write_to_hsm(0x0100, private_key, 32);

// Garder clé publique en cache RAM
memcpy(public_key_cache, public_key, 64);
```

**Avantages:**
- ✅ Contrôle total sur génération
- ✅ Même courbe P-256 que applet
- ✅ Pas de dépendance sur commandes HSM non-doc

---

## 4. PROBLÈMES COURANTS ET SOLUTIONS

### 4.1 Timeout SELECT Applet CC

**Symptôme:**
```
HSM: SE désactivé ✅
HSM: SE activé ✅
HSM: Erreur - Timeout SELECT applet CC ❌
```

**Causes possibles:**

**Cause 1: Délais insuffisants après ON**
```cpp
// ❌ Trop court
uart->printf("on\r\n");
delay(1500);  // Insuffisant

// ✅ Correct
uart->printf("on\r\n");
delay(2500);  // Ou plus si HSM lent
```

**Cause 2: Buffer UART pas vidé**
```cpp
// ❌ Pas de flush
uart->printf("on\r\n");
delay(2500);
// ATR reste dans buffer, perturbe SELECT

// ✅ Avec flush
uart->printf("on\r\n");
delay(2500);
// Lire et vider ATR
while ((millis() - start) < 3000) {
    if (uart->available() > 0) {
        uart->read();  // Ignorer ATR
    }
}
flush_input();  // Sécurité supplémentaire
delay(500);
// Maintenant SELECT
```

**Cause 3: Option --console dans ArduPilot**
```bash
# ❌ Interfère avec UART
arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 --console

# ✅ Sans --console, avec MAVProxy
arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &
mavproxy.py --master=tcp:127.0.0.1:5760 --console
```

**Cause 4: HSM en état instable**
```
Solution: Reset physique
1. Débrancher USB
2. Attendre 30-60 secondes
3. Rebrancher
4. Attendre 10 secondes
5. Relancer test
```

### 4.2 Réponses Corrompues ou Multiples

**Symptôme:**
```
9000
9000
9000
[Répété 100x]
```

**Cause:** Timing désynchronisé, commandes envoyées trop vite

**Solution:**
```cpp
// Flush avant CHAQUE commande importante
void flush_input() {
    while (uart->available() > 0) {
        uart->read();
    }
}

flush_input();
uart->printf("commande\r\n");
delay(100);  // Laisser HSM traiter
```

### 4.3 WRITE BINARY Timeout

**Symptôme:**
```
HSM: Envoi WRITE wrapped_dek...
HSM: Délai EEPROM write (2s)...
HSM: Erreur - Timeout WRITE wrapped_dek ❌
```

**Causes:**

**Cause 1: Délai insuffisant**
```cpp
// ❌ Trop court
uart->printf("A 00D6...\r\n");
delay(1000);  // Insuffisant pour EEPROM

// ✅ Correct
uart->printf("A 00D6...\r\n");
delay(2000);  // Minimum pour EEPROM write
```

**Cause 2: HSM pas dans bon état**
```
Vérifier séquence:
1. OFF → OK
2. ON → OK
3. SELECT → OK?
4. VERIFY PIN → OK?
5. WRITE → Seulement si 3-4 OK!
```

**Cause 3: Multiple writes sans pause**
```cpp
// ❌ Writes successifs sans pause
write_to_hsm(0x0120, data1, 32);
write_to_hsm(0x0140, data2, 32);  // Échec!

// ✅ Avec pause entre writes
write_to_hsm(0x0120, data1, 32);
delay(500);  // Pause inter-write
write_to_hsm(0x0140, data2, 32);  // Succès
```

### 4.4 HSM Instable après Tests Multiples

**Symptôme:**
```
Test 1: ✅ Succès
Test 2: ✅ Succès
Test 3: ❌ Timeout
Test 4: ❌ Timeout
Test 5: ❌ Timeout
[Tous les tests suivants échouent]
```

**Cause:** Accumulation de stress sur EEPROM et buffers internes

**Solutions:**

**Solution 1: Reset physique entre tests**
```bash
# Après 5-10 tests:
# 1. Débrancher HSM (30-60s)
# 2. Rebrancher
# 3. Attendre 10s
# 4. Relancer
```

**Solution 2: Délais entre tests automatisés**
```bash
#!/bin/bash
for i in {1..10}; do
    ./test.sh
    echo "Attente 10s avant test suivant..."
    sleep 10  # Laisser HSM récupérer
done
```

**Solution 3: Limiter écritures EEPROM**
```cpp
// Éviter writes inutiles
if (!dek_changed) {
    // Réutiliser DEK existante, pas de write
    return true;
}
// Write seulement si nécessaire
```

---

## 5. TIMINGS CRITIQUES

### 5.1 Délais Recommandés

**Initialisation:**
```cpp
// OFF
uart->printf("off\r\n");
delay(200);              // Court, juste arrêt SE

// ON
uart->printf("on\r\n");
delay(2500);             // CRITIQUE: 2.5s minimum
                         // Certains HSM: 3-4s nécessaires

// Lecture ATR
uint32_t start = millis();
while ((millis() - start) < 3000) {  // 3s timeout
    if (uart->available() > 0) {
        uart->read();    // Consommer ATR
    }
    delay(10);
}

// Flush post-ATR
flush_input();
delay(200);              // Laisser buffer se stabiliser
flush_input();           // Double flush sécurité
delay(200);

// SELECT
delay(500);              // Avant SELECT
uart->printf("A 00A4...\r\n");
// Attendre réponse (timeout 3s)

// VERIFY PIN
delay(100);              // Entre commandes
uart->printf("A 0020...\r\n");
```

**Opérations READ/WRITE:**
```cpp
// READ BINARY
uart->printf("A 00D0...\r\n");
delay(100);              // Court, lecture rapide
// Timeout réponse: 1000ms

// WRITE BINARY
uart->printf("A 00D6...\r\n");
delay(2000);             // CRITIQUE: 2s minimum
                         // Recommandé: 2.5-3s pour sécurité
// Timeout réponse: 3000ms

// Entre deux WRITE
write_1();
delay(500);              // Pause inter-write
write_2();
```

### 5.2 Timeouts Recommandés

```cpp
// Fonction send_apdu() - timeouts
bool send_apdu(const char* apdu, char* response, size_t len) {
    // Détecter type commande
    bool is_write = (strstr(apdu, "00D6") != nullptr);

    // Délai adapté
    if (is_write) {
        delay(2000);     // WRITE BINARY
    } else {
        delay(100);      // Autres commandes
    }

    // Lecture réponse avec timeout
    uint32_t timeout = 3000;  // 3s pour toutes commandes
    uint32_t start = millis();

    while ((millis() - start) < timeout) {
        if (uart->available() > 0) {
            // Lire réponse...
        }
    }

    return false;  // Timeout
}
```

### 5.3 Scan de Timings

**Si timeout persiste, scan systématique:**
```bash
# Test 1: Baseline (2.5s/3s/0.5s)
# Test 2: ON=3.5s
# Test 3: ON=4s
# Test 4: ON=4s, ATR=4s
# Test 5: ON=4s, ATR=4s, SELECT=1s
# Test 6: ON=5s, ATR=5s, SELECT=1.5s

# Script fourni: test_hsm_timing_scan.sh
```

**Résultats observés:**
```
HSM spécifiques peuvent nécessiter:
- ON delay: 3-5 secondes
- ATR read: 3-4 secondes
- Avant SELECT: 0.5-1 seconde
Total: 7-11 secondes pour init complète
```

---

## 6. ARCHITECTURE RECOMMANDÉE

### 6.1 Classe AP_HSM - Structure

```cpp
class AP_HSM {
public:
    AP_HSM() {}

    // Init
    bool init(AP_HAL::UARTDriver *uart);
    bool init_monolith();  // OFF→ON→SELECT→VERIFY

    // Feature 1: Init HSM
    bool load_keypair();
    bool generate_keypair();

    // Feature 2: Keypair P-256
    bool read_private_key_from_hsm(uint8_t key[32]);
    bool write_private_key_to_hsm(const uint8_t key[32]);
    const uint8_t* get_public_key();   // Getter cache

    // Feature 3: DEK ChaCha20-256
    bool generate_dek();
    bool compute_ecdh(const uint8_t* pub_remote, uint8_t secret[32]);
    bool derive_wrapping_key(const uint8_t secret[32], uint8_t wrap[32]);
    bool wrap_dek(const uint8_t wrap[32], uint8_t wrapped[32], uint8_t tag[32]);
    bool unwrap_dek(const uint8_t wrapped[32], const uint8_t tag[32], const uint8_t wrap[32]);
    bool store_dek_to_hsm(const uint8_t wrapped[32], const uint8_t tag[32]);
    bool load_dek_from_hsm(uint8_t wrapped[32], uint8_t tag[32]);

private:
    // UART
    AP_HAL::UARTDriver *uart_hsm = nullptr;
    bool initialized = false;

    // Cache clés
    uint8_t private_key_cache[32];
    uint8_t public_key_cache[64];
    uint8_t dek_cache[32];
    bool keypair_loaded = false;
    bool dek_loaded = false;

    // Helpers
    bool send_apdu(const char* apdu, char* response, size_t len);
    void flush_input();
};
```

### 6.2 Offsets EEPROM - Constantes

```cpp
// Dans AP_HSM.h ou .cpp
#define HSM_OFFSET_PRIVATE_KEY   0x0100  // 32 bytes
#define HSM_OFFSET_WRAPPED_DEK   0x0120  // 32 bytes
#define HSM_OFFSET_DEK_AUTH_TAG  0x0140  // 32 bytes
#define HSM_OFFSET_PUBLIC_KEY    0x0160  // 64 bytes (optionnel)

// Tailles
#define HSM_SIZE_PRIVATE_KEY     32
#define HSM_SIZE_PUBLIC_KEY      64
#define HSM_SIZE_DEK             32
#define HSM_SIZE_HMAC_TAG        32
```

### 6.3 Séquence d'Utilisation Typique

```cpp
// Dans AP_Vehicle::init_ardupilot()

// 1. Init HSM
AP_HSM hsm;
if (!hsm.init(uart)) {
    printf("HSM: Init failed\n");
    return;
}

// 2. Feature 1: Init Monolith + Keypair
if (!hsm.init_monolith()) {
    printf("HSM: Monolith init failed\n");
    return;
}

if (!hsm.load_keypair()) {
    printf("HSM: Génération nouvelle keypair\n");
    hsm.generate_keypair();
}
printf("HSM: ✓ Feature 1 OK\n");

// 3. Feature 2: Keypair en cache
const uint8_t* pubkey = hsm.get_public_key();
if (pubkey) {
    printf("HSM: ✓ Feature 2 OK\n");
}

// 4. Feature 3: DEK
uint8_t public_remote[64];  // De GCS
uint8_t shared_secret[32];
uint8_t wrapping_key[32];
uint8_t wrapped_dek[32];
uint8_t auth_tag[32];

// Try load existing
if (hsm.load_dek_from_hsm(wrapped_dek, auth_tag)) {
    hsm.compute_ecdh(public_remote, shared_secret);
    hsm.derive_wrapping_key(shared_secret, wrapping_key);
    if (hsm.unwrap_dek(wrapped_dek, auth_tag, wrapping_key)) {
        printf("HSM: ✓ DEK loaded from HSM\n");
    }
} else {
    // Generate new
    hsm.generate_dek();
    hsm.compute_ecdh(public_remote, shared_secret);
    hsm.derive_wrapping_key(shared_secret, wrapping_key);
    hsm.wrap_dek(wrapping_key, wrapped_dek, auth_tag);
    hsm.store_dek_to_hsm(wrapped_dek, auth_tag);
    printf("HSM: ✓ New DEK generated and stored\n");
}
printf("HSM: ✓ Feature 3 OK\n");
```

---

## 7. TESTS ET VALIDATION

### 7.1 Test Direct HSM (sans ArduPilot)

**Test basique avec echo:**
```bash
#!/bin/bash
# test_hsm_direct.sh

# Test OFF
echo -e "off\r" > /dev/ttyUSB0
sleep 1
timeout 1s cat /dev/ttyUSB0

# Test ON
echo -e "on\r" > /dev/ttyUSB0
sleep 4
timeout 2s cat /dev/ttyUSB0

# Test SELECT
echo -e "A 00A4040006010203040601\r" > /dev/ttyUSB0
sleep 1
timeout 2s cat /dev/ttyUSB0
```

**Résultat attendu:**
```
OK          ← OFF
9000        ← ON (après ATR)
9000        ← SELECT
```

### 7.2 Test Séquence Complète

**Script bash complet:**
```bash
#!/bin/bash
# test_hsm_sequence.sh

(
  echo -e "off\r"
  sleep 1
  echo -e "on\r"
  sleep 5
  echo -e "A 00A4040006010203040601\r"  # SELECT
  sleep 1
  echo -e "A 00200001083030303030303030\r"  # VERIFY PIN
  sleep 1
  echo -e "A 00D0010020\r"  # READ 32 bytes @ 0x0100
  sleep 1
) > /dev/ttyUSB0 &

sleep 1
timeout 15s cat /dev/ttyUSB0
```

### 7.3 Patterns de Validation

**Vérifier succès dans logs ArduPilot:**
```bash
# Feature 1
grep "✓ Feature 1 complétée avec succès" log.txt
grep "Application CC sélectionnée" log.txt
grep "PIN User vérifié" log.txt

# Feature 2
grep "✓ Feature 2 complétée avec succès" log.txt
grep "Public key (64 bytes):" log.txt | head -1

# Feature 3
grep "✓ Feature 3 complétée avec succès" log.txt
grep "DEK (32 bytes):" log.txt | head -1
grep "✓ DEK wrappée stockée avec succès" log.txt

# Erreurs
grep -E "(Erreur|Timeout|échoué)" log.txt
```

---

## 8. SÉCURITÉ ET BEST PRACTICES

### 8.1 Gestion des Clés Privées

**À FAIRE:**
- ✅ Stocker clé privée dans EEPROM HSM (offset 0x0100)
- ✅ Charger en cache RAM au boot uniquement
- ✅ Ne jamais logger clé privée en production
- ✅ Effacer cache RAM si nécessaire (pas implémenté SITL)

**À NE PAS FAIRE:**
- ❌ Logger clé privée: `printf("Private: %s", key);`
- ❌ Transmettre clé privée sur MAVLink
- ❌ Stocker clé privée en clair ailleurs que HSM

### 8.2 Validation HMAC

**Toujours vérifier tag HMAC avant unwrap:**
```cpp
bool unwrap_dek(const uint8_t wrapped[32], const uint8_t tag[32],
                const uint8_t wrap[32]) {
    // Recalculer HMAC
    uint8_t computed_tag[32];
    hmac_sha256(wrap, 32, wrapped, 32, computed_tag);

    // Comparer avec tag stocké
    if (memcmp(tag, computed_tag, 32) != 0) {
        printf("HSM: Erreur - Tag HMAC invalide\n");
        return false;  // Données corrompues ou mauvaise clé
    }

    // Tag valide, unwrap
    for (int i = 0; i < 32; i++) {
        dek_cache[i] = wrapped[i] ^ wrap[i];
    }
    return true;
}
```

### 8.3 Gestion Erreurs EEPROM

**Retry logic pour writes:**
```cpp
bool write_with_retry(uint16_t offset, const uint8_t* data, uint8_t len) {
    const int MAX_RETRIES = 3;

    for (int i = 0; i < MAX_RETRIES; i++) {
        if (write_to_hsm(offset, data, len)) {
            return true;  // Succès
        }

        printf("HSM: Retry write %d/%d\n", i+1, MAX_RETRIES);
        delay(500);  // Pause avant retry
    }

    printf("HSM: Erreur - Write failed après %d retries\n", MAX_RETRIES);
    return false;
}
```

### 8.4 Limite Écritures EEPROM

**EEPROM a durée de vie limitée:**
```
Typical: 100,000 cycles write/erase
Conservateur: 10,000 cycles garantis

Calcul:
- 1 write/boot
- 10 boots/jour
- 10,000 cycles / 10 = 1,000 jours = ~3 ans
- 100,000 cycles / 10 = 10,000 jours = ~27 ans

Conclusion: OK pour usage normal, éviter writes fréquentes
```

**Stratégie:**
```cpp
// Éviter writes inutiles
bool need_update = false;
if (memcmp(old_dek, new_dek, 32) != 0) {
    need_update = true;
}

if (need_update) {
    write_to_hsm(offset, new_dek, 32);
} else {
    printf("HSM: DEK inchangée, pas de write\n");
}
```

---

## 9. DÉPANNAGE AVANCÉ

### 9.1 Commandes Minicom

**Test interactif:**
```bash
# Lancer minicom
minicom -D /dev/ttyUSB0 -b 115200

# Commandes à taper:
off [ENTER]
on [ENTER]
A 00A4040006010203040601 [ENTER]
A 00200001083030303030303030 [ENTER]

# Quitter: Ctrl+A puis X
```

### 9.2 Capture Traces UART

**Avec screen:**
```bash
# Lancer capture
screen -L -Logfile hsm_trace.txt /dev/ttyUSB0 115200

# Envoyer commandes
# Traces sauvegardées dans hsm_trace.txt

# Quitter: Ctrl+A puis K
```

**Avec cat en background:**
```bash
# Capturer tout ce que HSM envoie
cat /dev/ttyUSB0 > hsm_output.txt &
CAT_PID=$!

# Envoyer commandes
echo -e "on\r" > /dev/ttyUSB0

# Après tests
kill $CAT_PID
cat hsm_output.txt
```

### 9.3 Reset Hardware vs Software

**Software reset (OFF/ON):**
```bash
echo -e "off\r" > /dev/ttyUSB0
sleep 1
echo -e "on\r" > /dev/ttyUSB0
```
- Reset Secure Element uniquement
- EEPROM préservée
- Buffers UART peuvent rester sales

**Hardware reset (USB déconnexion):**
```bash
# Débrancher USB
# Attendre 30-60 secondes
# Rebrancher
sleep 10
```
- Reset complet: ESP32 + SE + buffers
- EEPROM préservée
- Tous les condensateurs vidés
- État "propre" garanti

**Quand utiliser:**
- Software: Entre commandes, changement état
- Hardware: HSM instable, tests multiples, état corrompu

---

## 10. ERREURS FRÉQUENTES

### 10.1 Erreur: "ERROR No Command"

**Symptôme:**
```
ERROR No Command!
ERROR No Command!
[Répété en boucle]
```

**Cause:** HSM en état très instable, firmware ne reconnaît plus commandes

**Solution:**
```
1. Hardware reset (60 secondes)
2. Si persiste: Reflash firmware HSM (si accès)
3. Si persiste encore: HSM potentiellement endommagé
```

### 10.2 Erreur: "6D00" (Instruction Not Supported)

**Symptôme:**
```
Rx[10ms]:
6D00
```

**Cause:**
- Applet CC pas sélectionné
- PIN pas vérifié
- Commande invalide pour cet applet

**Solution:**
```
Vérifier séquence:
1. OFF → ON ✓
2. SELECT CC ✓
3. VERIFY PIN ✓
4. Commande APDU
```

### 10.3 Erreur: "6982" (Security Status Not Satisfied)

**Cause:** PIN pas vérifié

**Solution:**
```
Envoyer VERIFY PIN:
A 00200001083030303030303030
```

### 10.4 Erreur: Tag HMAC Invalide

**Symptôme:**
```
HSM: Erreur - Tag HMAC invalide (corruption ou mauvaise clé)
```

**Causes possibles:**
1. Première utilisation (EEPROM vide → données random)
2. Wrapping key différente (public_remote changée)
3. Corruption EEPROM (rare)
4. Bug dans code wrap/unwrap

**Solution:**
```cpp
// Détecter première utilisation vs corruption réelle
if (!unwrap_dek(...)) {
    // Vérifier si offset vide (tous 0x00 ou 0xFF)
    bool is_empty = true;
    for (int i = 0; i < 32; i++) {
        if (wrapped[i] != 0x00 && wrapped[i] != 0xFF) {
            is_empty = false;
            break;
        }
    }

    if (is_empty) {
        printf("HSM: Première utilisation, génération DEK...\n");
    } else {
        printf("HSM: Corruption détectée, régénération...\n");
    }

    // Dans les deux cas: générer nouvelle DEK
    generate_new_dek();
}
```

---

## 11. RÉFÉRENCES

### 11.1 Documentation HSM

- **LeMonolith Documentation**: LeMonolith6.pdf (si disponible)
- **ATECC608B Datasheet**: Microchip ATECC608B-TNGTLS Secure Element
- **JavaCard Specs**: ISO/IEC 7816-4 (APDU format)

### 11.2 Codes Status APDU Standards

```
9000: Succès
6283: Fichier invalidé
6300: Authentication failed
63CX: PIN incorrect, X tentatives restantes
6700: Wrong length
6982: Security status not satisfied (PIN requis)
6983: Authentication method blocked (PIN bloqué)
6A80: Incorrect parameters
6A82: File not found
6A86: Incorrect P1 P2
6D00: Instruction not supported
6E00: Class not supported
6F00: Unknown error
```

### 11.3 Outils Utiles

```bash
# Monitorer UART
minicom -D /dev/ttyUSB0 -b 115200
screen /dev/ttyUSB0 115200
picocom /dev/ttyUSB0 -b 115200

# Hex dump
xxd fichier.bin

# Serial monitor Arduino IDE (si disponible)

# Wireshark (pour debug protocole complexe)
# Nécessite adaptateur USB-UART avec support capture
```

---

## 12. CHECKLIST DEBUG

### Avant de Débugger HSM:

```
□ HSM branché? (ls -la /dev/ttyUSB0)
□ Aucun processus utilise HSM? (lsof /dev/ttyUSB0)
□ Permissions OK? (groupe dialout)
□ HSM reset récemment? (< 5 minutes)
□ Derniers tests espacés? (> 10s entre tests)
□ Pas de --console dans commande ArduPilot?
□ MAVProxy utilisé pour connexion TCP?
□ Logs activés et sauvegardés?
□ Pas plus de 10 tests sans reset hardware?
```

### Pendant Debug:

```
□ Vérifier messages "HSM:" dans logs
□ Chercher "Erreur", "Timeout", "échoué"
□ Vérifier séquence OFF→ON→SELECT→PIN
□ Vérifier délais après chaque commande
□ Vérifier réponses contiennent "9000"
□ Si échec persistant: reset hardware 60s
□ Tester avec script bash direct avant ArduPilot
```

### Après Tests:

```
□ Sauvegarder tous les logs
□ Noter délais qui ont fonctionné
□ Documenter comportement HSM spécifique
□ Attendre 10s avant prochain test
□ Reset hardware après session intensive (10+ tests)
```

---

## 13. SCRIPTS DE GESTION LEMONOLITH

### 13.1 Architecture des Scripts

**Structure de répertoires:**
```
CryptoTokenESP12-Release/
├── *.bat                    # Scripts racine (lanceurs principaux)
├── SELoaderSerial/          # Scripts USB Serial (winscard.dll SHIM)
├── SELoaderIOSE/            # Scripts IoSE (Internet of Secure Element)
├── SELoader_NET/            # Scripts Wi-Fi NET
├── ESP32Loader/             # Flash firmware ESP32
├── im/                      # Installation Manufacturing
├── openssl/                 # Tests SSL avec OpenSSL
├── wolfssl/                 # Tests SSL avec wolfSSL
├── keystore/                # Gestion clés Ethereum
├── iose/                    # Serveur IoSE et RACS
├── CertSerial/              # Certificats via Serial
├── CertPCSC/                # Certificats via PC/SC
├── makercert/               # Création certificats
├── config/                  # Configuration HSM
├── btools/                  # Outils de base
└── mfa/                     # Multi-Factor Authentication
```

### 13.2 Patterns de Scripts - Types de Base

**Pattern 1: Lanceur Simple (Racine)**
```batch
@echo off
cd .\<sous-dossier>
Call <script_reel>.bat
exit
```

Exemples:
- `FACTORY_All.bat` → cd im → MakeFactoryAll.bat
- `USB_GP_install.bat` → cd SELoaderSerial → GP_Install_Factory_2.bat
- `SSL_openssl.bat` → cd openssl → openssl.bat
- `IOSE_Openssl.bat` → cd iose → openssl_127_0_0_1_8888.bat

**Pattern 2: Commande gpshell**
```batch
@echo off
gpshell <fichier_script>.txt
PAUSE
```

Exemples:
- `list_SCP03.bat` → gpshell listSCP03.txt
- `delete_All_SCP03.bat` → gpshell delete_All_SCP03.txt

**Pattern 3: Configuration Serial (makecardconfig.bat)**
```batch
@echo off
listcom CP210x 1>com.txt         # Détection port COM
set /p myCOM=<./com.txt          # Lecture numéro port
if [%myCOM%]==[] listcom CH9102 1>com.txt  # Fallback CH9102
echo seid COM%myCOM%/key > cardconfig.txt
echo stimeout 1000  >>     cardconfig.txt
echo sbaud   115200 >>     cardconfig.txt
echo sflush   1 >>         cardconfig.txt
echo tx 1 >>               cardconfig.txt
echo smode 100 >>          cardconfig.txt
echo cmd dtr 0 >>          cardconfig.txt
echo cmd rts 1 >>          cardconfig.txt
echo cmd wait 10 >>        cardconfig.txt
echo cmd rts 0 >>          cardconfig.txt
echo cmd wait 1000 >>      cardconfig.txt
echo cmd on >>             cardconfig.txt
echo stimeout 15000 >>     cardconfig.txt
```

**Pattern 4: Installation Factory Complète**
```batch
@echo off
set PSK=0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F20
call makecardconfig.bat          # Configuration COM
gpshell delete_All_SCP03.txt     # Suppression anciennes applets
gpshell helloInstallSCP03_im_factory_2.txt  # Installation
echo press ENTER for setting TLS-IM keys
PAUSE
copy /b .\prefix.txt + %PSK% + .\suffix.txt .\perso.txt
copy perso.txt scriptdefault.txt
reader                           # Personnalisation
del scriptdefault.txt
PAUSE
```

**Pattern 5: Test TLS avec OpenSSL**
```batch
@echo off
openssl s_client -tls1_3 ^
    -connect 192.168.1.49:444 ^
    -servername key1.com ^
    -groups P-256 ^
    -cipher DHE ^
    -ciphersuites TLS_AES_128_CCM_SHA256 ^
    -debug -tlsextdebug -msg -no_ticket ^
    -psk 0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F20
PAUSE
```

**Pattern 6: Client Keystore TLS-IM**
```batch
listcom.exe Leonardo 1>mycom.txt
set /p myServer=<%Rep%/myserver.txt
set /p myPort=<%Rep%/myport.txt
set /p Key=<%Rep%/mykey.txt
client -H com%MyMfa% -H pin0000 -H im -H tc ^
    -H #c0%Key% -H #X0%Key%%pk% ^
    -H #p0%Key% -H #s0%Key%1234 -H #! ^
    -S %MySn% -s -p %myPort% -h %myServer% ^
    -l TLS13-AES128-CCM-SHA256
```

**Pattern 7: Console RACS (IoSE)**
```batch
@echo off
console 127.0.0.1:7777
```

### 13.3 Scripts par Catégorie

#### FACTORY (Initialisation Usine)
| Script | Description | Action |
|--------|-------------|--------|
| `FACTORY_All.bat` | Init complète | Flash ESP32 + Install applets |
| `FACTORY_GP.bat` | Applets seulement | gpshell install |

#### USB Serial (SELoaderSerial)
| Script | Description | Action |
|--------|-------------|--------|
| `USB_GP_install.bat` | Installation applets | gpshell helloInstallSCP03 |
| `USB_GP_delete.bat` | Suppression applets | gpshell delete_All_SCP03 |
| `USB_GP_list.bat` | Liste applets | gpshell listSCP03 |
| `makecardconfig.bat` | Config COM auto | Détecte CP210x/CH9102 |

#### Wi-Fi (SELoader_NET)
| Script | Description | Action |
|--------|-------------|--------|
| `SSL_openssl.bat` | Test TLS 1.3 OpenSSL | openssl s_client |
| `SSL_wolfssl.bat` | Test TLS 1.3 wolfSSL | wolfssl client |
| `SSL_wolfssl_MFA.bat` | Test TLS + MFA | wolfssl + auth hardware |

#### TLS-IM (Personnalisation)
| Script | Description | Action |
|--------|-------------|--------|
| `GP_Install_Factory_2.bat` | Install + Perso | gpshell + reader |
| `scriptPSK.bat` | Configuration PSK | Personnalisation clés |
| `scriptPSK2.bat` | Configuration PSK alt | Variante perso |

#### IoSE (Serveur/Client)
| Script | Description | Action |
|--------|-------------|--------|
| `IOSE_Openssl.bat` | Client OpenSSL IoSE | openssl via 127.0.0.1:8888 |
| `IOSE_RACS_Console.bat` | Console RACS | console 127.0.0.1:7777 |
| `IOSE_RACS_List.bat` | Liste applets IoSE | gpshell list via IoSE |
| `IOSE_GP_install.bat` | Install via IoSE | gpshell via réseau |
| `IOSE_GP_delete.bat` | Delete via IoSE | gpshell delete via réseau |

#### Keystore Ethereum
| Script | Description | Action |
|--------|-------------|--------|
| `ETH_Transaction_Send.bat` | Envoi transaction | keystore → blockchain |
| `ETH_Transaction_View.bat` | Vue transaction | Affiche détails tx |
| `ETH_NET_Make_Transaction.bat` | Création tx NET | Via Wi-Fi |
| `ETH_BLT_Make_Transaction.bat` | Création tx Bluetooth | Via RFCOMM |
| `KEYSTORE_NET_Load_Key.bat` | Charge clé NET | Import dans HSM |
| `Make_Key_Keystore3.bat` | Génération clé | client -H #c0 #X0 |

#### Certificats
| Script | Description | Action |
|--------|-------------|--------|
| `SE_NET_Cert_MFA.bat` | Cert + MFA | Certification avec auth |
| `SE_NET_Cert_SC.bat` | Cert SmartCard | Via lecteur SC |
| `SE_NET_auth_MFA.bat` | Auth MFA | Authentification MFA |
| `SE_NET_auth_SC.bat` | Auth SmartCard | Auth via SC |

### 13.4 Outils Utilisés

**gpshell** (GlobalPlatform Shell):
- Gestion applets JavaCard
- Protocoles: SCP02, SCP03
- Fichiers .txt contiennent les commandes GP

**reader** (Lecteur APDU):
- Envoie script APDU vers SE
- Lit `scriptdefault.txt`
- Perso et configuration

**listcom** (Détection COM):
- Détecte ports série
- Paramètres: CP210x, CH9102, Leonardo
- Sortie: numéro port uniquement

**client** (Client TLS-IM):
- Connexion TLS 1.3 PSK
- Options -H pour commandes HSM
- Commandes: im, tc, pin, #c0, #X0, #p0, #s0

**console** (Console RACS):
- Interface administrative IoSE
- Connexion TCP vers serveur RACS
- Gestion à distance

**openssl/wolfssl**:
- Tests connexion TLS 1.3
- Cipher: TLS_AES_128_CCM_SHA256
- Mode PSK obligatoire

### 13.5 Configuration cardconfig.txt

**Format complet:**
```
seid COM<N>/key       # Port série et identifiant
stimeout 1000         # Timeout lecture (ms)
stxtimeout 0          # Timeout transmission (ms)
sbaud 115200          # Baudrate
sflush 1              # Flush buffer activé
tx 1                  # Mode transmission
smode 100             # Mode série (100=standard)
cmd dtr 0             # Signal DTR bas
cmd rts 1             # Signal RTS haut
cmd wait 10           # Attente 10ms
cmd rts 0             # Signal RTS bas
cmd wait 1000         # Attente 1000ms (reset)
cmd null              # Commandes vides (réservé)
cmd null
cmd null
cmd on                # Active Secure Element
stimeout 15000        # Timeout étendu pour ATR
```

**Séquence reset:**
1. DTR=0, RTS=1 → Prépare reset
2. Wait 10ms
3. RTS=0 → Déclenche reset
4. Wait 1000ms → Attend boot ESP32
5. "on" → Active SE
6. Timeout 15s → Attend ATR

### 13.6 PSK par Défaut

**Valeur:**
```
0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F20
```

**Utilisation:**
- 32 bytes (256 bits)
- Format: hex string sans séparateurs
- TLS 1.3 PSK mode avec AES128-CCM-SHA256
- Doit être changé en production

### 13.7 Commandes Client HSM (-H)

| Commande | Description |
|----------|-------------|
| `com<N>` | Port COM à utiliser |
| `pin<XXXX>` | Code PIN (ex: pin0000) |
| `im` | Mode TLS-IM |
| `tc` | Test Connect |
| `#c0<KEY>` | Configure clé KEY |
| `#X0<KEY><pk>` | Configure clé + public |
| `#p0<KEY>` | Prépare signature |
| `#s0<KEY><data>` | Signe data avec KEY |
| `#!` | Exécute commande |

### 13.8 Ports Réseau Standards

| Port | Service | Description |
|------|---------|-------------|
| 444 | TLS-IM | Connexion TLS 1.3 PSK |
| 7777 | RACS Console | Administration IoSE |
| 8888 | OpenSSL Test | Test via localhost |

### 13.9 Chips Serial Supportés

| Chip | Usage |
|------|-------|
| CP210x | Silicon Labs (standard) |
| CH9102 | WCH (compatible) |
| CH340 | WCH (alternative) |
| Leonardo | Arduino (MFA) |

---

## 14. RÉSUMÉ ESSENTIEL

### Configuration Rapide USB

1. **Détecter port:**
   ```bash
   ls /dev/ttyUSB*   # Linux
   listcom CP210x    # Windows
   ```

2. **Tester connexion:**
   ```bash
   echo -e "off\r" > /dev/ttyUSB0
   echo -e "on\r" > /dev/ttyUSB0
   ```

3. **SELECT applet CC:**
   ```
   A 00A4040006010203040601
   ```

4. **VERIFY PIN (00000000):**
   ```
   A 00200001083030303030303030
   ```

### Configuration Wi-Fi TLS

1. **IP HSM:** 192.168.1.49 (configurable)
2. **Port:** 444
3. **Cipher:** TLS_AES_128_CCM_SHA256
4. **PSK:** 32 bytes hex

### AIDs des Applets

| Applet | AID |
|--------|-----|
| CC (Crypto Currency) | 010203040601 |
| TLS-SE | 010203040500 |
| TLS-IM | 010203040501 |
| TLS-IM0 | 010203040502 |

### Commandes APDU Essentielles

| Action | APDU |
|--------|------|
| SELECT CC | 00A4040006010203040601 |
| VERIFY PIN | 00200001083030303030303030 |
| READ @0x0100 (32B) | 00D001002000 |
| WRITE @0x0100 (32B) | 00D6010020<data> |

### Délais Critiques

| Opération | Délai Minimum |
|-----------|---------------|
| Après OFF | 200ms |
| Après ON | 2500ms (3-5s recommandé) |
| Lecture ATR | 3000ms |
| Avant SELECT | 500ms |
| Après WRITE | 2000ms |

---

## 15. KEY EXCHANGE PROTOCOL (KEP) - SESSION 3

### 15.1 Prérequis pour Détection GCS

**CRITIQUE: Le drone détecte les peers via HEARTBEAT**

Le Key Exchange Protocol (KEP) côté drone ne peut initier un échange de clés que s'il détecte un GCS. Cette détection se fait via les HEARTBEAT MAVLink.

**Conséquence:**
```
❌ GCS connecté mais n'envoie pas de HEARTBEAT
   → Drone ne voit pas de peer
   → Pas d'envoi HSM_WK_EXCHANGE

✅ GCS connecté ET envoie HEARTBEAT (1Hz minimum)
   → Drone détecte sysid=255
   → Envoi HSM_WK_EXCHANGE automatique
```

**Code Python GCS avec heartbeat sender:**
```python
import threading
import time
from pymavlink import mavutil
import mavlink_hsm

def heartbeat_sender(mav):
    """Send heartbeats in background thread"""
    mav_hsm = mavlink_hsm.MAVLink(mav, srcSystem=255, srcComponent=190)
    while True:
        try:
            msg = mav_hsm.heartbeat_encode(
                type=mavlink_hsm.MAV_TYPE_GCS,
                autopilot=mavlink_hsm.MAV_AUTOPILOT_INVALID,
                base_mode=0,
                custom_mode=0,
                system_status=mavlink_hsm.MAV_STATE_ACTIVE
            )
            mav.write(msg.pack(mav_hsm))
            time.sleep(1)  # 1Hz heartbeat
        except:
            break

# Start heartbeat thread AFTER connection
hb_thread = threading.Thread(target=heartbeat_sender, args=(mav,), daemon=True)
hb_thread.start()
```

### 15.2 Remplacement Dialect pymavlink

**OBLIGATOIRE: Remplacer mavutil.mavlink pour parser messages HSM**

Les messages custom HSM (12000, 12001, 12002) ne sont pas reconnus par le dialect standard MAVLink. Il faut remplacer le dialect par notre version générée.

**Pattern correct:**
```python
import sys
sys.path.insert(0, '/path/to/Tools/hsm')
from pymavlink import mavutil
import mavlink_hsm  # Notre dialect avec HSM_* messages

# CRITIQUE: Remplacer AVANT connexion
mavutil.mavlink = mavlink_hsm

# Maintenant les messages HSM sont parsés
mav = mavutil.mavlink_connection('tcp:127.0.0.1:5760')
```

**Sans remplacement:**
```
>>> BAD_DATA
>>> BAD_DATA
>>> UNKNOWN_12000
```

**Avec remplacement:**
```
>>> HSM_WK_EXCHANGE from sysid=1
>>> HSM_DEK_EXCHANGE from sysid=1
>>> HSM_KEY_ACK from sysid=1
```

### 15.3 Noms d'Attributs MAVLink HSM

**ERREUR COURANTE: Mauvais noms d'attributs**

Les noms d'attributs dans le code Python doivent correspondre EXACTEMENT à ceux définis dans le dialect généré.

**HSM_DEK_EXCHANGE (msgid 12001):**
```python
# ❌ INCORRECT - AttributeError
msg.ephemeral_pub   # Wrong!
msg.tag             # Wrong!

# ✅ CORRECT - Noms officiels
msg.ephemeral_pubkey   # 64 bytes
msg.encrypted_dek      # 32 bytes
msg.nonce              # 24 bytes
msg.auth_tag           # 16 bytes
msg.target_system      # 1 byte
msg.target_component   # 1 byte
```

**Vérifier les noms dans mavlink_hsm.py:**
```python
# Chercher la définition de la classe
class MAVLink_hsm_dek_exchange_message(MAVLink_message):
    fieldnames = ['target_system', 'target_component',
                  'ephemeral_pubkey', 'encrypted_dek',
                  'nonce', 'auth_tag']
```

### 15.4 Comportement SITL Pendant Init HSM

**"EOF on TCP socket" spam est NORMAL**

Pendant l'initialisation HSM (~25 secondes en SITL), le socket TCP est bloqué. pymavlink recv_match() peut générer des erreurs répétées.

**Comportement observé:**
```
Connecting to SITL...
Waiting for heartbeat...
Connection on serial port 5760
HSM: === DÉBUT INIT HSM (SITL BLOQUANT) ===
EOF on TCP socket
EOF on TCP socket
EOF on TCP socket
[... ~25 secondes ...]
HSM: === FIN INIT HSM ===
HEARTBEAT from sysid=1
```

**Solution: Attendre patiemment avec timeout long**
```python
def wait_heartbeat_patient(mav, timeout=90):
    """Wait for heartbeat during HSM init"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            msg = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
            if msg and msg.get_srcSystem() == 1:
                return msg
        except:
            pass  # Ignore errors during init

        elapsed = int(time.time() - start)
        if elapsed % 10 == 0:
            print(f"  Still waiting... ({elapsed}s)")
    return None
```

### 15.5 Séquence Key Exchange Complète

**Flow bidirectionnel validé (Session 3):**

```
DRONE (sysid=1)                          GCS (sysid=255)
──────────────                           ──────────────
      │                                        │
      │  ◄──────── HEARTBEAT ─────────────── │
      │          (détection peer)             │
      │                                        │
      │  ─────── HSM_WK_EXCHANGE ──────────► │
      │     wk_public[64], timestamp          │
      │                                        │
      │  ◄────── HSM_WK_EXCHANGE ───────────  │
      │     wk_public[64], timestamp          │
      │                                        │
      │  ◄──────── HSM_KEY_ACK ─────────────  │
      │     status=SUCCESS, phase=WK_RECEIVED │
      │                                        │
      │  ─────── HSM_DEK_EXCHANGE ─────────► │
      │     ephemeral[64], encrypted[32],     │
      │     nonce[24], auth_tag[16]           │
      │                                        │
      │  ◄──────── HSM_KEY_ACK ─────────────  │
      │     status=SUCCESS, phase=DEK_RECEIVED│
      │                                        │
      ▼                                        ▼
   peer_deks[255] = DEK_GCS          peer_deks[1] = DEK_DRONE
   (peut décrypter msgs GCS)         (peut décrypter msgs drone)
```

**Timing typique:**
- T+0s: Connexion GCS
- T+25s: Fin init HSM, premier HEARTBEAT reçu
- T+26s: WK_EXCHANGE bidirectionnel
- T+27s: DEK_EXCHANGE bidirectionnel
- T+28s: KEY EXCHANGE COMPLETE

### 15.6 Commande de Test Session 3

**Test complet key exchange avec gcs_kep_client.py:**

```bash
# 1. Démarrer SITL avec HSM (terminal 1)
stdbuf -oL ./build/sitl/bin/arducopter \
    --model + \
    --serial1=uart:/dev/ttyUSB0:115200 \
    > /tmp/sitl_hsm.log 2>&1 &

# 2. Attendre init HSM (~25s)
sleep 30

# 3. Lancer GCS client (terminal 2)
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 75

# Résultat attendu:
# HSM_WK_EXCHANGE from sysid=1
# HSM_KEY_ACK from sysid=1 (WK_RECEIVED)
# HSM_DEK_EXCHANGE from sysid=1
# HSM_KEY_ACK from sysid=1 (DEK_RECEIVED)
# *** KEY EXCHANGE COMPLETE! ***
# Decrypted 45 messages
```

**Options gcs_kep_client.py:**
- `--no-hsm`: GCS simule HSM en mémoire (pas de /dev/ttyUSB0 requis)
- `--hsm`: GCS utilise vrai HSM via UART
- `--timeout N`: Timeout en secondes pour heartbeat initial

### 15.7 Troubleshooting KEP

| Symptôme | Cause | Solution |
|----------|-------|----------|
| Pas de HSM_WK_EXCHANGE | GCS n'envoie pas HEARTBEAT | Ajouter thread heartbeat_sender |
| UNKNOWN_12000 | Dialect pas remplacé | `mavutil.mavlink = mavlink_hsm` |
| AttributeError: ephemeral_pub | Mauvais nom attribut | Utiliser `ephemeral_pubkey` |
| AttributeError: tag | Mauvais nom attribut | Utiliser `auth_tag` |
| EOF on TCP socket x100 | Init HSM en cours | Attendre ~25s, c'est normal |
| Timeout heartbeat | Init HSM trop longue | Augmenter timeout à 75-90s |
| KEY_ACK mais pas WK response | Bug send_wk_exchange | Vérifier payload_len dans send |

---

**FIN DU DOCUMENT HSM SKILLS**

Ce document contient toutes les connaissances critiques pour travailler avec le HSM LeMonolith, incluant protocoles, timings, scripts de gestion, dépannage, et patterns éprouvés.
