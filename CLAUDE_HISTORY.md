# CLAUDE_HISTORY.md - Sessions Archivées

Archive des sessions de développement HSM. Consulter uniquement si besoin de détails historiques.

---

## Session 1-9: Pixhawk Mock HSM Development (2026-01-25 → 2026-01-27)

### Session 1: Découverte du problème WK

```
✅ Firmware flashé sur Pixhawk5X avec Mock HSM
✅ GCS connecté avec Real HSM (/dev/ttyUSB0)
✅ MAVLink connecté au Pixhawk (/dev/ttyACM0)
✅ HEARTBEAT reçu du Pixhawk (sysid=1)
✅ WK_EXCHANGE envoyé par GCS → Pixhawk
✅ KEY_ACK reçu du Pixhawk (status=SUCCESS, phase=WK_RECEIVED)
❌ Pixhawk ne renvoie PAS son WK_EXCHANGE au GCS
```

### Session 2: Crash uECC découvert et contourné

**Problème critique:** `uECC_compute_public_key()` crash sur ARM Cortex-M7

**Diagnostic:**
- HSM disabled: ✅ stable
- HSM + Mock init: ✅ stable
- \+ KeyOrchestrator: ❌ CRASH
- \+ RNG + HKDF: ✅ stable
- \+ uECC: ❌ CRASH

**Workaround:** Pseudo-PRNG au lieu de uECC (non sécurisé, test uniquement)

### Session 3: Key Exchange SITL - COMPLET ✅

**Problèmes résolus:**
1. `mavutil.mavlink` non remplacé par dialect HSM → Fix: `mavutil.mavlink = mavlink_hsm`
2. `msg.ephemeral_pub` au lieu de `msg.ephemeral_pubkey` → Fix attribut
3. GCS n'envoyait pas de HEARTBEAT → Fix: ajout heartbeats

**Résultat:** WK + DEK bidirectionnel, 45 messages déchiffrés OK

### Session 4: Pixhawk KEP - COMPLET ✅

**Problème:** Clé WK invalide (pseudo-PRNG ≠ point P-256 valide)

**Solution temporaire:** Clés de test P-256 hardcodées + ECIES bypass

**Fonctions uECC qui crashent sur ARM:**
- `uECC_compute_public_key()`
- `uECC_make_key()`
- `uECC_shared_secret()`

### Session 5: Fix uECC - REAL CRYPTO WORKS! ✅

**Cause root:** `uECC_config.h` forçait x86_64 même sur ARM!
```cpp
// AVANT (FAUX):
#define uECC_PLATFORM 2  /* uECC_x86_64 */
#define uECC_WORD_SIZE 8

// APRÈS (CORRECT):
#if defined(__x86_64__)
    #define uECC_PLATFORM uECC_x86_64
    #define uECC_WORD_SIZE 8
#elif defined(__arm__)
    #define uECC_PLATFORM uECC_arm_thumb2
    #define uECC_WORD_SIZE 4
#endif
```

**Commit:** `75656daedf` - Fix uECC crash on ARM Cortex-M7

### Session 6: Full Key Exchange Working! ✅

**Problème:** `uECC_make_key()` retournait 0 - RNG non configuré dans KEP

**Solutions:**
1. RNG fix: `uECC_set_rng()` dans `ecies_encrypt_dek()`
2. Peer reset: 30s timeout pour re-exchange sans reboot
3. GCS heartbeats: Pixhawk détecte maintenant le GCS

**Commit:** `2c13981c60` - Fix key exchange: RNG + peer reset + GCS heartbeats

### Session 7: Pi Zero Bridge Architecture

**Découverte:** Pixhawk5X n'a aucun port USB Host → HSM ESP32 (USB device) incompatible

**Solution:** Raspberry Pi Zero comme pont
```
Pixhawk TELEM1 (TTL) ←→ Pi Zero (GPIO UART + USB OTG) ←→ HSM (USB-C)
```

**Script créé:** `Tools/hsm/pi_zero_bridge.py`

### Session 9: Test Pixhawk Mock HSM - SUCCÈS! ✅

**Architecture finale testée:**
- Pixhawk5X avec Mock HSM (RAM)
- GCS avec Real HSM (/dev/ttyUSB0)

**Commande:**
```bash
python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 --timeout 120
```

**Résultat:** state=COMPLETE, 42 messages déchiffrés OK

---

## Session 11 - Gazebo + HSM ✅

**Plugin:** `~/ardupilot_gazebo/build/libArduPilotPlugin.so`

```bash
# Terminal 1: Gazebo
export GZ_SIM_SYSTEM_PLUGIN_PATH=$HOME/ardupilot_gazebo/build:$GZ_SIM_SYSTEM_PLUGIN_PATH
export GZ_SIM_RESOURCE_PATH=$HOME/ardupilot_gazebo/models:$HOME/ardupilot_gazebo/worlds:$GZ_SIM_RESOURCE_PATH
gz sim -v4 -r iris_runway.sdf

# Terminal 2: SITL
python3 Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --map --console
```

---

## Session 12 - Chiffrement Bidirectionnel ✅

| Direction | Status |
|-----------|--------|
| Drone → GCS | ✅ Chiffré |
| GCS → Drone | ✅ Chiffré via `--interactive` |

```bash
python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 -i
# Commandes: arm, disarm, takeoff N, land, rtl, guided, loiter, status, quit
```

---

## Session 13 - Dual HSM + Gazebo + Wireshark ✅

Configuration 2 HSM physiques: drone (/dev/ttyUSB0) + GCS (/dev/ttyUSB1)

```bash
# Wireshark
wireshark -k -i lo -f "port 5760 or port 5761 or port 14550"

# Mission chiffrée
python3 Tools/hsm/encrypted_mission.py --hsm /dev/ttyUSB1 --mavlink tcp:127.0.0.1:5760
```

Résultat: 39+ messages déchiffrés, 7 commandes TX chiffrées.

---

## Session 14 - Bugs Corrigés

### Bug 1: find_peer() wildcard compid
**Fix:** `KeyExchangeProtocol.cpp:95` - compid=0 = wildcard "any"

### Bug 2: CRC Collision
**Fix:** `GCS_Common.cpp:1954` - Déchiffrer même avec CRC OK si peer a DEK

### Plaintext Messages Fix
```cpp
const bool is_plaintext_msg = (msg.msgid == MAVLINK_MSG_ID_HEARTBEAT ||
                               msg.msgid == MAVLINK_MSG_ID_HSM_WK_EXCHANGE ||
                               msg.msgid == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE ||
                               msg.msgid == MAVLINK_MSG_ID_HSM_KEY_ACK);
```

### Leçons
1. CRC MAVLink peut coïncider avec payload chiffré
2. compid=0 doit être wildcard
3. SITL blocking init problématique
4. HSM nécessite 3x reset off/on

---

## Session 15 - Tests Phase A: 47/47 PASSED ✅

| Phase | Tests | Description |
|-------|-------|-------------|
| A1 | 6/6 | Communication (OFF/ON/SELECT/PIN) |
| A2 | 7/7 | EEPROM (WRITE/READ) |
| A3 | 7/7 | P-256 Asymétrique |
| A4 | 9/9 | XChaCha20-Poly1305 |
| A5 | 9/9 | Hiérarchie MK→WK→DEK |
| A6 | 9/9 | Stress (2.9 ops/sec) |

### Performance HSM
| Opération | Latence |
|-----------|---------|
| READ | ~350ms |
| WRITE | ~550ms |
| VERIFY PIN | ~550ms |

### Découverte: sim_vehicle.py = MAVProxy au milieu
→ Voit BAD_CRC → Messages rejetés!
→ Solution: SITL direct ou module HSM

---

## Session 16 - Tests Phase B: 39/39 PASSED ✅

| Phase | Tests | Description |
|-------|-------|-------------|
| B1 | 6/6 | Import module |
| B2 | 6/6 | ChaCha20 |
| B3 | 6/6 | HSM init |
| B4 | 6/6 | KEP |
| B5 | 7/7 | SITL integration |
| B6 | 8/8 | Module simulation |

### SITL vs Pixhawk
- SITL: Mono-thread, HSM init bloque TCP
- Pixhawk: Scheduler async, tout fonctionne

---

## Session 17 - Debug Mock HSM

### Debug Printf ajoutés
`libraries/AP_Vehicle/AP_Vehicle.cpp:328-350`
```cpp
printf("HSM_DEBUG: init_monolith() SUCCESS\n");
printf("HSM_DEBUG: init_mission_keys() SUCCESS\n");
printf("HSM_DEBUG: KEP init SUCCESS!\n");
```

### Fix mavproxy_hsm.py
```python
# Avant (ne marche pas avec symlink)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Après
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
```

---

## Session 18 - SITL Mock + MAVProxy Real HSM

### Problème: GCS HSM init bloque MAVProxy
1. MAVProxy connecte TCP
2. `hsm init /dev/ttyUSB0` bloque 11-22s
3. SITL timeout → "EOF on TCP socket"

### Clés générées (quand ça marche)
```
MK: 05C25124... @0x0100
WK: 05325DE8... @0x0120
DEK: D0563CEF... @0x0140
```

### HSM Reset agressif
```python
for i in range(3):
    s.write(b'off\r\n'); time.sleep(1)
    s.write(b'on\r\n'); time.sleep(5)
s.write(b'A 00A4040006010203040601\r\n')
```

---

## Session 19 - Architecture Complète

### Tests: 86/86 PASSED ✅
- Phase A: 47/47 (Hardware HSM)
- Phase B: 39/39 (Intégration)

### Configurations Testées
| Config | Status |
|--------|--------|
| Pixhawk5X + Mock HSM | ✅ |
| SITL + Mock HSM | ✅ |
| SITL + Real HSM | ⚠️ TCP timeout |
| Dual Real HSM + Gazebo | ✅ |

---

## Session 20 - MAVProxy Module Fix

### Fix: Chargement module
```bash
ln -sf /path/to/mavproxy_hsm.py $(python3 -c "import MAVProxy.modules; print(MAVProxy.modules.__path__[0])")/mavproxy_hsm.py
```

### Pourquoi timeout ne marche pas
Thread GELÉ pendant init HSM → ne peut pas vérifier timeout

### Timing mesuré
| Test | Temps |
|------|-------|
| Nouvelles clés | 24.3s |
| Clés existantes | 11.6s |
| Hardware init | ~10s (incompressible) |

→ Seule solution: Thread séparé

---

---

## Session 21 - Analyse CRC vs Encryption (2026-02-04)

### Objectif
Analyser et résoudre le problème de CRC invalide causé par le chiffrement du payload MAVLink.

### Problème Identifié

**Séquence actuelle (problématique):**
```
TX: CRC = crc(PLAINTEXT) → Encrypt(payload) → Send [Header][Ciphertext][CRC_plaintext]
RX: Receive → CRC_calculé = crc(CIPHERTEXT) → CRC_calculé ≠ CRC_reçu → BAD_CRC!
```

**Code analysé:**
- `mavlink_helpers.h:365-369` - CRC calculé sur plaintext AVANT envoi
- `GCS_MAVLink.cpp:162-282` - Chiffrement dans `comm_send_buffer()` buffer[1]
- `GCS_Common.cpp:1939-1991` - Interception BAD_CRC pour décryption

**Ordre des opérations découvert:**
1. MAVLink calcule CRC sur payload PLAINTEXT
2. `_mavlink_send_uart()` appelle `comm_send_buffer()` 3-4 fois:
   - buffer[0] = Header (envoyé en clair)
   - buffer[1] = Payload → **CHIFFRÉ ICI** dans `comm_send_buffer()`
   - buffer[2] = CRC (calculé sur plaintext, déjà obsolète!)
   - buffer[3] = Signature (optionnel)
3. RX calcule CRC sur ciphertext → mismatch → BAD_CRC

### Solutions Analysées

| Option | Description | Verdict |
|--------|-------------|---------|
| A | Statu quo (intercepter BAD_CRC) | ❌ Hacky, pas d'intégrité |
| B | Recalculer CRC dans buffer[2] | ✅ **RECOMMANDÉE** |
| C | Modifier mavlink_helpers.h | ❌ Intrusif, maintenance difficile |
| D | Ajouter MAC Poly1305 | ❌ Change taille message |

### Solution Retenue: Option B

**Principe:** Recalculer le CRC sur le ciphertext dans `comm_send_buffer()` pour buffer[2]

```cpp
// Variables statiques par channel
static uint8_t stored_header[MAVLINK_COMM_NUM_BUFFERS][10];
static uint8_t stored_ciphertext[MAVLINK_COMM_NUM_BUFFERS][256];
static uint8_t stored_ciphertext_len[MAVLINK_COMM_NUM_BUFFERS];
static bool was_encrypted[MAVLINK_COMM_NUM_BUFFERS];

// buffer[0]: Stocker header
// buffer[1]: Chiffrer + stocker ciphertext
// buffer[2]: Recalculer CRC = crc(header + ciphertext + crc_extra)
```

**Avantages:**
- ✅ CRC valide côté RX (plus de BAD_CRC)
- ✅ Intégrité vérifiable
- ✅ Modification localisée (1 seul fichier)
- ✅ Utilise fonctions MAVLink existantes
- ✅ RX simplifié (décryption après CRC OK)

**Coût RAM:** ~266 bytes par channel (~1KB pour 4 channels SITL)

### Fichiers à Modifier (Session 22)

| Fichier | Modification |
|---------|--------------|
| `GCS_MAVLink.cpp` | Ajouter stockage header/ciphertext + recalcul CRC buffer[2] |
| `GCS_Common.cpp` | Simplifier RX: décrypter après CRC OK (plus de BAD_CRC) |

### Fonctions MAVLink Utilisables

```cpp
#include "checksum.h"  // Déjà inclus via mavlink_helpers.h

crc_init(&crc);                          // Init CRC à 0xFFFF
crc_accumulate(byte, &crc);              // Ajoute 1 byte
crc_accumulate_buffer(&crc, buf, len);   // Ajoute buffer
mavlink_get_msg_entry(msgid)->crc_extra; // CRC extra par msgid
```

### Prochaine Session (22)
- Implémenter Option B dans `GCS_MAVLink.cpp`
- Modifier RX dans `GCS_Common.cpp`
- Tester SITL + GCS

---

## Session 22 - CRC Fix Implementation (2026-02-04)

### Objectif
Implémenter la Solution B (recalcul CRC sur ciphertext) analysée en Session 21.

### Implémentation

#### 1. GCS_MAVLink.cpp - CRC Recalculation

**Includes ajoutés:**
```cpp
#include "include/mavlink/v2.0/checksum.h"
#include "include/mavlink/v2.0/mavlink_types.h"
```

**Variables statiques:**
```cpp
static uint8_t stored_header[MAVLINK_COMM_NUM_BUFFERS][10];
static uint8_t stored_ciphertext[MAVLINK_COMM_NUM_BUFFERS][256];
static uint8_t stored_ciphertext_len[MAVLINK_COMM_NUM_BUFFERS];
static bool was_encrypted[MAVLINK_COMM_NUM_BUFFERS] = {false};
```

**Logique comm_send_buffer():**
- **buffer[0]**: Stocker header complet (10 bytes), reset `was_encrypted = false`
- **buffer[1]**: Si encryption active, chiffrer payload, stocker ciphertext, `was_encrypted = true`
- **buffer[2]**: Si `was_encrypted`, recalculer CRC:
  ```cpp
  crc_init(&crc);
  // CRC header bytes 1-9 (skip STX)
  for (int i = 1; i < 10; i++) crc_accumulate(stored_header[chan][i], &crc);
  // CRC ciphertext
  crc_accumulate_buffer(&crc, stored_ciphertext[chan], stored_ciphertext_len[chan]);
  // CRC extra
  crc_accumulate(mavlink_get_msg_entry(msgid)->crc_extra, &crc);
  ```

#### 2. Debug Output Fix - SITL Mock Mode

**Problème découvert:** En SITL, `hal.console->printf()` écrit sur le port TCP MAVLink (5760), corrompant le stream binaire.

**Solution:** Macros pour désactiver le debug verbose en SITL Mock:

```cpp
// AP_HSM.cpp, KeyOrchestrator.cpp, KeyExchangeProtocol.cpp, DualDekEngine.cpp
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
  #if AP_HSM_MOCK_ENABLED
    #define XX_DEBUG(fmt, ...) do { /* disabled */ } while(0)
  #else
    #define XX_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
  #endif
#else
  #define XX_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
#endif
```

**Fichiers modifiés:**
- `AP_HSM.cpp` → `MOCK_DEBUG()`
- `KeyOrchestrator.cpp` → `KO_DEBUG()`
- `KeyExchangeProtocol.cpp` → `KEP_DEBUG()`
- `DualDekEngine.cpp` → `DDE_DEBUG()`

### Tests

**Commande:**
```bash
./build/sitl/bin/arducopter --model + &
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 30
```

**Résultats:**
```
✅ Connected to system 1 component 0
✅ WK public initialized
✅ Received HSM_WK_EXCHANGE from sysid=1
✅ Sent HSM_WK_EXCHANGE, HSM_DEK_EXCHANGE, HSM_KEY_ACK
✅ Received HSM_DEK_EXCHANGE from sysid=1
✅ KEY EXCHANGE COMPLETE!
✅ Peer 1: state=COMPLETE wk_recv=True dek_recv=True
```

### Résumé Session 22

| Tâche | Status |
|-------|--------|
| CRC recalculation TX | ✅ Implémenté |
| Debug output fix SITL | ✅ Corrigé |
| Build SITL | ✅ Compile |
| Key Exchange test | ✅ COMPLETE |

### Notes

- Le GCS client montre "Decrypted OK: 0" car la logique RX décrypte après BAD_CRC, pas après CRC OK
- Future work: Modifier GCS_Common.cpp pour décrypter après MAVLINK_FRAMING_OK
- L'init banner ArduPilot (`Init ArduCopter...`) pollue encore le début du stream TCP - c'est normal pour SITL

---

**Fin des archives - Sessions 11-22**
