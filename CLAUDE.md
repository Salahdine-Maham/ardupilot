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
| Dual HSM | ✅ 2 HSM physiques (drone + GCS) |
| Mission Chiffrée | ⚠️ encrypted_mission.py (SITL instable) |
| Gazebo + Wireshark | ✅ Visualisation + capture |
| Decrypt GCS→Drone | ✅ SET_MODE + COMMAND_LONG (Session 14) |
| CRC Collision Fix | ✅ Decrypt même avec CRC OK (Session 14) |

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
├── encrypted_mission.py    # Mission chiffrée automatisée (Session 13)
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
| HSM garbage | Unplug/replug USB + 3x off/on reset |
| uECC crash ARM | Fixed: uECC_config.h auto-detect platform |
| ECIES RNG fail | Fixed: uECC_set_rng() in KEP |
| BAD_CRC spam | Normal: encrypted payload |
| BAD_CRC plaintext | Fixed: Skip decrypt for msgid 0,12000,12001,12002 |
| CRC collision | Fixed: Decrypt even with FRAMING_OK if peer has DEK (Session 14) |
| find_peer miss | Fixed: compid=0 as wildcard (Session 14) |
| SITL HSM blocking | **WIP**: TCP timeout pendant init 25s → pré-init avec netcat |

## MAVLink CRC & HSM Messages (Session 14)

### Problème Résolu: Plaintext Messages Corrompus
Messages en clair (HEARTBEAT, HSM_*) arrivaient avec BAD_CRC et étaient "déchiffrés",
ce qui les corrompait. Fix dans `GCS_Common.cpp:1960`:

```cpp
const bool is_plaintext_msg = (msg.msgid == MAVLINK_MSG_ID_HEARTBEAT ||
                               msg.msgid == MAVLINK_MSG_ID_HSM_WK_EXCHANGE ||
                               msg.msgid == MAVLINK_MSG_ID_HSM_DEK_EXCHANGE ||
                               msg.msgid == MAVLINK_MSG_ID_HSM_KEY_ACK);
if (is_plaintext_msg) {
    packetReceived(status, msg);  // Process without decryption
}
```

### CRC Extras Table (ardupilotmega.h)
```c
{12000, 144, 70, 70, 3, 4, 5}   // HSM_WK_EXCHANGE: crc=144, len=70
{12001, 14, 138, 138, 3, 0, 1}  // HSM_DEK_EXCHANGE: crc=14, len=138
{12002, 74, 4, 4, 3, 0, 1}      // HSM_KEY_ACK: crc=74, len=4
```

### Dialect Python
- **Fichier:** `Tools/hsm/mavlink_hsm.py` (2.1MB, généré)
- **Source:** `modules/mavlink/message_definitions/v1.0/ardupilotmega.xml`
- **Usage:** Importé par `gcs_kep_client.py` pour messages HSM

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

## Gazebo + HSM (Session 11 - FONCTIONNE ✅)

**Plugin installé:** `~/ardupilot_gazebo/build/libArduPilotPlugin.so`

**Lancer simulation:**
```bash
# Terminal 1: Gazebo
export GZ_SIM_SYSTEM_PLUGIN_PATH=$HOME/ardupilot_gazebo/build:$GZ_SIM_SYSTEM_PLUGIN_PATH
export GZ_SIM_RESOURCE_PATH=$HOME/ardupilot_gazebo/models:$HOME/ardupilot_gazebo/worlds:$GZ_SIM_RESOURCE_PATH
gz sim -v4 -r iris_runway.sdf

# Terminal 2: SITL (IMPORTANT: --model JSON)
cd ~/Code_Sources/ardupilot_claude
source venv-ardupilot/bin/activate
python3 Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --map --console
```

**Commandes vol:**
```
mode guided
arm throttle
takeoff 5
```

## Chiffrement Bidirectionnel ✅ (Session 12)

| Direction | Status | Notes |
|-----------|--------|-------|
| Drone → GCS | ✅ Chiffré | Déchiffré par `gcs_kep_client.py` |
| GCS → Drone | ✅ Chiffré | Via `--interactive` mode |

**Architecture:**
```
gcs_kep_client.py                  Drone (SITL+HSM)
     │                                    │
     │───── Chiffré (MY_DEK) ────────────►│ ← Drone déchiffre avec peer_dek[255]
     │◄──── Chiffré (peer DEK) ──────────│ ← GCS déchiffre avec peer_dek[1]
```

**Commandes interactives chiffrées:**
```bash
# Lancer avec mode interactif
python3 Tools/hsm/gcs_kep_client.py --mavlink /dev/ttyACM0 --hsm /dev/ttyUSB0 -i

# Après key exchange, commandes disponibles:
#   arm       - Arm (chiffré)
#   disarm    - Disarm (chiffré)
#   takeoff N - Takeoff N mètres (chiffré)
#   land      - Land (chiffré)
#   rtl       - Return to launch (chiffré)
#   guided    - Mode GUIDED (chiffré)
#   loiter    - Mode LOITER (chiffré)
#   status    - Stats crypto
#   quit      - Quitter
```

**API Python:**
```python
client = GCSKeyExchangeClient(mavlink=..., hsm_port=...)
client.run()  # Key exchange
# Après échange:
client.send_encrypted_command(400, param1=1)  # ARM
client.send_encrypted_command(22, param7=5)   # TAKEOFF 5m
client.send_encrypted_set_mode(1, 4)          # GUIDED mode
```

## Dual HSM + Gazebo + Wireshark (Session 13) ✅

Configuration avec **2 HSM physiques** : un pour le drone (SITL), un pour le GCS.

### Architecture Dual HSM
```
┌─────────────────┐              ┌─────────────────┐
│   HSM #1        │              │   HSM #2        │
│  /dev/ttyUSB0   │              │  /dev/ttyUSB1   │
│  (Drone keys)   │              │  (GCS keys)     │
└────────┬────────┘              └────────┬────────┘
         │                                │
         ▼                                ▼
┌─────────────────┐   Chiffré    ┌─────────────────┐
│  SITL+Gazebo    │◄────────────►│  GCS Client     │
│  (arducopter)   │   MAVLink    │  (Python)       │
└─────────────────┘              └─────────────────┘
         │
         ▼
    ┌─────────┐
    │ Gazebo  │  ← Visualisation 3D
    └─────────┘
```

### Lancer le test complet
```bash
# Terminal 1: Gazebo
export GZ_SIM_SYSTEM_PLUGIN_PATH=$HOME/ardupilot_gazebo/build:$GZ_SIM_SYSTEM_PLUGIN_PATH
export GZ_SIM_RESOURCE_PATH=$HOME/ardupilot_gazebo/models:$HOME/ardupilot_gazebo/worlds:$GZ_SIM_RESOURCE_PATH
gz sim -v4 -r iris_runway.sdf

# Terminal 2: Wireshark (capture trafic chiffré)
wireshark -k -i lo -f "port 5760 or port 5761 or port 14550"

# Terminal 3: SITL avec HSM #1
stdbuf -oL ./build/sitl/bin/arducopter --model JSON \
  --serial1=uart:/dev/ttyUSB0:115200 \
  --defaults Tools/autotest/default_params/copter.parm,Tools/autotest/default_params/gazebo-iris.parm \
  -I0

# Terminal 4: Mission chiffrée avec HSM #2
source venv-ardupilot/bin/activate
python3 Tools/hsm/encrypted_mission.py --hsm /dev/ttyUSB1
```

### Mission Chiffrée Automatisée
**Script:** `Tools/hsm/encrypted_mission.py`

Exécute une mission complète avec toutes les commandes chiffrées:
1. Mode GUIDED (chiffré)
2. ARM (chiffré)
3. TAKEOFF 20m (chiffré)
4. Navigation 100m Nord (chiffré)
5. Mode CIRCLE (chiffré)
6. RTL (chiffré)
7. LAND (chiffré)

```bash
python3 Tools/hsm/encrypted_mission.py --hsm /dev/ttyUSB1 --mavlink tcp:127.0.0.1:5760
```

### Wireshark - Ce qu'on voit
| Type | Contenu visible |
|------|-----------------|
| HSM_WK_EXCHANGE (12000) | Clé publique WK (64 bytes) |
| HSM_DEK_EXCHANGE (12001) | ECIES: ephemeral + encrypted DEK + nonce + tag |
| HSM_KEY_ACK (12002) | Acknowledgment |
| Commandes (SET_MODE, COMMAND_LONG) | **Payload chiffré** (illisible) |
| Télémétrie (HEARTBEAT, ATTITUDE...) | **Payload chiffré** (BAD_DATA) |

### Résultat Session 13
```
Échange clés: state=COMPLETE wk_recv=True dek_recv=True
HSM #1 (Drone): Clés générées dans HSM physique
HSM #2 (GCS):   MK=FF9978BA WK=2B0514B7 DEK=0DB7E854
Peer DEK échangé: c075ecb9...
Messages déchiffrés: 39+
Commandes TX chiffrées: 7 (toute la mission)
```

## Session 14 - Bugs Corrigés & Leçons Apprises

### Bugs Corrigés ✅

#### 1. Bug `find_peer()` - Wildcard compid
**Problème:** Le drone ne trouvait pas le DEK du GCS (sysid=255) car `get_peer_dek(255, 0)` cherchait `compid=0` exactement, mais le GCS était enregistré avec `compid=190`.

**Fix:** `KeyExchangeProtocol.cpp:95`
```cpp
// Avant: match exact sysid ET compid
if (_peers[i].sysid == sysid && _peers[i].compid == compid)

// Après: compid=0 = wildcard "any"
if (_peers[i].sysid == sysid) {
    if (compid == 0 || _peers[i].compid == compid) {
        return &_peers[i];
    }
}
```

#### 2. Bug CRC Collision
**Problème:** Les COMMAND_LONG (msgid=76) chiffrés avaient parfois `framing=1` (CRC OK par coïncidence!) au lieu de `framing=2` (BAD_CRC). Ils n'étaient donc pas déchiffrés.

**Explication:** Le payload chiffré + CRC extra de msgid=76 peut produire un CRC valide par hasard.

**Fix:** `GCS_Common.cpp:1954` - Déchiffrer aussi les messages avec CRC OK venant de peers chiffrés:
```cpp
if (framing == MAVLINK_FRAMING_OK) {
    // Check if message should be decrypted despite valid CRC (collision case)
    if (peer_dek_ok != nullptr && !is_plaintext_msg && msg.len > 0) {
        // Decrypt despite FRAMING_OK
        ChaCha20XOR(peer_dek_ok, 0, nonce_ok, msg.payload64, decrypted_ok, msg.len);
        memcpy(msg.payload64, decrypted_ok, msg.len);
    }
    packetReceived(status, msg);
}
```

### Résultats Obtenus ✅

Quand SITL est stable:
```
DECRYPT_DEBUG: msgid=11 sysid=255 len=6 peer_dek=YES
DECRYPT_DEBUG: peer_dek[0:8]=0db7e8549ed362cb  ← Même que MY_DEK GCS ✅
DECRYPT_OK: msg 11 from sysid=255 (6 bytes)
```

- Key exchange: `state=COMPLETE wk_recv=True dek_recv=True` ✅
- Déchiffrement drone→GCS: 54 messages ✅
- Déchiffrement GCS→drone: SET_MODE fonctionne ✅
- COMMAND_LONG: Détecté comme CRC collision, déchiffré ✅

### Problème Non Résolu ❌

**SITL crashe/bloque pendant l'init HSM** quand un client Python se connecte:
1. Client Python init son HSM (~11s)
2. Client se connecte à SITL (trigger init HSM drone ~25s bloquant)
3. Pendant l'init bloquante, TCP ferme répétitivement ("EOF on TCP socket")
4. SITL devient instable ou crashe

**Workaround:** Pré-initialiser SITL avec netcat avant de connecter le client Python:
```bash
./build/sitl/bin/arducopter --model + --serial1=uart:/dev/ttyUSB0:115200 ... &
sleep 3
echo "" | timeout 3 nc 127.0.0.1 5760  # Trigger HSM init
sleep 40  # Wait for HSM init to complete
# Now connect Python client
```

**Recommandation:** Tester sur **Pixhawk physique** où l'init HSM est non-bloquante.

### HSM Instable - Reset Agressif

Les HSM LeMonolith deviennent parfois instables (garbage bytes). Reset agressif requis:
```python
for i in range(3):
    s.write(b'off\r\n'); time.sleep(1)
    s.write(b'on\r\n'); time.sleep(5)
    s.reset_input_buffer()
s.write(b'A 00A4040006010203040601\r\n')  # Test SELECT
```

### Fichiers Modifiés Session 14

| Fichier | Modification |
|---------|--------------|
| `KeyExchangeProtocol.cpp:95` | Fix `find_peer()` wildcard compid |
| `GCS_Common.cpp:1954` | Fix CRC collision - decrypt même avec CRC OK |
| `GCS_Common.cpp:1938` | Debug FRAME_DEBUG amélioré |
| `gcs_kep_client.py:549` | Debug ENCRYPT avec MY_DEK et nonce |

### Leçons Clés

1. **CRC MAVLink peut coïncider** - Un payload chiffré peut produire un CRC valide par hasard
2. **compid=0 doit être wildcard** - Pour `get_peer_dek()` qui ne connaît pas le compid exact
3. **SITL blocking init problématique** - L'init HSM bloquante cause des timeouts TCP
4. **HSM nécessite reset multiple** - 3 cycles off/on pour état propre garanti

---
**Last:** 2026-01-27 Session 14 - Fix find_peer wildcard + Fix CRC collision. Déchiffrement bidirectionnel fonctionne quand SITL stable. Problème init HSM bloquante non résolu → tester Pixhawk.
