# CLAUDE.md - Contexte Projet HSM ArduPilot v2.0

## Vue d'Ensemble

Projet d'intégration cryptographique HSM LeMonolith v0.6 avec ArduPilot pour sécuriser les communications MAVLink entre drones.

**Architecture v2.0** - Hiérarchie de clés à 3 niveaux avec protocole d'échange bidirectionnel.

---

## Décisions Techniques (Q&A 2026-01-24)

| Question | Réponse |
|----------|---------|
| Rétro-compatibilité v1? | **NON** - Remplace totalement l'existant |
| Nombre de drones | **2-5 drones** |
| Topologie réseau | **Mesh**, test initial: 1 drone + GCS |
| Master Key génération | **Au boot** (init mission) |
| Master Key unique? | **OUI** - chaque drone a sa propre MK |
| Wrapper Key durée | **Par mission** (3 clés générées une fois) |
| Nonce ChaCha20 | **Random 12 bytes** |
| Rotation DEK | **Par mission** (pas en vol) |
| Messages en transit | **HEARTBEAT en clair**, autres attendent DEK |
| Transport MAVLink | **Nouveau message custom** |
| Authentification | **Trust-on-first-use** (pas de certificats) |
| Découverte drones | **Via HEARTBEAT** |
| PFS (Perfect Forward Secrecy) | **OUI** - ECDH éphémère + rotation WK |
| Stockage HSM | **MK + WK_priv wrappée + DEK wrappée** |
| Langage | **C++ pur** |

---

## Architecture Cryptographique v2.0

```
╔══════════════════════════════════════════════════════════════════╗
║  NIVEAU 1: MASTER KEY (MK)                                        ║
║  ├── Type: ChaCha20-256 bits (32 bytes)                           ║
║  ├── Génération: Random au boot (hal.util->get_random_vals)       ║
║  ├── Stockage: HSM exclusif @0x0100                               ║
║  └── UNIQUE par drone                                             ║
║                                                                    ║
║          │ HKDF-SHA256 ("WrapperKey-P256-v1")                     ║
║          ▼                                                         ║
║                                                                    ║
║  NIVEAU 2: WRAPPER KEY (WK)                                        ║
║  ├── Type: secp256r1 (P-256) asymétrique                          ║
║  ├── WK_private: Dérivée de MK via HKDF                           ║
║  ├── WK_public: Calculée depuis WK_private (micro-ecc)            ║
║  ├── Stockage: WK_priv wrappée HSM @0x0120, tag @0x0160           ║
║  └── Usage: Échange sécurisé des DEK (ECIES)                      ║
║                                                                    ║
║          │ ECIES (ChaCha20-Poly1305)                              ║
║          ▼                                                         ║
║                                                                    ║
║  NIVEAU 3: DATA ENCRYPTION KEY (DEK)                              ║
║  ├── Type: ChaCha20-256 bits (32 bytes)                           ║
║  ├── MY_DEK: Pour chiffrer MES messages sortants                  ║
║  ├── PEER_DEKs: DEKs reçues pour déchiffrer messages entrants     ║
║  ├── Génération: Random par drone                                 ║
║  └── Stockage: MY_DEK wrappée HSM @0x0140, tag @0x0180            ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Stockage HSM LeMonolith

| Offset | Taille | Contenu |
|--------|--------|---------|
| 0x0100 | 32 bytes | Master Key (MK) |
| 0x0120 | 32 bytes | Wrapped WK_private |
| 0x0140 | 32 bytes | Wrapped DEK |
| 0x0160 | 32 bytes | HMAC tag (WK) |
| 0x0180 | 32 bytes | HMAC tag (DEK) |

---

## Commandes APDU HSM (VÉRIFIÉ 2026-01-24)

**⚠️ ATTENTION: L'applet CC utilise des commandes NON-STANDARD!**

| Opération | INS | Format Complet | Exemple |
|-----------|-----|----------------|---------|
| **WRITE** | **D0** | `00 D0 <P1> <P2> <Lc> <data>` | `A 00D0010020<64hex>` |
| READ | B0 | `00 B0 <P1> <P2> <Le>` | `A 00B0010020` |
| VERIFY PIN | 20 | `00 20 00 01 08 <pin_hex>` | `A 00200001083030303030303030` |
| SELECT CC | A4 | `00 A4 04 00 06 <AID>` | `A 00A4040006010203040601` |

**PIN par défaut:** `00000000` (8 chars) = `3030303030303030` (hex)

**Séquence d'init:**
```bash
off                                    # Power OFF (délai 0.3s)
on                                     # Power ON (délai 3.5s, auto-SELECT)
A 00200001083030303030303030           # VERIFY PIN (délai 1.5s)
A 00D0010020<data_64_hex>              # WRITE 32 bytes @0x0100 (délai 3s)
A 00B0010020                           # READ 32 bytes @0x0100 (délai 0.5s)
```

**Délais critiques:**
- Après ON: **3.5 secondes** (ATR + auto-SELECT)
- Après WRITE: **2-3 secondes** (EEPROM)
- Autres commandes: 0.5s

---

## Features v2.0

### Feature 1: Key Orchestrator
- **Fichiers**: `libraries/AP_HSM/KeyOrchestrator.h/.cpp`
- **État**: ✅ **COMPLÉTÉ ET TESTÉ** (2026-01-24)
- **Spec**: `docs/hsm-project/features/FEATURE-1-KEY-ORCHESTRATOR.md`

**Tests validés:**
- ✅ `KeyOrchestrator.h` - 367 lignes, API v2.0 complète
- ✅ `KeyOrchestrator.cpp` - 989 lignes, implémentation complète
- ✅ Test simulation - 31/31 tests passent (`tests/hsm/cpp/test_key_orchestrator_sim.cpp`)
- ✅ Test HSM réel - 18/18 tests passent (`tests/hsm/python/test_key_orchestrator_hsm.py`)
- ✅ Hiérarchie MK→WK→DEK avec wrapping XOR+HMAC fonctionnelle

### Feature 2: Key Exchange Protocol
- **Fichiers**: `libraries/AP_HSM/KeyExchangeProtocol.h/.cpp` (à créer)
- **État**: ❌ Non commencé
- **Spec**: `docs/hsm-project/features/FEATURE-2-KEY-EXCHANGE-PROTOCOL.md`

**Messages MAVLink Custom:**
| ID | Nom | Usage |
|----|-----|-------|
| 12000 | HSM_WK_EXCHANGE | Échange clé publique WK |
| 12001 | HSM_DEK_EXCHANGE | DEK chiffrée ECIES |
| 12002 | HSM_KEY_ACK | Accusé de réception |

### Feature 3: Dual-DEK Engine
- **Fichiers**: `libraries/AP_HSM/DualDekEngine.h/.cpp` (à créer)
- **État**: ❌ Non commencé
- **Spec**: `docs/hsm-project/features/FEATURE-3-DUAL-DEK-COMMUNICATION.md`

**Principe:**
- ENVOI: `payload → ChaCha20-Poly1305(MY_DEK) → ciphertext`
- RÉCEPTION: `ciphertext → ChaCha20-Poly1305(PEER_DEK) → payload`

---

## Algorithmes Cryptographiques

| Usage | Algorithme | Standard |
|-------|------------|----------|
| Master Key | ChaCha20-256 (32 bytes) | - |
| Dérivation WK | HKDF-SHA256 | RFC 5869 |
| Wrapper Key | secp256r1 (P-256) | FIPS 186-4 |
| Échange DEK | ECIES | IEEE 1363a |
| Chiffrement payload | ChaCha20-Poly1305 | RFC 8439 |
| Nonce | Random 12 bytes | - |
| Auth tag | Poly1305 16 bytes | RFC 8439 |

---

## Fichiers Clés du Projet

```
libraries/AP_HSM/
├── AP_HSM.h/.cpp           # Driver HSM LeMonolith
├── KeyOrchestrator.h/.cpp  # Feature 1 (en cours)
├── KeyExchangeProtocol.h/.cpp  # Feature 2 (à créer)
├── DualDekEngine.h/.cpp    # Feature 3 (à créer)
├── uECC.h                  # micro-ecc pour P-256
└── wscript                 # Build config

libraries/AP_Crypto/
├── AP_Crypto.h/.cpp        # SHA-256, HMAC, HKDF

libraries/GCS_MAVLink/
├── GCS.h/.cpp              # À modifier pour Feature 3
├── GCS_Common.cpp          # À modifier pour Feature 3
└── GCS_MAVLink.cpp         # À modifier pour Feature 3

docs/hsm-project/
├── README.md               # Vue d'ensemble v2.0
├── PRD-V2.md               # Product Requirements
└── features/               # Specs détaillées
```

---

## Commandes Build

```bash
# Configuration SITL
./waf configure --board sitl

# Compilation Copter
./waf copter

# Configuration Pixhawk 5X
./waf configure --board Pixhawk5X

# Test avec HSM
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &
mavproxy.py --master=tcp:127.0.0.1:5760 --console
```

---

## Environnement de Test

### Hardware

| Composant | Modèle | Connexion |
|-----------|--------|-----------|
| **Flight Controller** | Pixhawk 5X | USB vers ordinateur |
| **HSM** | LeMonolith v0.6 | USB vers ordinateur (`/dev/ttyUSB0`) |
| **GCS** | MAVProxy | TCP `127.0.0.1:5760` |

### Architecture de Test

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: SITL + HSM réel                                       │
│  ┌──────────────┐    ┌──────────┐    ┌──────────────┐          │
│  │ sim_vehicle  │◄──►│ MAVProxy │    │     HSM      │          │
│  │   (SITL)     │    │  (GCS)   │    │ /dev/ttyUSB0 │          │
│  │ ArduCopter   │    └──────────┘    └──────────────┘          │
│  └──────┬───────┘                           ▲                   │
│         │ SERIAL1 (uart)                    │                   │
│         └───────────────────────────────────┘                   │
├─────────────────────────────────────────────────────────────────┤
│  PHASE 2: Pixhawk 5X + HSM réel                                 │
│  ┌──────────────┐    ┌──────────┐    ┌──────────────┐          │
│  │  Pixhawk 5X  │◄──►│ MAVProxy │    │     HSM      │          │
│  │  (hardware)  │    │  (GCS)   │    │ /dev/ttyUSB0 │          │
│  └──────┬───────┘    └──────────┘    └──────────────┘          │
│         │ TELEM2/SERIAL4                    ▲                   │
│         └───────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

### Workflow de Test par Feature

```
1. Test unitaire C++ (simulation pure)
   └─► tests/hsm/cpp/test_*.cpp

2. Test Python HSM (communication HSM seule)
   └─► tests/hsm/python/test_*.py

3. Test SITL + HSM réel
   └─► sim_vehicle.py + HSM sur /dev/ttyUSB0
   └─► Vérifier logs ArduPilot + MAVProxy

4. Test Hardware Pixhawk 5X + HSM
   └─► Flash firmware sur Pixhawk 5X
   └─► HSM sur /dev/ttyUSB0
   └─► MAVProxy pour monitoring
```

### Commandes de Test SITL

```bash
# Lancer SITL avec HSM sur SERIAL1
cd Tools/autotest
./sim_vehicle.py -v ArduCopter --console --map \
    -A "--serial1=uart:/dev/ttyUSB0:115200"

# Alternative: lancer manuellement
cd /home/samwitwity/Code_Sources/ardupilot_claude
./waf configure --board sitl && ./waf copter
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &
mavproxy.py --master=tcp:127.0.0.1:5760 --console
```

### Ports Série Pixhawk 5X

| Port | Paramètre | Usage recommandé |
|------|-----------|------------------|
| TELEM1 | SERIAL1 | GCS (MAVProxy) |
| TELEM2 | SERIAL2 | HSM LeMonolith |
| GPS1 | SERIAL3 | GPS |
| GPS2 | SERIAL4 | Libre |

---

## Migration Future: Connexion Directe Pixhawk ↔ HSM (UART)

**Note importante (2026-01-24):** Le LeMonolith HSM ne supporte PAS I2C. Interfaces disponibles:
- USB Serial (UART 115200 baud) via CP2102/CH9102
- Wi-Fi (TLS1.3 PSK sur port 444)
- Bluetooth (RFCOMM 9600 baud)

### Configuration Actuelle (HSM sur PC)

```
┌──────────────┐     ┌─────────┐     ┌─────────────┐
│  Pixhawk 5X  │ USB │   PC    │ USB │ HSM         │
│  (ArduPilot) │◄───►│         │◄───►│ /dev/ttyUSB0│
└──────────────┘     └─────────┘     └─────────────┘
```

### Configuration Future (Connexion Directe)

```
┌──────────────┐  UART  ┌─────────────┐
│  Pixhawk 5X  │◄──────►│ HSM         │
│  TELEM2/SER2 │        │ LeMonolith  │
└──────────────┘        └─────────────┘
```

### Checklist de Migration

#### 1. Matériel Requis

| Élément | Détail |
|---------|--------|
| **Câble** | UART 4 fils: TX, RX, GND, (optionnel 5V) |
| **Port Pixhawk** | TELEM2 (recommandé) ou GPS2 |
| **Port HSM** | Connecteur USB → câble UART-TTL |
| **Niveau logique** | 3.3V (Pixhawk) ↔ 3.3V (ESP32) ✓ Compatible |

**Branchement TELEM2 Pixhawk 5X:**
```
Pixhawk TELEM2     HSM LeMonolith (ESP32)
─────────────      ─────────────────────
Pin 2 (TX)    ───► RX (GPIO3)
Pin 3 (RX)    ◄─── TX (GPIO1)
Pin 6 (GND)   ───► GND
```

#### 2. Paramètres ArduPilot

```
# Configurer SERIAL2 pour HSM
SERIAL2_PROTOCOL = -1    # Aucun protocole MAVLink
SERIAL2_BAUD = 115       # 115200 baud
```

#### 3. Modification Code (AP_Vehicle.cpp)

```cpp
// Avant (SITL - HSM sur PC)
hsm.begin(hal.serial(1));  // SERIAL1

// Après (Pixhawk 5X - HSM sur TELEM2)
hsm.begin(hal.serial(2));  // SERIAL2 = TELEM2
```

**Note:** Le driver AP_HSM est déjà compatible UART - aucune autre modification requise.

#### 4. Build et Flash

```bash
# Compiler pour Pixhawk 5X
./waf configure --board Pixhawk5X
./waf copter

# Flash via Mission Planner ou QGC
# Fichier: build/Pixhawk5X/bin/arducopter.apj
```

### Résumé des Changements

| Catégorie | De (Actuel) | Vers (Future) |
|-----------|-------------|---------------|
| **Hardware** | HSM USB → PC | Câble UART TELEM2 → HSM |
| **Paramètres** | - | `SERIAL2_PROTOCOL=-1`, `SERIAL2_BAUD=115` |
| **Code** | `hal.serial(1)` | `hal.serial(2)` |
| **Build** | `--board sitl` | `--board Pixhawk5X` |

---

## Points Techniques Importants

### Dérivation HKDF → P-256 Scalar

```cpp
// Le scalar doit être < ordre de la courbe P-256
// Boucle avec compteur si nécessaire (99.99999% succès au 1er essai)
const char* salt = "ArduPilot-HSM-Salt-v2";
const char* info = "WrapperKey-P256-v1";
```

### Wrapping avec HMAC

```cpp
// XOR avec Master Key + HMAC pour intégrité
wrapped[i] = key[i] ^ master_key[i];
hmac_sha256(master_key, 32, wrapped, 32, tag);
```

### Messages NON Chiffrés

- HEARTBEAT (découverte peers)
- HSM_WK_EXCHANGE
- HSM_DEK_EXCHANGE
- HSM_KEY_ACK

---

## Documentation Complémentaire

- `build_skill/README.md` - Base de connaissances
- `build_skill/hsm_skills.md` - Communication HSM, APDU, timings
- `build_skill/ardupilot_skills.md` - Build waf, UART, SITL

---

**Dernière mise à jour**: 2026-01-24 19:00 - Feature 1 & 2.1 VALIDÉS SITL+HSM

---

## Journal de Session (2026-01-24)

### Corrections effectuées

1. **wscript AP_HSM** - Inclut `KeyOrchestrator.cpp` ✅
2. **AP_Vehicle.cpp** - Corrigé appel `init_mission_keys()` (était `generate_key_hierarchy`)
3. **AP_Vehicle.cpp** - Corrigé noms Stats: `mk_loaded`, `wk_loaded`, `dek_loaded`
4. **AP_HSM.cpp** - Corrigé WRITE APDU `00D6` → `00D0` ✅
5. **KeyOrchestrator.cpp** - Corrigé WRITE APDU `00D6` → `00D0` (ligne 884) ✅

### Test SITL + HSM Réel - SUCCÈS (2026-01-24 19:00)

```
HSM: ✓ Initialisation LeMonolith terminée avec succès
HSM: ✓ Feature 1 complétée avec succès!

KeyOrch: ✓ MISSION INITIALISÉE EN 20725 ms
KeyOrch:   MK  @0x0100
KeyOrch:   WK  @0x0120 (tag @0x0160)
KeyOrch:   DEK @0x0140 (tag @0x0180)

KeyOrch: STATUS:
KeyOrch:   MK:  LOADED
KeyOrch:   WK:  LOADED
KeyOrch:   DEK: LOADED

HSM: ✓ Feature 2.1 complétée avec succès!
HSM:   MK chargee: OUI
HSM:   WK chargee: OUI
HSM:   DEK chargee: OUI
```

### Commande de Test SITL + HSM

```bash
# 1. S'assurer que le HSM est branché sur /dev/ttyUSB0
ls -la /dev/ttyUSB0

# 2. Nettoyer les processus existants
pkill -9 arducopter; pkill -9 mavproxy; fuser -k 5760/tcp

# 3. Compiler (si modifications)
./waf copter

# 4. Lancer SITL avec HSM
./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &

# 5. Connecter MAVProxy (dans un autre terminal)
mavproxy.py --master=tcp:127.0.0.1:5760 --console

# 6. Observer les logs - chercher ces messages de succès:
#    - "HSM: ✓ Feature 1 complétée avec succès!"
#    - "KeyOrch: ✓ MISSION INITIALISÉE"
#    - "HSM: ✓ Feature 2.1 complétée avec succès!"
```

**Temps attendu**: ~25 secondes pour init complète (délais EEPROM HSM)

### État actuel

- **Feature 1 (AP_HSM init)**: ✅ VALIDÉ
- **Feature 2.1 (KeyOrchestrator C++)**: ✅ VALIDÉ (Drone/Pixhawk)
- **Feature 2.1 (GCS_HSM Python)**: ✅ VALIDÉ (GCS/PC) - 2026-01-24
- **Feature 2.2 (Key Exchange Protocol)**: ❌ Non commencé
- **Feature 3 (Dual-DEK Engine)**: ❌ Non commencé

### Module GCS_HSM (Python) - VALIDÉ 2026-01-24

```
Tools/hsm/
├── __init__.py
└── gcs_hsm.py    # KeyOrchestrator équivalent pour GCS
```

**Test réussi:**
```bash
python3 -u Tools/hsm/gcs_hsm.py --port /dev/ttyUSB0 --force-new
```

**Résultat:**
```
✅ MK générée @0x0100
✅ WK dérivée @0x0120 (tag @0x0160)
✅ DEK générée @0x0140 (tag @0x0180)
⏱️  Temps: ~24 secondes
```

**Architecture actuelle (1 HSM):**
```
┌──────────────────┐              ┌──────────────────────────┐
│  DRONE           │   MAVLink    │  GCS (PC)                │
│  ┌────────────┐  │   (clair)    │  ┌────────────────────┐  │
│  │ Pixhawk 5X │◄─┼──────────────┼─►│  MAVProxy          │  │
│  └────────────┘  │              │  └─────────┬──────────┘  │
│                  │              │            │              │
│  ❌ Pas de HSM   │              │  ┌─────────▼──────────┐  │
│     (en attente) │              │  │  HSM #1 (GCS)      │  │
│                  │              │  │  /dev/ttyUSB0      │  │
│                  │              │  │  GCS_HSM.py ✅     │  │
└──────────────────┘              └──┴────────────────────┴──┘
```

### Test Intégration Pixhawk 5X + GCS + HSM - VALIDÉ (2026-01-24)

```bash
# Commande de test
python3 -u -c "
from Tools.hsm.gcs_hsm import GCS_HSM
from pymavlink import mavutil
# ... voir test complet dans le repo
"
```

**Résultat:**
```
[1/3] GCS_HSM:
  ✅ MK: LOADED (03AEE16B...)
  ✅ WK: LOADED (84DC3B39...)
  ✅ DEK: LOADED (B4F8A3B7...)

[2/3] Pixhawk 5X:
  ✅ HEARTBEAT OK (sysid=1)
  ✅ Autopilot: ArduPilot

[3/3] MAVLink:
  ✅ 22 msg/s (ATTITUDE, SYS_STATUS, etc.)
```

### Feature 2.2: Key Exchange Protocol - EN COURS (2026-01-24)

**Fichiers créés:**
```
# Python (GCS)
Tools/hsm/
├── __init__.py          # Exports
├── gcs_hsm.py           # ✅ KeyOrchestrator GCS (testé)
├── ecies.py             # ✅ ECIES encrypt/decrypt (testé)
└── key_exchange_protocol.py  # ✅ Protocol complet (testé loopback)

# C++ (Pixhawk)
libraries/AP_HSM/
├── KeyExchangeProtocol.h    # ✅ Header
└── KeyExchangeProtocol.cpp  # ✅ Implémentation (compilé)

# MAVLink Messages
modules/mavlink/message_definitions/v1.0/ardupilotmega.xml
  - HSM_WK_EXCHANGE (ID: 12000)  # ✅ Ajouté
  - HSM_DEK_EXCHANGE (ID: 12001) # ✅ Ajouté
  - HSM_KEY_ACK (ID: 12002)      # ✅ Ajouté
```

**Test Python loopback: RÉUSSI**
```bash
cd Tools/hsm && python3 key_exchange_protocol.py
# *** TEST PASSED: DEKs exchanged correctly! ***
```

**Build C++: RÉUSSI**
```bash
./waf copter
# 'copter' finished successfully
```

**TODO Feature 2.2:**
- [ ] Intégrer MAVLink message handlers dans GCS_MAVLink
- [ ] Connecter KeyExchangeProtocol au système de messages
- [ ] Test complet Pixhawk ↔ GCS via MAVLink
- [ ] Implémenter ChaCha20-Poly1305 propre (placeholder actuel)

**Prochaine étape:** Intégrer les handlers MAVLink et tester avec HSM réel
