# CLAUDE.md - HSM ArduPilot v2.0

## Overview

HSM LeMonolith v0.6 integration with ArduPilot for secure MAVLink communications.
**Architecture v2.0** - 3-level key hierarchy with bidirectional exchange protocol.

---

## Quick Start (Pour reprendre le travail)

### Option 1: Test Pixhawk5X avec Mock HSM (RECOMMANDÉ)

```bash
# 1. Vérifier connexions
ls -la /dev/ttyUSB0   # HSM LeMonolith
ls -la /dev/ttyACM0   # Pixhawk5X

# 2. Vérifier Mock HSM activé
grep "AP_HSM_MOCK_ENABLED" libraries/AP_HSM/AP_HSM.h
# Doit afficher: #define AP_HSM_MOCK_ENABLED 1

# 3. Compiler et flasher Pixhawk
./waf configure --board Pixhawk5X
./waf copter
./waf --upload copter

# 4. Lancer le test GCS avec Real HSM
python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 --timeout 120

# Résultat attendu:
#   Peer 1: state=COMPLETE wk_recv=True dek_recv=True
#   Decrypted OK: 42+
```

### Option 2: Test SITL avec Real HSM

```bash
# 1. Vérifier HSM connecté
ls -la /dev/ttyUSB0

# 2. Compiler SITL
./waf configure --board sitl && ./waf copter

# 3. Lancer SITL avec HSM
stdbuf -oL ./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &
sleep 35  # Attendre init HSM (~25s)

# 4. Test GCS (sans HSM local car SITL utilise le HSM)
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 60

# Résultat attendu: "KEY EXCHANGE COMPLETE!"
```

### Dépannage HSM

```bash
# Si HSM envoie du garbage, débrancher/rebrancher USB puis:
python3 << 'EOF'
import serial, time
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=2)
ser.write(b'off\r\n'); time.sleep(0.5)
ser.write(b'on\r\n'); time.sleep(4)
ser.write(b'A 00A4040006010203040601\r\n'); time.sleep(1.5)
print('OK!' if b'9000' in ser.read(500) else 'ERROR - rebrancher HSM')
ser.close()
EOF
```

---

## Commit History

| Commit | Feature | Description |
|--------|---------|-------------|
| `2c13981c60` | Session 6 | Fix key exchange: RNG + peer reset + GCS heartbeats |
| `75656daedf` | Session 5 | Fix uECC crash on ARM Cortex-M7 (platform detection) |
| `2d7b310a78` | Feature 3 | DualDekEngine - Chiffrement MAVLink End-to-End |
| `46575f08f9` | Feature 2.2 | Key Exchange Protocol - Implementation |
| `49cb78d04b` | Feature 1 | Organisation et documentation complète |
| `197a9cec4b` | Feature 1 | Initialisation fiable et robuste du LeMonolith HSM |

---

## Feature Status (2026-02-04)

| Feature | Status | Notes |
|---------|--------|-------|
| 1: AP_HSM init | ✅ DONE | Blocking init ~25s (SITL), instant (Pixhawk Mock) |
| 2.1: KeyOrchestrator | ✅ DONE | MK+WK+DEK stored in HSM |
| 2.2: Key Exchange Protocol | ✅ DONE | Full ECIES crypto on SITL + Pixhawk |
| 3: Dual-DEK Engine | ✅ DONE | TX/RX encryption, deterministic nonce |
| **3.1: CRC Fix** | ✅ DONE | Session 22 - Recalculer CRC sur ciphertext |
| **3.2: GCS RX Decrypt** | ✅ DONE | Session 23 - pymavlink v2.0 fix + 51 msg OK |
| **Mock HSM** | ✅ DONE | Test Pixhawk sans câble TELEM2 |
| **Pixhawk KEP** | ✅ DONE | Full bidirectional exchange - Session 6 |
| **Peer Reset** | ✅ DONE | 30s timeout allows re-exchange without reboot |
| **HSM avant TCP** | ❌ ABANDONNÉ | Session 10 - Impossible sans modifier HAL |
| **KEP Test Framework** | ✅ DONE | 27 tests bidirectionnels - Session 11 |

---

## Session 10: Analyse HSM Init vs TCP (2026-02-03)

### Objectif Initial
Déplacer l'initialisation HSM **AVANT** la connexion TCP pour permettre l'utilisation d'un **VRAI HSM** en SITL.

### Découverte Importante

**Le TCP bind/accept ne se fait PAS dans `serial_manager.init_console()` !**

L'initialisation TCP se fait dans `HAL_SITL_Class.cpp:run()` AVANT que `setup()` soit appelé:

```cpp
// libraries/AP_HAL_SITL/HAL_SITL_Class.cpp:214-250
void HAL_SITL::run(...) const
{
    _sitl_state->init(argc, argv);  // Parse --serial1=uart:/dev/...
    scheduler->init();
    serial(0)->begin(115200);       // ← TCP bind + accept() BLOQUANT ICI!
    // ...
    callbacks->setup();             // ← AP_Vehicle::setup() vient APRÈS!
}
```

### Pourquoi l'Approche "HSM avant TCP dans setup()" Ne Fonctionne Pas

```
Séquence réelle:
1. HAL_SITL::run() → serial(0)->begin() → TCP:5760 bind + accept()
2. GCS se connecte (ou timeout)
3. callbacks->setup() → AP_Vehicle::setup() → HSM init

Modifier l'ordre dans setup() n'a AUCUN effet car TCP est déjà établi!
```

### Option Analysée: Modifier HAL_SITL_Class.cpp

**Avantages:**
- ✅ Permettrait Real HSM avant connexion TCP
- ✅ GCS se connecterait à un système prêt

**Inconvénients:**
- ⚠️ Couplage architectural HAL → Application (mauvaise pratique)
- ⚠️ HAL_SITL devrait inclure AP_HSM.h
- ⚠️ Code spécifique SITL, pas portable vers Pixhawk

### Décision: ABANDONNER

L'architecture actuelle est acceptable:
1. GCS se connecte via TCP
2. HSM s'initialise (~25s pour Real HSM, instant pour Mock)
3. Premier HEARTBEAT envoyé après HSM init
4. Key exchange peut commencer

**Le GCS doit simplement attendre ~30s avant de recevoir des données avec Real HSM.**

### Architecture Actuelle (Conservée)

```cpp
// libraries/AP_Vehicle/AP_Vehicle.cpp
void AP_Vehicle::setup() {
    AP_Param::setup_sketch_defaults();
    serial_manager.init_console();  // Note: TCP déjà établi par HAL!

    // HSM init APRÈS TCP (GCS connecté mais attend HSM)
    #if AP_HSM_ENABLED && CONFIG_HAL_BOARD == HAL_BOARD_SITL
    hsm.begin(hal.serial(1));
    hsm.init_monolith();  // Mock=instant, Real=25s
    // ... KeyOrchestrator, KEP, DDE ...
    #endif
}
```

### Commande pour Real HSM en SITL (fonctionne toujours)

```bash
# Le GCS doit attendre ~35s après connexion pour le premier HEARTBEAT
./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &
sleep 35  # Attendre HSM init
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 60
```

---

## Technical Decisions

| Question | Answer |
|----------|--------|
| Backward compatibility v1? | **NO** - Complete replacement |
| Number of drones | **2-5** |
| Network topology | **Mesh**, test: 1 drone + GCS |
| Master Key generation | **At boot** (mission init) |
| Master Key unique? | **YES** - each drone has its own MK |
| Wrapper Key duration | **Per mission** |
| Nonce | **Random 24 bytes** (XChaCha20) |
| DEK rotation | **Per mission** (not in flight) |
| Messages in transit | **HEARTBEAT plaintext**, others wait for DEK |
| Transport | **Custom MAVLink messages** |
| Authentication | **Trust-on-first-use** |
| Discovery | **Via HEARTBEAT** |
| PFS | **YES** - Ephemeral ECDH + WK rotation |
| HSM storage | **MK + wrapped WK_priv + wrapped DEK** |

---

## Cryptographic Architecture

```
LEVEL 1: MASTER KEY (MK)
├── Type: ChaCha20-256 bits (32 bytes)
├── Generation: Random at boot
├── Storage: HSM @0x0100
└── UNIQUE per drone

        │ HKDF-SHA256 ("WrapperKey-P256-v1")
        ▼

LEVEL 2: WRAPPER KEY (WK)
├── Type: secp256r1 (P-256) asymmetric
├── WK_private: Derived from MK via HKDF
├── WK_public: Computed from WK_private (micro-ecc)
├── Storage: WK_priv wrapped HSM @0x0120, tag @0x0160
└── Usage: Secure DEK exchange (ECIES)

        │ ECIES (XChaCha20-Poly1305)
        ▼

LEVEL 3: DATA ENCRYPTION KEY (DEK)
├── Type: ChaCha20-256 bits (32 bytes)
├── MY_DEK: Encrypt outgoing messages
├── PEER_DEKs: Decrypt incoming messages
├── Generation: Random per drone
└── Storage: MY_DEK wrapped HSM @0x0140, tag @0x0180
```

---

## HSM Storage Map

| Offset | Size | Content |
|--------|------|---------|
| 0x0100 | 32 bytes | Master Key (MK) |
| 0x0120 | 32 bytes | Wrapped WK_private |
| 0x0140 | 32 bytes | Wrapped DEK |
| 0x0160 | 32 bytes | HMAC tag (WK) |
| 0x0180 | 32 bytes | HMAC tag (DEK) |

---

## HSM APDU Commands

**WARNING: CC applet uses NON-STANDARD commands!**

| Operation | INS | Format | Example |
|-----------|-----|--------|---------|
| **WRITE** | **D0** | `00 D0 <P1> <P2> <Lc> <data>` | `A 00D0010020<64hex>` |
| READ | B0 | `00 B0 <P1> <P2> <Le>` | `A 00B0010020` |
| VERIFY PIN | 20 | `00 20 00 01 08 <pin_hex>` | `A 00200001083030303030303030` |
| SELECT CC | A4 | `00 A4 04 00 06 <AID>` | `A 00A4040006010203040601` |

**Default PIN:** `00000000` = `3030303030303030` (hex)

**Init sequence:**
```bash
off                                    # Power OFF (0.3s delay)
on                                     # Power ON (3.5s delay, auto-SELECT)
A 00200001083030303030303030           # VERIFY PIN (1.5s delay)
A 00D0010020<data_64_hex>              # WRITE 32 bytes @0x0100 (3s delay)
A 00B0010020                           # READ 32 bytes @0x0100 (0.5s delay)
```

**Critical delays:**
- After ON: **3.5s** (ATR + auto-SELECT)
- After WRITE: **2-3s** (EEPROM)
- Other commands: 0.5s

---

## MAVLink Custom Messages

| ID | Name | Usage |
|----|------|-------|
| 12000 | HSM_WK_EXCHANGE | Exchange WK public key |
| 12001 | HSM_DEK_EXCHANGE | Encrypted DEK via ECIES |
| 12002 | HSM_KEY_ACK | Acknowledgment |

**DEK_EXCHANGE payload (138 bytes):**
- target_sys (1) + target_comp (1) + ephemeral (64) + encrypted_dek (32) + nonce (24) + tag (16)

---

## Cryptographic Algorithms

| Usage | Algorithm | Implementation |
|-------|-----------|----------------|
| Master Key | ChaCha20-256 (32 bytes) | Random |
| WK derivation | HKDF-SHA256 | AP_Crypto |
| Wrapper Key | secp256r1 (P-256) | micro-ecc |
| DEK exchange | ECIES | micro-ecc + Monocypher |
| ECIES encryption | **XChaCha20-Poly1305** | **Monocypher (C++) / PyNaCl (Python)** |
| Nonce | **24 bytes** | Random |
| Auth tag | Poly1305 16 bytes | Monocypher |

---

## Key Files

```
libraries/AP_HSM/
├── AP_HSM.h/.cpp               # HSM LeMonolith driver
├── KeyOrchestrator.h/.cpp      # Feature 1: Key hierarchy
├── KeyExchangeProtocol.h/.cpp  # Feature 2: Key exchange
├── DualDekEngine.h/.cpp        # Feature 3: Payload encryption
├── uECC.h                      # micro-ecc for P-256
└── wscript                     # Build config

libraries/AP_Crypto/
├── AP_Crypto.h/.cpp            # SHA-256, HMAC, HKDF

libraries/AP_CheckFirmware/
├── monocypher.h/.cpp           # XChaCha20-Poly1305

libraries/GCS_MAVLink/
├── GCS_Common.cpp              # MAVLink handlers (lines 4617-4688)

Tools/hsm/
├── gcs_hsm.py                  # GCS KeyOrchestrator
├── ecies.py                    # ECIES encrypt/decrypt
├── key_exchange_protocol.py    # GCS KEP
├── gcs_kep_client.py           # GCS client for key exchange
├── dual_dek_engine.py          # Feature 3: Python DualDekEngine
├── setup_mavlink.py            # MAVLink dialect generator
├── mavlink_hsm.py              # Generated MAVLink dialect
├── test_kep_steps.py           # KEP test runner (27 tests)
└── test_assertions.py          # Reusable test assertions
```

---

## Build Commands

```bash
# Configure SITL
./waf configure --board sitl

# Compile Copter
./waf copter

# Configure Pixhawk 5X
./waf configure --board Pixhawk5X

# Regenerate MAVLink dialect
cd modules/mavlink && python3 pymavlink/tools/mavgen.py --lang=Python3 --wire-protocol=2.0 \
    --output=/path/to/Tools/hsm/mavlink_hsm message_definitions/v1.0/ardupilotmega.xml
```

---

## Test Commands

```bash
# 1. Verify HSM connected
ls -la /dev/ttyUSB0

# 2. Clean existing processes
pkill -9 arducopter; pkill -9 mavproxy; fuser -k 5760/tcp

# 3. Compile
./waf copter

# 4. Launch SITL with HSM
./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &

# 5. Wait for HSM init (~35s)
sleep 35

# 6. Connect MAVProxy
mavproxy.py --master=tcp:127.0.0.1:5760 --source-system=255

# Expected logs:
# - "HSM: ✓ Feature 1 completed successfully!"
# - "KeyOrch: ✓ MISSION INITIALIZED"
# - "HSM: ✓ Feature 2.1 completed successfully!"
# - "HSM: ✓ KeyExchangeProtocol initialized"
```

**GCS client test:**
```bash
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 60
```

**ECIES test:**
```bash
python3 Tools/hsm/ecies.py
# *** TEST PASSED: DEK matches! ***
```

---

## Test Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  SITL + Real HSM                                                │
│  ┌──────────────┐    ┌──────────┐    ┌──────────────┐          │
│  │ sim_vehicle  │◄──►│ MAVProxy │    │     HSM      │          │
│  │   (SITL)     │    │  (GCS)   │    │ /dev/ttyUSB0 │          │
│  │ ArduCopter   │    └──────────┘    └──────────────┘          │
│  └──────┬───────┘                           ▲                   │
│         │ SERIAL1 (uart)                    │                   │
│         └───────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Exchange Flow

```
DRONE (sysid=1)                          GCS (sysid=255)
──────────────                           ──────────────
      │                                        │
      │  ◄──────── HEARTBEAT ─────────────── │
      │                                        │
      │  ─────── HSM_WK_EXCHANGE ──────────► │
      │     { wk_public[64], timestamp }      │
      │                                        │
      │  ◄────── HSM_WK_EXCHANGE ───────────  │
      │     { wk_public[64], timestamp }      │
      │                                        │
      │  ─────── HSM_DEK_EXCHANGE ─────────► │
      │     { ephemeral[64], encrypted[32],   │
      │       nonce[24], tag[16] }            │
      │                                        │
      │  ◄────── HSM_DEK_EXCHANGE ──────────  │
      │     { ephemeral[64], encrypted[32],   │
      │       nonce[24], tag[16] }            │
      │                                        │
      │  ◄──────► HSM_KEY_ACK ◄─────────────► │
      │                                        │
      ▼                                        ▼
   peer_deks[255] = DEK_GCS          peer_deks[1] = DEK_DRONE
```

---

## HSM Init: SITL vs Pixhawk

**IMPORTANT: L'architecture d'init est différente selon la plateforme!**

```
┌─────────────────────────────────────────────────────────────────┐
│  SITL (Linux)                  │  PIXHAWK (ChibiOS)             │
├────────────────────────────────┼─────────────────────────────────┤
│  • Single thread simulé        │  • Multi-thread réel            │
│  • delay() bloque TOUT         │  • delay() bloque 1 tâche       │
│  • Init BLOQUANTE dans setup() │  • Init ASYNC via scheduler     │
│  • TCP indisponible 21s        │  • MAVLink fonctionne pendant   │
│  • GCS doit attendre >25s      │  • GCS reçoit heartbeats immédiatement │
└────────────────────────────────┴─────────────────────────────────┘
```

**Code (AP_Vehicle.cpp):**
```cpp
// SITL: Init bloquante dans setup() - ligne 322
#if AP_HSM_ENABLED && CONFIG_HAL_BOARD == HAL_BOARD_SITL
    hsm.init_monolith();  // Bloque 21s
#endif

// Pixhawk: Init async via scheduler - ligne 761
#if AP_HSM_ENABLED && CONFIG_HAL_BOARD != HAL_BOARD_SITL
    SCHED_TASK(hsm_update, 10, 200, 254),  // 10Hz, non-bloquant
#endif
```

**Pourquoi cette différence?**
- En SITL, le scheduler et TCP partagent le même thread
- `hal.scheduler->delay()` bloque tout le processus
- Sur Pixhawk (ChibiOS), les tâches sont sur des threads séparés
- Les delays dans `hsm_update()` ne bloquent pas MAVLink

---

## Pixhawk 5X Migration

**Current (HSM on PC):**
```
Pixhawk 5X  ◄─USB─►  PC  ◄─USB─►  HSM /dev/ttyUSB0
```

**Future (Direct connection):**
```
Pixhawk 5X TELEM2  ◄─UART─►  HSM LeMonolith
```

**Wiring TELEM2 Pixhawk 5X:**
```
Pixhawk TELEM2     HSM LeMonolith (ESP32)
Pin 2 (TX)    ───► RX (GPIO3)
Pin 3 (RX)    ◄─── TX (GPIO1)
Pin 6 (GND)   ───► GND
```

**ArduPilot parameters:**
```
SERIAL2_PROTOCOL = -1    # No MAVLink protocol
SERIAL2_BAUD = 115       # 115200 baud
```

**Code change (AP_Vehicle.cpp) pour Pixhawk:**
```cpp
// Ligne 326: Changer SERIAL1 vers SERIAL2
AP_HAL::UARTDriver* uart = hal.serial(2);  // SERIAL2 = TELEM2
```

---

## Mock HSM - Test sans câble TELEM2

### Objectif

Tester le code Pixhawk **SANS câble physique** vers le HSM. Le Mock simule le HSM en RAM.

### Architecture de test actuelle

```
┌────────────────────────────┐                    ┌────────────────────────────┐
│      PIXHAWK 5X            │                    │      PC (GCS)              │
│      (Drone)               │                    │                            │
│                            │     Telemetry      │                            │
│  ┌──────────────────────┐  │◄─── Radio/WiFi ──►│  ┌──────────────────────┐  │
│  │   ArduCopter         │  │      MAVLink      │  │   gcs_kep_client.py  │  │
│  │   + KEP + DDE        │  │                   │  │                      │  │
│  └──────────┬───────────┘  │                   │  └──────────┬───────────┘  │
│             │              │                   │             │              │
│  ┌──────────▼───────────┐  │                   │  ┌──────────▼───────────┐  │
│  │   *** MOCK HSM ***   │  │                   │  │   *** REAL HSM ***   │  │
│  │   (RAM - 256 bytes)  │  │                   │  │   /dev/ttyUSB0       │  │
│  │   Pas de câble!      │  │                   │  │   LeMonolith v0.6    │  │
│  └──────────────────────┘  │                   │  └──────────────────────┘  │
└────────────────────────────┘                   └────────────────────────────┘
```

### Configuration Mock HSM

**Fichier:** `libraries/AP_HSM/AP_HSM.h`

```cpp
// ═══════════════════════════════════════════════════════════════════
// MOCK HSM CONFIGURATION
// ═══════════════════════════════════════════════════════════════════
// Set to 1 to enable Mock HSM (simulated in RAM, no hardware needed)
// Set to 0 to use real HSM hardware via UART
#ifndef AP_HSM_MOCK_ENABLED
#define AP_HSM_MOCK_ENABLED 1    // ← CHANGER ICI
#endif
// ═══════════════════════════════════════════════════════════════════
```

### Comportement Mock vs Real HSM

| Fonction | Mock HSM | Real HSM |
|----------|----------|----------|
| `init_monolith()` | Return `true` immédiatement | UART init + APDU séquence (~25s) |
| `send_apdu()` | Simule READ/WRITE en RAM | Envoie APDU via UART |
| `store_*_to_hsm()` | Stocke dans `_mock_storage[]` | WRITE BINARY APDU |
| `load_*_from_hsm()` | Lit depuis `_mock_storage[]` | READ BINARY APDU |
| Init time | **0 ms** | **~22 secondes** |

### Mock Storage Map (RAM)

```
_mock_storage[256]:
  Offset 0x00 (HSM 0x0100): Master Key (32 bytes)
  Offset 0x20 (HSM 0x0120): Wrapped WK_private (32 bytes)
  Offset 0x40 (HSM 0x0140): Wrapped DEK (32 bytes)
  Offset 0x60 (HSM 0x0160): HMAC tag WK (32 bytes)
  Offset 0x80 (HSM 0x0180): HMAC tag DEK (32 bytes)
```

### Test avec Mock HSM

**Compiler pour Pixhawk5X:**
```bash
./waf configure --board Pixhawk5X
./waf copter
# Flasher build/Pixhawk5X/bin/arducopter.apj
```

**GCS avec Real HSM:**
```bash
# Le GCS utilise le vrai HSM connecté au PC
python3 Tools/hsm/gcs_kep_client.py --hsm --timeout 120
```

**Logs attendus (Pixhawk):**
```
KeyOrch: ✓ MISSION INITIALISÉE EN 0 ms   ← Mock instantané!
HSM: ✓ Feature 2.1 complétée avec succès!
HSM: ✓ KeyExchangeProtocol initialisé
HSM: ✓ DualDekEngine initialisé
```

---

## Quand le câble TELEM2 arrive

### Étapes pour passer au Real HSM

**1. Désactiver le Mock:**
```cpp
// libraries/AP_HSM/AP_HSM.h
#define AP_HSM_MOCK_ENABLED 0    // ← Changer de 1 à 0
```

**2. Configurer SERIAL2 pour le HSM:**
```cpp
// libraries/AP_Vehicle/AP_Vehicle.cpp (ligne ~328)
// Changer:
AP_HAL::UARTDriver* uart = hal.serial(1);  // SERIAL1
// En:
AP_HAL::UARTDriver* uart = hal.serial(2);  // SERIAL2 = TELEM2
```

**3. Paramètres ArduPilot:**
```
SERIAL2_PROTOCOL = -1    # Pas de protocole MAVLink
SERIAL2_BAUD = 115       # 115200 baud
```

**4. Câblage TELEM2:**
```
Pixhawk TELEM2     HSM LeMonolith (ESP32)
Pin 2 (TX)    ───► RX (GPIO3)
Pin 3 (RX)    ◄─── TX (GPIO1)
Pin 6 (GND)   ───► GND
```

**5. Recompiler et flasher:**
```bash
./waf configure --board Pixhawk5X
./waf copter
# Flasher build/Pixhawk5X/bin/arducopter.apj
```

**6. Test:**
```bash
# GCS sans HSM local (le drone a son propre HSM maintenant)
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 120
```

### Checklist transition Mock → Real HSM

- [ ] Câble TELEM2 connecté (TX/RX/GND)
- [ ] `AP_HSM_MOCK_ENABLED` = 0
- [ ] `hal.serial(2)` dans AP_Vehicle.cpp
- [ ] `SERIAL2_PROTOCOL = -1`
- [ ] `SERIAL2_BAUD = 115`
- [ ] Recompilé et flashé
- [ ] Test key exchange OK

---

## Important Technical Notes

### SITL UART Buffer
In SITL, UART writes are buffered. Force scheduler to flush:
```cpp
uart_hsm->printf("%s\r\n", apdu);
for (int i = 0; i < 10; i++) {
    hal.scheduler->delay(10);  // Flush buffer
}
hal.scheduler->delay(500);  // Wait for HSM response
```

### Debug Logging
- SITL: Use `printf()` + `fflush(stdout)`
- Pixhawk: Use `hal.console->printf()` (no stdout on embedded)

**Pixhawk compilation fixes applied:**
- Replaced `printf()` with `hal.console->printf()` in AP_HSM.cpp, KeyExchangeProtocol.cpp, AP_Vehicle.cpp, GCS_Common.cpp
- Removed `#include <iostream>` (not available on embedded)
- Replaced `sscanf()` with manual hex conversion
- Fixed micro-ecc `__clang_major__` and `default_RNG_defined` macros

### HSM Reset
If HSM sends garbage, physically disconnect/reconnect USB, then test:
```python
import serial, time
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=2)
ser.write(b'off\r\n'); time.sleep(0.3); ser.read(100)
ser.write(b'on\r\n'); time.sleep(4); ser.read(1000)
ser.write(b'A 00A4040006010203040601\r\n'); time.sleep(1.5)
print('OK!' if b'9000' in ser.read(500) else 'Error')
```

### Unencrypted Messages
- HEARTBEAT (peer discovery)
- HSM_WK_EXCHANGE
- HSM_DEK_EXCHANGE
- HSM_KEY_ACK

---

## Monocypher API

```cpp
// Encryption
void crypto_lock(uint8_t mac[16], uint8_t *cipher_text,
                 const uint8_t key[32], const uint8_t nonce[24],
                 const uint8_t *plain_text, size_t text_size);

// Decryption (returns 0 on success, -1 on auth failure)
int crypto_unlock(uint8_t *plain_text,
                  const uint8_t key[32], const uint8_t nonce[24],
                  const uint8_t mac[16],
                  const uint8_t *cipher_text, size_t text_size);
```

---

## Feature 3: DualDekEngine - COMPLETE ✅

**All components working:**
- ✅ `DualDekEngine.h/.cpp` - Core C++ engine (Monocypher)
- ✅ `dual_dek_engine.py` - Python equivalent (PyNaCl)
- ✅ TX Hook in `GCS_MAVLink.cpp:comm_send_buffer()` - Encryption payload
- ✅ RX Hook in `GCS_Common.cpp:update_receive()` - Décryption BAD_CRC
- ✅ Plaintext messages exclus (HEARTBEAT, HSM_*)
- ✅ Nonce déterministe (seq + sysid + msgid)
- ✅ Build SITL + Pixhawk5X successful
- ✅ Init in `AP_Vehicle.cpp` after KEP
- ✅ GCS client integration (`gcs_kep_client.py`)
- ✅ End-to-end test: Key exchange + encrypted messages

**Architecture TX/RX:**
```
TX (GCS_MAVLink.cpp:200):
├── Parse header buffer[0] → extract seq, sysid, msgid
├── Skip if msgid in {0, 12000, 12001, 12002}  # Plaintext
├── Nonce = seq || sysid || compid || msgid || chan || 0x00...
├── ChaCha20XOR(my_dek, nonce, payload) → encrypted
└── Send encrypted payload

RX (GCS_Common.cpp:1939):
├── Receive → CRC computed on encrypted = BAD_CRC
├── If BAD_CRC && encryption_enabled:
│   ├── Get peer_dek from KeyExchangeProtocol(msg.sysid)
│   ├── Same nonce derivation as TX
│   ├── ChaCha20XOR(peer_dek, nonce, encrypted) → plaintext
│   └── packetReceived(plaintext)
```

**Limitation:**
- CRC calculé sur plaintext côté TX mais payload chiffré
- Côté RX, CRC échoue (BAD_CRC) car calculé sur bytes chiffrés
- On intercepte BAD_CRC et décrypte manuellement
- Stream cipher sans MAC (pas d'authentification crypto)

**Test Commands:**
```bash
# Test Python DualDekEngine
python3 Tools/hsm/dual_dek_engine.py
# *** ALL TESTS PASSED ***

# Test SITL avec HSM - Full end-to-end
# 1. Start SITL with HSM
stdbuf -oL ./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 > /tmp/sitl.log 2>&1 &

# 2. Run GCS client (triggers HSM init, waits 60s for heartbeat)
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 120

# Expected output:
# - HSM init: ~25s
# - Key exchange: WK + DEK bidirectional
# - "KEY EXCHANGE COMPLETE!"
# - DDE initialized with peer DEK
# - BAD_DATA messages = encrypted messages (normal)
```

---

## KEP Testing Framework - COMPLETE ✅

### Overview

Comprehensive test suite for validating Key Exchange Protocol (KEP) bidirectionally between SITL/Pixhawk (drone) and GCS.

**27 tests** organized in **6 steps** covering the complete communication flow.

### Test Files

| File | Lines | Description |
|------|-------|-------------|
| `Tools/hsm/test_kep_steps.py` | ~700 | Main test runner |
| `Tools/hsm/test_assertions.py` | ~300 | Reusable assertions |

### Test Coverage

| Step | Name | Tests | Description |
|------|------|-------|-------------|
| 1 | HSM Init | 2 | Mock HSM (SITL) + Real HSM (GCS) |
| 2 | HEARTBEAT | 4 | Bidirectional discovery |
| 3 | WK Exchange | 6 | Wrapper Key exchange (msg 12000) |
| 4 | DEK Exchange | 8 | Data Encryption Key via ECIES (msg 12001) |
| 5 | KEY_ACK | 5 | Acknowledgments + error handling |
| 6 | Encryption | 5 | ChaCha20 TX/RX validation |

### Usage

```bash
# Run all 27 tests
python3 Tools/hsm/test_kep_steps.py --all --no-hsm

# Run specific step
python3 Tools/hsm/test_kep_steps.py --step 3              # WK Exchange
python3 Tools/hsm/test_kep_steps.py --step 4.6            # GCS ECIES decrypt

# With real HSM
python3 Tools/hsm/test_kep_steps.py --all --hsm /dev/ttyUSB0

# Options
python3 Tools/hsm/test_kep_steps.py --all --stop-on-fail  # Stop on first error
python3 Tools/hsm/test_kep_steps.py --all --verbose       # Detailed logs
```

### Test Report Example

```
════════════════════════════════════════════════════════════════
                    RAPPORT DE TEST KEP
════════════════════════════════════════════════════════════════

ÉTAPE 1: HSM INIT
────────────────────────────────────────────────────────────────
  ✓ 1.1 Mock HSM init (SITL)      PASS    [12ms]
  ✓ 1.2 Real HSM init (GCS)       PASS    [24532ms]

ÉTAPE 2: HEARTBEAT DISCOVERY
  ✓ 2.1-2.4                       PASS

ÉTAPE 3: WK EXCHANGE
  ✓ 3.1-3.6                       PASS

ÉTAPE 4: DEK EXCHANGE
  ✓ 4.1-4.8                       PASS

ÉTAPE 5: KEY_ACK
  ✓ 5.1-5.5                       PASS

ÉTAPE 6: ENCRYPTION
  ✓ 6.1-6.5                       PASS

════════════════════════════════════════════════════════════════
RÉSULTAT: 27/27 TESTS PASSED
════════════════════════════════════════════════════════════════
```

### Key Assertions (test_assertions.py)

```python
class TestAssertions:
    # HSM Init
    def assert_hsm_init_time(self, init_time_ms, max_ms, is_mock=True)
    def assert_mk_present(self, mk_bytes)

    # HEARTBEAT
    def assert_heartbeat_received(self, msg, timeout_s, expected_sysid=None)
    def assert_peer_created(self, peers, sysid)

    # WK Exchange
    def assert_wk_public_size(self, wk_public)
    def assert_wk_stored(self, peer, wk_public)

    # DEK Exchange
    def assert_ecies_decrypt_success(self, success)
    def assert_dek_stored(self, peer, dek)

    # State
    def assert_state_complete(self, state, sysid)

    # Encryption
    def assert_message_encrypted(self, is_bad_crc, msgid)
    def assert_decrypt_success(self, plaintext, expected_msgid)
```

---

## Known Issues & Limitations

| Issue | Description | Workaround |
|-------|-------------|------------|
| SITL blocking | HSM init bloque TCP pendant ~25s | GCS client attend 60s pour heartbeat |
| No MAC on payload | ChaCha20 stream cipher sans authentification | CRC MAVLink sert de checksum (pas crypto) |
| Single connection SITL | SITL s'arrête si connexion TCP fermée | Garder connexion ouverte ou reconnecter |
| ~~CRC mismatch~~ | ~~CRC calculé sur plaintext mais payload chiffré~~ | **RÉSOLU** Session 22 - Recalcul CRC ciphertext |
| ~~BAD_DATA spam~~ | ~~pymavlink utilisait dialect v10 au lieu de v20~~ | **RÉSOLU** Session 23 - MAVLINK20=1 |
| ~~uECC crash ARM~~ | ~~Toutes les fonctions uECC crashent sur Pixhawk5X~~ | **RÉSOLU** Session 5 - Fix config platform |
| ~~WK response missing~~ | ~~Pixhawk envoie KEY_ACK mais pas WK_EXCHANGE~~ | **RÉSOLU** Session 5 |
| ~~DEK not sent~~ | ~~uECC_make_key échouait - RNG pas configuré~~ | **RÉSOLU** Session 6 |

---

## Next Steps (Future Work)

| Priority | Task | Description | Status |
|----------|------|-------------|--------|
| ~~1~~ | ~~CRC Fix~~ | ~~Recalculer CRC sur ciphertext dans buffer[2]~~ | ✅ DONE (Session 22) |
| ~~2~~ | ~~pymavlink v2.0~~ | ~~MAVLINK20=1 avant import pymavlink~~ | ✅ DONE (Session 23) |
| 3 | ~~Fix KEP response~~ | ~~Pixhawk reçoit WK mais ne renvoie pas le sien~~ | ✅ DONE (Session 5) |
| 4 | ~~Fix uECC ARM~~ | ~~uECC crashait - config forçait x86_64 sur ARM~~ | ✅ DONE (Session 5) |
| 5 | ~~Fix ECIES RNG~~ | ~~uECC_make_key échouait - RNG pas configuré~~ | ✅ DONE (Session 6) |
| 6 | ~~Peer state reset~~ | ~~Reset état peer pour re-exchange~~ | ✅ DONE (Session 6) |
| ~~7~~ | ~~GCS TX Encryption~~ | ~~Chiffrer messages GCS→Drone~~ | ✅ DONE (Session 23) |
| 8 | **Pi Zero Bridge** | Configurer Pi Zero comme pont Pixhawk↔HSM | ⏳ En attente matériel |
| 9 | Multi-drone | Tester avec 2+ drones mesh | |
| 10 | DEK rotation | Rotation de clés en vol | |

---

## Session History

> **Détails complets:** Voir `CLAUDE_HISTORY.md` pour l'historique détaillé des sessions 1-22.

### Résumé des sessions clés

| Session | Date | Résultat |
|---------|------|----------|
| 5 | 2026-01-26 | Fix uECC ARM (config forçait x86_64) |
| 6 | 2026-01-26 | Full KEP working (RNG + peer reset) |
| 9 | 2026-01-27 | Pixhawk Mock HSM SUCCESS (42 msg déchiffrés) |
| 10 | 2026-02-03 | Analyse HSM vs TCP - ABANDONNÉ (TCP bind dans HAL) |
| 11 | 2026-02-03 | KEP Test Framework - 27 tests bidirectionnels |
| 21 | 2026-02-04 | Analyse CRC vs Encryption - Solution B retenue |
| **22** | **2026-02-04** | **CRC Fix implémenté - Drone TX encryption** |
| **23** | **2026-02-04** | **pymavlink v2.0 fix + GCS RX decrypt OK (51 msg)** |

### Session 10 - Analyse TCP vs HSM Init

**Objectif initial:** Déplacer HSM init AVANT TCP pour Real HSM en SITL

**Découverte clé:**
- Le TCP bind/accept se fait dans `HAL_SITL_Class.cpp:run()` AVANT `setup()`
- Modifier l'ordre dans `AP_Vehicle::setup()` n'a AUCUN effet
- Pour vraiment mettre HSM avant TCP, il faudrait modifier la HAL (couplage indésirable)

**Décision:** ABANDONNER cette approche
- L'architecture actuelle fonctionne
- GCS attend ~30s avec Real HSM, c'est acceptable
- Pas de couplage HAL → Application

**Code revenu à l'état original:**
- HSM init APRÈS `serial_manager.init_console()` dans `AP_Vehicle.cpp`

### Commande de test validée

```bash
# Pixhawk avec Mock HSM + GCS avec Real HSM
python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 --timeout 120

# SITL avec Real HSM (NOUVEAU - à tester)
./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200
```

### Session 11 - KEP Test Framework (2026-02-03)

**Objectif:** Créer un framework de test complet pour valider le Key Exchange Protocol

**Fichiers créés:**

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `Tools/hsm/test_kep_steps.py` | ~700 | Test runner principal avec 27 tests |
| `Tools/hsm/test_assertions.py` | ~300 | Assertions réutilisables |

**Tests implémentés (27 total):**

| Étape | Tests | Description |
|-------|-------|-------------|
| 1 | 1.1, 1.2 | HSM Init (Mock + Real) |
| 2 | 2.1-2.4 | HEARTBEAT discovery bidirectionnel |
| 3 | 3.1-3.6 | WK Exchange (envoie/reçoit/state) |
| 4 | 4.1-4.8 | DEK Exchange + ECIES decrypt |
| 5 | 5.1-5.5 | KEY_ACK + gestion erreurs |
| 6 | 6.1-6.5 | Encryption TX/RX + plaintext |

**Usage:**
```bash
# Tous les tests
python3 Tools/hsm/test_kep_steps.py --all --no-hsm

# Test spécifique
python3 Tools/hsm/test_kep_steps.py --step 4.6  # GCS ECIES decrypt
```

**Couverture identifiée mais non implémentée:**
- Peer Reset 30s timeout
- Race conditions (initiation simultanée)
- WK retry sur perte
- Multi-peer (>2 drones)
- Nonce rollover (seq 255→0)

### Session 21 - CRC Fix: Recalculer CRC sur Ciphertext (2026-02-04)

**Problème analysé:** Le CRC MAVLink est calculé sur le payload PLAINTEXT, mais le payload est chiffré APRÈS. Le RX calcule le CRC sur le CIPHERTEXT → mismatch → BAD_CRC.

**Séquence actuelle (problématique):**
```
mavlink_helpers.h:365-369  →  CRC = crc(PLAINTEXT)
GCS_MAVLink.cpp:237        →  Encrypt(payload)
→ RX: CRC(ciphertext) ≠ CRC_reçu → BAD_CRC
```

**Solution retenue (Option B):** Recalculer le CRC sur le ciphertext dans `comm_send_buffer()` buffer[2]

```cpp
// Variables statiques par channel
static uint8_t stored_header[MAVLINK_COMM_NUM_BUFFERS][10];
static uint8_t stored_ciphertext[MAVLINK_COMM_NUM_BUFFERS][256];
static uint8_t stored_ciphertext_len[MAVLINK_COMM_NUM_BUFFERS];
static bool was_encrypted[MAVLINK_COMM_NUM_BUFFERS];

// buffer[2]: Recalculer CRC
if (current_buffer == 2 && was_encrypted[chan]) {
    uint16_t crc;
    crc_init(&crc);
    // Header (bytes 1-9, sans STX)
    for (int i = 1; i < 10; i++) {
        crc_accumulate(stored_header[chan][i], &crc);
    }
    // Ciphertext
    crc_accumulate_buffer(&crc, (char*)stored_ciphertext[chan], stored_ciphertext_len[chan]);
    // CRC extra
    const mavlink_msg_entry_t* entry = mavlink_get_msg_entry(msgid);
    if (entry) crc_accumulate(entry->crc_extra, &crc);

    uint8_t ck[2] = {(uint8_t)(crc & 0xFF), (uint8_t)(crc >> 8)};
    write(ck, 2);
    return;
}
```

**Fichiers à modifier:**

| Fichier | Modification |
|---------|--------------|
| `GCS_MAVLink.cpp` | Stocker header/ciphertext + recalculer CRC buffer[2] |
| `GCS_Common.cpp` | Simplifier RX: décrypter après CRC OK |

**Avantages:**
- ✅ CRC valide côté RX (plus de BAD_CRC)
- ✅ Intégrité vérifiable
- ✅ Modification localisée (1 fichier principal)
- ✅ RAM: ~266 bytes/channel

**Status:** ✅ Implémenté Session 22

---

### Session 23 - pymavlink MAVLink v2.0 Fix (2026-02-04)

**Problème:** pymavlink retournait `BAD_DATA` pour tous les messages malgré des frames MAVLink v2 valides.

**Analyse:**
- Raw TCP montrait des frames MAVLink v2 correctes (start byte 0xFD, CRC valide)
- pymavlink utilisait `dialects/v10/ardupilotmega.py` au lieu de `v20/`
- La variable `WIRE_PROTOCOL_VERSION` était 2.0 mais le mauvais dialect était chargé

**Solution:** Définir `MAVLINK20=1` dans l'environnement AVANT d'importer pymavlink

```python
# gcs_kep_client.py - ligne 20
import os
os.environ['MAVLINK20'] = '1'  # AVANT import pymavlink!

# ... plus tard ...
from pymavlink import mavutil
mavutil.set_dialect('ardupilotmega')
```

**Fichier modifié:**
- `Tools/hsm/gcs_kep_client.py` - Ajout `os.environ['MAVLINK20'] = '1'`

**Résultat test (--test-tx):**
```
✓ KEY EXCHANGE COMPLETE!
  Peer 1: state=COMPLETE wk_recv=True dek_recv=True
  RX - Encrypted received: 50
  RX - Decrypted OK: 50
  RX - Decrypted FAIL: 0
  TX - Encrypted sent: 3  ← TX ENCRYPTION WORKS!
  TX Encryption: ENABLED
```

**Architecture finale Session 22+23:**
```
DRONE (SITL/Pixhawk)                    GCS (Python)
════════════════════                    ════════════
TX: Encrypt payload                     TX: (planned)
    Recalc CRC on ciphertext            RX: pymavlink v2.0
    Send frame                              Decrypt after CRC OK
                                            51 messages déchiffrés ✓
```

---

## Environment

```
OS: Ubuntu 22.04 (Linux 6.14.0)
Python: 3.10+
ArduPilot: V4.7.0-dev
HSM: LeMonolith v0.6 sur ESP32 (/dev/ttyUSB0)
Branch: kek-HSM
```

---

**Last update:** 2026-02-04 - Session 23: pymavlink v2.0 fix (MAVLINK20=1). Key exchange COMPLETE + RX decrypt (50 msg OK) + TX encrypt (3 msg OK).
