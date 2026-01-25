# CLAUDE.md - HSM ArduPilot v2.0

## Overview

HSM LeMonolith v0.6 integration with ArduPilot for secure MAVLink communications.
**Architecture v2.0** - 3-level key hierarchy with bidirectional exchange protocol.

---

## Quick Start (Pour reprendre le travail)

```bash
# 1. Vérifier HSM connecté
ls -la /dev/ttyUSB0

# 2. Compiler
cd /home/samwitwity/Code_Sources/ardupilot_claude
./waf configure --board sitl && ./waf copter

# 3. Test rapide Feature 3
stdbuf -oL ./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &
sleep 3
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 60

# Résultat attendu: "KEY EXCHANGE COMPLETE!"
```

---

## Commit History

| Commit | Feature | Description |
|--------|---------|-------------|
| `2d7b310a78` | Feature 3 | DualDekEngine - Chiffrement MAVLink End-to-End |
| `46575f08f9` | Feature 2.2 | Key Exchange Protocol - Implementation |
| `49cb78d04b` | Feature 1 | Organisation et documentation complète |
| `197a9cec4b` | Feature 1 | Initialisation fiable et robuste du LeMonolith HSM |

---

## Feature Status (2026-01-25)

| Feature | Status | Notes |
|---------|--------|-------|
| 1: AP_HSM init | ✅ DONE | Blocking init ~25s (SITL), async (Pixhawk) |
| 2.1: KeyOrchestrator | ✅ DONE | MK+WK+DEK stored in HSM |
| 2.2: Key Exchange Protocol | ✅ DONE | Monocypher XChaCha20-Poly1305 |
| 3: Dual-DEK Engine | ✅ DONE | TX/RX encryption, deterministic nonce |
| **Mock HSM** | ✅ DONE | Test Pixhawk sans câble TELEM2 |

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
└── mavlink_hsm.py              # Generated MAVLink dialect
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

## Known Issues & Limitations

| Issue | Description | Workaround |
|-------|-------------|------------|
| SITL blocking | HSM init bloque TCP pendant ~25s | GCS client attend 60s pour heartbeat |
| No MAC on payload | ChaCha20 stream cipher sans authentification | CRC MAVLink sert de checksum (pas crypto) |
| Single connection SITL | SITL s'arrête si connexion TCP fermée | Garder connexion ouverte ou reconnecter |
| BAD_DATA spam | Messages chiffrés = BAD_CRC côté GCS Python | Filtrer avec `grep -v BAD_DATA` |
| **uECC crash ARM** | `uECC_compute_public_key()` crash sur Pixhawk5X | Pseudo-PRNG pour WK_public (non-crypto) |
| **WK response missing** | Pixhawk envoie KEY_ACK mais pas WK_EXCHANGE | En investigation |

---

## Next Steps (Future Work)

| Priority | Task | Description | Status |
|----------|------|-------------|--------|
| 1 | **Fix KEP response** | Pixhawk reçoit WK mais ne renvoie pas le sien | ⏳ Investigation |
| 2 | **Câble TELEM2** | Quand reçu: désactiver Mock, brancher HSM | ⏳ Attente câble |
| 3 | RX decrypt Python | Décrypter messages chiffrés dans gcs_kep_client.py | ✅ DONE (Session 3) |
| 4 | Multi-drone | Tester avec 2+ drones mesh | |
| 5 | DEK rotation | Rotation de clés en vol | |
| 6 | HSM backup | Sauvegarde/restauration des clés | |

---

## Test Pixhawk Mock HSM (2026-01-25)

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

**Problème critique découvert:** `uECC_compute_public_key()` crash sur ARM (Pixhawk5X)

**Diagnostic étape par étape:**
```
1. HSM disabled:              ✅ Pixhawk stable (heartbeat OK)
2. HSM + Mock init only:      ✅ Stable
3. + KeyOrchestrator:         ❌ CRASH (printf → hal.console->printf)
4. + printf fix:              ❌ CRASH (toujours)
5. + RNG only:                ✅ Stable
6. + RNG + HKDF:              ✅ Stable
7. + RNG + HKDF + uECC:       ❌ CRASH
```

**Cause:** `uECC_compute_public_key()` de micro-ecc crash sur ARM Cortex-M7.
Possible stack overflow ou incompatibilité P-256 sur cette plateforme.

**Workaround appliqué:** WK_public calculé par pseudo-PRNG au lieu de uECC:
```cpp
// KeyOrchestrator.cpp - init_mission_keys()
// SKIP uECC on Pixhawk (causes crash)
for (int i = 0; i < WK_PUBLIC_SIZE; i++) {
    _wk_public[i] = _wk_private[i % KEY_SIZE] ^ (uint8_t)(i * 17 + 0x5A);
}
```
**Note:** Ce n'est PAS cryptographiquement sûr, mais permet de tester le protocole.

### Résultat avec workaround

```
✅ Pixhawk stable (pas de crash)
✅ KeyOrchestrator: RNG + HKDF fonctionnent
✅ WK_public généré (pseudo-random, non-ECC)
✅ KEP initialisé
✅ KEY_ACK reçu du Pixhawk (SUCCESS, WK_RECEIVED)
❌ Pixhawk ne renvoie toujours pas son WK_EXCHANGE
```

### Prochain problème à résoudre

Le `handle_wk_exchange()` appelle `send_wk_exchange()` mais le message n'arrive pas au GCS.
Possibilités:
1. Message envoyé mais payload_len incorrect
2. GCS ne parse pas correctement (UNKNOWN_12000 avec mauvais format)
3. Canal MAVLink incorrect

**Fichiers à investiguer:**
- `libraries/AP_HSM/KeyExchangeProtocol.cpp`: `send_wk_exchange()`
- `Tools/hsm/gcs_kep_client.py`: parsing de UNKNOWN_12000

### Session 3: Key Exchange SITL - COMPLET ✅

**Date:** 2026-01-25

**Problèmes résolus:**

1. **WK_EXCHANGE non parsé par GCS**
   - Cause: `mavutil.mavlink` n'était pas remplacé par notre dialect HSM
   - Solution: Ajout `mavutil.mavlink = mavlink_hsm` dans gcs_kep_client.py

2. **Attribut incorrect dans DEK_EXCHANGE**
   - Cause: `msg.ephemeral_pub` au lieu de `msg.ephemeral_pubkey`
   - Solution: Correction dans gcs_kep_client.py ligne 496

3. **GCS ne détecté pas par le drone**
   - Cause: Le GCS n'envoyait pas de HEARTBEAT
   - Solution: Le client envoie maintenant des HEARTBEAT pour être détecté par KEP

**Résultat final - SITL avec Real HSM:**
```
✅ HSM init (Feature 1): ~25s bloquant
✅ KeyOrchestrator (Feature 2.1): MK+WK+DEK générés
✅ KeyExchangeProtocol (Feature 2.2): WK bidirectionnel
✅ DEK exchange: ECIES XChaCha20-Poly1305
✅ DualDekEngine (Feature 3): Messages déchiffrés

Test final:
- GCS → Drone: HSM_WK_EXCHANGE (wk=0446acf6...)  ✅
- Drone → GCS: HSM_WK_EXCHANGE                   ✅
- GCS → Drone: HSM_KEY_ACK (WK_RECEIVED)         ✅
- Drone → GCS: HSM_DEK_EXCHANGE                  ✅
- GCS → Drone: HSM_KEY_ACK (DEK_RECEIVED)        ✅
- Drone → GCS: HSM_KEY_ACK                       ✅
- 45 messages decrypted OK                       ✅
```

**Fichiers modifiés cette session:**
- `Tools/hsm/gcs_kep_client.py` - Fix attribute names (ephemeral_pubkey, auth_tag)

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

**Last update:** 2026-01-25 (Session 3) - Key exchange SITL complet! WK+DEK bidirectionnel fonctionne. 45 messages déchiffrés avec succès. Prochaine étape: tester avec Pixhawk.
