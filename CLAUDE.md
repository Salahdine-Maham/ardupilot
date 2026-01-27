# CLAUDE.md - HSM ArduPilot v2.0

HSM LeMonolith v0.6 + ArduPilot - 3-level key hierarchy (MK→WK→DEK)

## Quick Start

### Pixhawk5X + Mock HSM (RECOMMANDÉ)
```bash
# Vérifier Mock activé
grep "AP_HSM_MOCK_ENABLED" libraries/AP_HSM/AP_HSM.h  # Doit être 1

# Compiler et flasher
./waf configure --board Pixhawk5X && ./waf copter && ./waf --upload copter

# Test (HSM sur PC, Mock sur Pixhawk)
python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 --timeout 120
# Résultat: state=COMPLETE wk_recv=True dek_recv=True, Decrypted OK: 42+
```

### SITL + Real HSM
```bash
./waf configure --board sitl && ./waf copter
stdbuf -oL ./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 &
sleep 35
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 60
```

### Dépannage HSM (garbage bytes)
Débrancher/rebrancher USB puis:
```bash
python3 -c "import serial,time;s=serial.Serial('/dev/ttyUSB0',115200,timeout=2);s.write(b'off\r\n');time.sleep(0.5);s.write(b'on\r\n');time.sleep(4);s.write(b'A 00A4040006010203040601\r\n');time.sleep(1.5);print('OK!' if b'9000' in s.read(500) else 'ERROR');s.close()"
```

## Feature Status ✅
| Feature | Status |
|---------|--------|
| 1: AP_HSM init | ✅ Blocking ~25s (SITL), instant (Mock) |
| 2.1: KeyOrchestrator | ✅ MK+WK+DEK in HSM |
| 2.2: Key Exchange Protocol | ✅ ECIES on SITL + Pixhawk |
| 3: Dual-DEK Engine | ✅ TX/RX encryption |
| Mock HSM | ✅ Test sans câble |
| Peer Reset | ✅ 30s timeout |

## Crypto Architecture
```
MK (32B, HSM@0x0100) → HKDF → WK_priv (P-256) → ECIES → DEK (32B)
                              WK_pub (64B)         ↓
                                            peer_deks[sysid]
```
**Algos:** P-256 (micro-ecc), XChaCha20-Poly1305 (Monocypher/PyNaCl), HKDF-SHA256

## HSM Storage & Commands
| Offset | Content | APDU |
|--------|---------|------|
| 0x0100 | MK (32B) | WRITE: `A 00D0010020<hex>` READ: `A 00B0010020` |
| 0x0120 | Wrapped WK_priv | |
| 0x0140 | Wrapped DEK | |
| 0x0160 | HMAC WK | |
| 0x0180 | HMAC DEK | |

**PIN:** `00000000` = `3030303030303030` | **Délais:** ON=3.5s, WRITE=2-3s

## MAVLink Custom Messages
| ID | Name | Usage |
|----|------|-------|
| 12000 | HSM_WK_EXCHANGE | WK public (64B) |
| 12001 | HSM_DEK_EXCHANGE | ECIES: ephemeral(64)+enc_dek(32)+nonce(24)+tag(16) |
| 12002 | HSM_KEY_ACK | Acknowledgment |

## Key Files
```
libraries/AP_HSM/
├── AP_HSM.h/.cpp           # HSM driver (AP_HSM_MOCK_ENABLED toggle)
├── KeyOrchestrator.*       # MK+WK+DEK generation
├── KeyExchangeProtocol.*   # ECIES exchange
├── DualDekEngine.*         # Payload encryption
libraries/micro-ecc/uECC_config.h  # Platform auto-detect (ARM fix)
Tools/hsm/
├── gcs_kep_client.py       # Main GCS test client
├── gcs_hsm.py              # HSM Python driver
├── ecies.py, dual_dek_engine.py
```

## Build
```bash
./waf configure --board sitl && ./waf copter      # SITL
./waf configure --board Pixhawk5X && ./waf copter # Pixhawk
```

## Mock HSM Config
**File:** `libraries/AP_HSM/AP_HSM.h`
```cpp
#define AP_HSM_MOCK_ENABLED 1  // 1=RAM mock, 0=real UART
```
Mock: instant, simule READ/WRITE en RAM | Real: ~25s init, APDU via UART

## SITL vs Pixhawk Init
- **SITL:** Blocking dans setup() (~25s), TCP indisponible pendant init
- **Pixhawk:** Async via scheduler, MAVLink OK immédiatement

## Transition Mock → Real HSM
1. `AP_HSM_MOCK_ENABLED 0` dans AP_HSM.h
2. `hal.serial(2)` dans AP_Vehicle.cpp (TELEM2)
3. Params: `SERIAL2_PROTOCOL=-1, SERIAL2_BAUD=115`
4. Câblage TELEM2: TX→RX, RX→TX, GND→GND

## Pi Zero Bridge (si connexion directe impossible)
Pixhawk n'a pas de USB Host → Pi Zero comme pont:
```
Pixhawk TELEM1 (TTL) ←→ Pi Zero (GPIO UART + USB OTG) ←→ HSM (USB-C)
```
Script: `Tools/hsm/pi_zero_bridge.py`

## Known Issues
| Issue | Fix |
|-------|-----|
| HSM garbage | Unplug/replug USB |
| uECC crash ARM | Fixed: uECC_config.h auto-detect platform |
| ECIES RNG fail | Fixed: uECC_set_rng() in KEP |
| BAD_CRC spam | Normal: encrypted payload |

## Commits clés
- `2c13981c60` Session 6: Fix KEP (RNG + peer reset)
- `75656daedf` Session 5: Fix uECC ARM crash
- `2d7b310a78` Feature 3: DualDekEngine
- `46575f08f9` Feature 2.2: KEP

## Environment
Ubuntu 22.04, Python 3.10+, ArduPilot V4.7.0-dev, HSM LeMonolith v0.6

## Branches
- `kek-HSM` - Main HSM dev (Session 9 OK)
- `KEK_HSM_Gazibo` - Gazebo testing
- `pi-zero-bridge` - Pi Zero config WIP

## Gazebo (Session 10 - EN COURS)
```bash
# Install plugin
cd ~ && git clone https://github.com/ArduPilot/ardupilot_gazebo
cd ardupilot_gazebo && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=RelWithDebInfo && make -j4

# Env vars
export GZ_SIM_SYSTEM_PLUGIN_PATH=$HOME/ardupilot_gazebo/build:$GZ_SIM_SYSTEM_PLUGIN_PATH
export GZ_SIM_RESOURCE_PATH=$HOME/ardupilot_gazebo/models:$HOME/ardupilot_gazebo/worlds:$GZ_SIM_RESOURCE_PATH

# Run
gz sim -v4 -r iris_runway.sdf  # Terminal 1
./build/sitl/bin/arducopter -S -I0 --model gazebo-iris  # Terminal 2
```
Status: Gazebo Sim Harmonic 8.10.0 installé, plugin à installer

---
**Last:** 2026-01-27 Session 9 OK - `python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 --timeout 120`
