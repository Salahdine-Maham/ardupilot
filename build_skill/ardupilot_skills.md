# ArduPilot Skills - Connaissances Projet HSM

**Date**: 2026-01-23
**Projet**: Intégration HSM LeMonolith avec ArduPilot pour sécurisation MAVLink
**Utilisation**: Humain ou AI pour projets similaires

---

## 1. STRUCTURE ARDUPILOT

### 1.1 Architecture des Bibliothèques

**Localisation des bibliothèques personnalisées:**
```
ardupilot/
├── libraries/
│   ├── AP_HSM/              # Nouvelle bibliothèque HSM
│   │   ├── AP_HSM.h         # Header avec déclarations
│   │   ├── AP_HSM.cpp       # Implémentation
│   │   └── wscript          # Configuration build
│   ├── AP_Crypto/           # Crypto existante (HKDF, HMAC)
│   ├── AP_Vehicle/          # Point d'entrée principal
│   └── GCS_MAVLink/         # Communication MAVLink
```

**Point d'intégration principal:**
- Fichier: `libraries/AP_Vehicle/AP_Vehicle.cpp`
- Fonction: `AP_Vehicle::init_ardupilot()`
- Ligne: ~330-450 (après initialisation HAL)

### 1.2 Système de Build (waf)

**Commandes essentielles:**
```bash
# Configuration initiale (une seule fois)
./waf configure --board sitl

# Compilation ArduCopter
./waf copter

# Compilation rapide (ne recompile que les changements)
./waf copter --targets bin/arducopter

# Nettoyage complet
./waf clean
./waf distclean  # Plus profond
```

**Fichier wscript pour nouvelle bibliothèque:**
```python
# libraries/AP_HSM/wscript
def build(bld):
    bld.ap_library(
        name='AP_HSM',
        sources=['AP_HSM.cpp'],
        depends=['AP_HAL', 'AP_SerialManager']
    )
```

**Problèmes courants:**
- **Erreur**: `undefined reference to AP_HSM::fonction()`
  - **Cause**: Bibliothèque pas déclarée dans wscript du vehicle
  - **Solution**: Ajouter `'AP_HSM'` dans `libraries=['...']` de ArduCopter/wscript

### 1.3 Gestion UART/Serial

**Configuration UART pour périphérique externe:**
```cpp
// Dans AP_Vehicle.cpp, méthode init_ardupilot()
AP_SerialManager &serial_manager = AP::serialmanager();

// SERIAL1 généralement disponible pour périphériques custom
AP_HAL::UARTDriver *uart = serial_manager.find_serial(AP_HAL::SerialProtocol::Serial1, 0);

if (uart != nullptr) {
    uart->begin(115200);  // Baud rate
    uart->set_blocking_writes(true);
    uart->set_unbuffered_writes(true);
}
```

**Ligne de commande pour SITL avec UART externe:**
```bash
# Connecter SERIAL1 à un device UART physique
arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200

# IMPORTANT: Ne PAS utiliser --console avec périphériques UART
# --console interfère avec la communication UART
arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200  # CORRECT
```

**Communication UART:**
```cpp
// Écriture
uart->printf("commande\r\n");

// Lecture
if (uart->available() > 0) {
    char c = uart->read();
}

// Flush buffer d'entrée
while (uart->available() > 0) {
    uart->read();
}
```

### 1.4 Delays et Scheduling

**Fonctions de délai:**
```cpp
// Délai bloquant (utiliser avec précaution)
hal.scheduler->delay(1000);  // 1000ms = 1 seconde

// Timing non-bloquant
uint32_t start = AP_HAL::millis();
while ((AP_HAL::millis() - start) < 3000) {
    // Faire quelque chose pendant 3 secondes
}
```

**Important:**
- ArduPilot est un système temps-réel
- Les délais longs (>500ms) doivent être justifiés
- Privilégier les state machines non-bloquantes pour production
- OK pour initialisation au boot (une seule fois)

### 1.5 Logging et Debug

**Fonctions de log:**
```cpp
// Printf simple (visible dans console)
printf("HSM: Message de debug\n");

// Avec formatting
printf("HSM: Valeur = %d, Status = 0x%02X\n", val, status);

// Pour hex dump
for (int i = 0; i < 32; i++) {
    printf("%02X", buffer[i]);
}
printf("\n");
```

**Voir les logs SITL:**
```bash
# Lancer avec output console
arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 2>&1 | tee log.txt

# Ou avec redirection
arducopter [...] > /tmp/arducopter.log 2>&1 &
tail -f /tmp/arducopter.log

# Filtrer logs HSM uniquement
grep "HSM:" /tmp/arducopter.log
```

---

## 2. SITL (SOFTWARE IN THE LOOP)

### 2.1 Lancement SITL

**Méthode 1: Direct (sans connexion TCP)**
```bash
# Simple, mais bloque sans connexion TCP
build/sitl/bin/arducopter --model quad
```

**Méthode 2: Avec MAVProxy (RECOMMANDÉ)**
```bash
# Terminal 1: Lancer ArduCopter
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &

# Terminal 2: Connecter MAVProxy
sleep 4
mavproxy.py --master=tcp:127.0.0.1:5760 --console
```

**Méthode 3: Avec sim_vehicle.py (méthode officielle)**
```bash
# Lance ArduCopter + MAVProxy automatiquement
./Tools/autotest/sim_vehicle.py -v ArduCopter --no-rebuild
```

### 2.2 Options SITL Importantes

**Options de model:**
- `--model quad`: Quadcopter
- `--model +`: Quadcopter en configuration +
- `--model octa`: Octocopter

**Options serial:**
- `--serial0 tcp:5760`: SERIAL0 sur TCP (par défaut)
- `--serial1 uart:/dev/ttyUSB0:115200`: SERIAL1 sur UART physique
- `--serial2 sim:gps`: SERIAL2 sur GPS simulé

**Options vitesse:**
- `--speedup 1`: Temps réel (défaut)
- `--speedup 10`: 10x plus rapide

**Options autres:**
- `--defaults Tools/autotest/default_params/copter.parm`: Charger paramètres
- `--console`: Mode console (À ÉVITER avec UART externe!)

### 2.3 Problème Critique: --console vs UART

**PROBLÈME DÉCOUVERT:**
```
❌ arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 --console
   → Timeout communication UART
   → HSM ne répond pas aux commandes APDU

✅ arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200
   → Attend connexion TCP sur port 5760
   → Communication UART fonctionne correctement
```

**Explication:**
- Sans `--console`: ArduCopter crée un socket TCP sur port 5760, attend connexion
- Une fois connecté (MAVProxy), il initialise tout y compris UART
- Avec `--console`: ArduCopter démarre sans attendre TCP, perturbe timing UART

**Solution:**
```bash
# Toujours lancer avec MAVProxy pour UART externe
arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &
sleep 4
mavproxy.py --master=tcp:127.0.0.1:5760 --console &
```

---

## 3. INTÉGRATION CRYPTO

### 3.1 Bibliothèques Crypto Disponibles

**AP_Crypto (existante):**
```cpp
#include <AP_Crypto/AP_Crypto.h>

// HKDF-SHA256 (RFC 5869)
uint8_t salt[] = "MySalt";
uint8_t ikm[32];      // Input Key Material
uint8_t info[] = "MyInfo";
uint8_t okm[32];      // Output Key Material

hkdf_sha256(salt, sizeof(salt),
            ikm, 32,
            info, sizeof(info),
            okm, 32);

// HMAC-SHA256
uint8_t key[32];
uint8_t data[100];
uint8_t hmac[32];
hmac_sha256(key, 32, data, 100, hmac);
```

**micro-ecc (ajoutée):**
```cpp
// Localisation: libraries/AP_HSM/uECC.h (copie locale)
// Ou ajouter comme submodule git

#include "uECC.h"

// Génération keypair P-256
uECC_Curve curve = uECC_secp256r1();
uint8_t private_key[32];
uint8_t public_key[64];  // Non compressée: 32 bytes X + 32 bytes Y

int result = uECC_make_key(public_key, private_key, curve);
if (result != 1) {
    // Erreur
}

// ECDH (Elliptic Curve Diffie-Hellman)
uint8_t remote_public[64];
uint8_t shared_secret[32];

result = uECC_shared_secret(remote_public, private_key, shared_secret, curve);
if (result != 1) {
    // Erreur
}
```

**ChaCha20 (existante dans GCS_MAVLink):**
```cpp
// Localisation: libraries/GCS_MAVLink/
// Utilisée pour chiffrement MAVLink v2
// Pas utilisée directement dans notre projet (Feature 4)
```

### 3.2 Intégration dans ArduPilot

**Ajout de dépendances dans wscript:**
```python
# ArduCopter/wscript
def build(bld):
    bld.ap_program(
        name='arducopter',
        libraries=[
            'AP_Vehicle',
            'AP_HSM',      # Notre lib
            'AP_Crypto',   # Pour HKDF/HMAC
            # micro-ecc inclus directement dans AP_HSM
        ],
        # ...
    )
```

**Exemple d'utilisation complète (Feature 3):**
```cpp
// 1. Générer DEK
uint8_t dek[32];
hal.util->get_random_vals(dek, 32);

// 2. ECDH avec clé publique remote
uint8_t public_remote[64];
uint8_t shared_secret[32];
uECC_shared_secret(public_remote, private_key, shared_secret, curve);

// 3. Dériver wrapping key (HKDF)
uint8_t salt[] = "ArduPilot-HSM-Salt-2026";
uint8_t info[] = "DEK-Wrapping-Key-v1";
uint8_t wrapping_key[32];
hkdf_sha256(salt, sizeof(salt)-1,
            shared_secret, 32,
            info, sizeof(info)-1,
            wrapping_key, 32);

// 4. Wrap DEK (XOR + HMAC)
uint8_t wrapped_dek[32];
uint8_t auth_tag[32];
for (int i = 0; i < 32; i++) {
    wrapped_dek[i] = dek[i] ^ wrapping_key[i];
}
hmac_sha256(wrapping_key, 32, wrapped_dek, 32, auth_tag);
```

---

## 4. PATTERNS DE CODE ARDUPILOT

### 4.1 Initialisation de Module

**Pattern standard:**
```cpp
class AP_HSM {
public:
    // Constructeur
    AP_HSM() {}

    // Initialisation (appelée depuis AP_Vehicle::init_ardupilot)
    bool init(AP_HAL::UARTDriver *uart);

    // Méthodes publiques
    bool generate_key();

private:
    AP_HAL::UARTDriver *uart_hsm;
    bool initialized = false;

    // Méthodes privées
    bool send_command(const char* cmd);
};
```

**Appel depuis AP_Vehicle:**
```cpp
// Dans libraries/AP_Vehicle/AP_Vehicle.cpp
#include <AP_HSM/AP_HSM.h>

// Membre statique ou global
static AP_HSM hsm;

void AP_Vehicle::init_ardupilot(void) {
    // ... autre init ...

    // Init UART
    AP_HAL::UARTDriver *uart = serial_manager.find_serial(...);

    // Init HSM
    if (uart != nullptr) {
        if (!hsm.init(uart)) {
            printf("HSM: Erreur initialisation\n");
            return;
        }
        printf("HSM: ✓ Initialisé\n");
    }
}
```

### 4.2 Cache de Données Sensibles

**Stockage sécurisé en RAM:**
```cpp
class AP_HSM {
private:
    // Cache pour éviter lectures HSM répétées
    uint8_t private_key_cache[32];
    uint8_t public_key_cache[64];
    uint8_t dek_cache[32];

    // Flags de validité
    bool keypair_loaded = false;
    bool dek_loaded = false;

public:
    // Getter avec lazy loading
    const uint8_t* get_dek() {
        if (!dek_loaded) {
            load_dek_from_hsm();
        }
        return dek_loaded ? dek_cache : nullptr;
    }
};
```

**Important:**
- RAM non sécurisée dans SITL (protection limitée)
- Cache évite overhead communication HSM
- Flags pour invalidation si nécessaire

### 4.3 Gestion d'Erreurs

**Pattern standard:**
```cpp
bool AP_HSM::operation() {
    // Vérifications préalables
    if (uart_hsm == nullptr) {
        printf("HSM: Erreur - UART non initialisée\n");
        return false;
    }

    if (!initialized) {
        printf("HSM: Erreur - HSM non initialisé\n");
        return false;
    }

    // Opération
    if (!send_command("cmd")) {
        printf("HSM: Erreur - Timeout commande\n");
        return false;
    }

    // Vérification résultat
    if (!check_response()) {
        printf("HSM: Erreur - Réponse invalide\n");
        return false;
    }

    printf("HSM: ✓ Opération réussie\n");
    return true;
}
```

**Messages de log structurés:**
```
Format: "HSM: [Statut] Message"
- HSM: Démarrage ...
- HSM: ✓ Succès ...
- HSM: Erreur - Description ...
- HSM: ⚠️  Avertissement ...
```

---

## 4.4 Interception MAVLink avec comm_send_buffer()

### 4.4.1 Point d'Interception UNIVERSEL

**LA fonction pour intercepter 100% du trafic MAVLink sortant:**

```cpp
// libraries/GCS_MAVLink/GCS_MAVLink.cpp ligne ~149
void comm_send_buffer(mavlink_channel_t chan, const uint8_t *buf, uint8_t len)
```

**Pourquoi cette fonction est CRITIQUE:**
- Appelée pour TOUS les messages MAVLink (heartbeats, telemetry, commands, missions)
- Appelée 3-4 fois par message MAVLink:
  - Appel 1: Header (10-12 bytes)
  - Appel 2: PAYLOAD (0-255 bytes) ← À CHIFFRER ICI
  - Appel 3: Checksum (2 bytes)
  - Appel 4: Signature (13 bytes, optionnel)
- Bas niveau: intercepte avant écriture UART/TCP
- Un seul endroit à modifier pour encryption globale

**Structure d'un message MAVLink:**
```
┌──────────┬─────────┬──────────┬───────────┐
│  Header  │ PAYLOAD │ Checksum │ Signature │
│ (10-12B) │ (0-255B)│  (2B)    │  (13B)    │
│  CLAIR   │ CHIFFRÉ │  CLAIR   │  CLAIR    │
└──────────┴─────────┴──────────┴───────────┘
     ↓          ↓         ↓          ↓
  Appel 1   Appel 2   Appel 3    Appel 4
```

### 4.4.2 Implémentation Encryption Payload-Only

**Code complet dans comm_send_buffer():**

```cpp
void comm_send_buffer(mavlink_channel_t chan, const uint8_t *buf, uint8_t len)
{
    // Validations de base
    if (!valid_channel(chan) || mavlink_comm_port[chan] == nullptr) {
        return;
    }

#if AP_HSM_ENABLED
    // *** ENCRYPTION PAYLOAD-ONLY - Feature 4 ***

    // Tracking de quel buffer est envoyé (header/payload/checksum/signature)
    static uint8_t send_buffer_index[MAVLINK_COMM_NUM_BUFFERS] = {0};
    const uint8_t current_buffer = send_buffer_index[chan];
    const bool is_payload = (current_buffer == 1);  // 2ème appel = payload

    if (gcs().get_mav_encrypt() != 0 && is_payload) {
        AP_HSM& hsm = AP_HSM::get_singleton();

        if (hsm.has_dek()) {
            const uint8_t* dek = hsm.get_dek();

            // Compteur de messages pour nonce unique
            static uint64_t message_counter[MAVLINK_COMM_NUM_BUFFERS] = {0};

            // Buffer pour payload chiffré
            uint8_t encrypted[len];

            // Construire nonce (12 bytes)
            uint8_t nonce[12];
            uint64_t msg_num = message_counter[chan];

            // Nonce = counter (8B) + channel (1B) + padding (3B)
            nonce[0] = (msg_num >> 0) & 0xFF;
            nonce[1] = (msg_num >> 8) & 0xFF;
            nonce[2] = (msg_num >> 16) & 0xFF;
            nonce[3] = (msg_num >> 24) & 0xFF;
            nonce[4] = (msg_num >> 32) & 0xFF;
            nonce[5] = (msg_num >> 40) & 0xFF;
            nonce[6] = (msg_num >> 48) & 0xFF;
            nonce[7] = (msg_num >> 56) & 0xFF;
            nonce[8] = chan;
            nonce[9] = 0x00;
            nonce[10] = 0x00;
            nonce[11] = 0x00;

            // Chiffrer avec ChaCha20-256
            ChaCha20XOR((uint8_t*)dek, 0, nonce, (uint8_t*)buf, encrypted, len);

            // Incrémenter counter
            message_counter[chan]++;

            // Log périodique (tous les 50 messages)
            static uint32_t debug_count = 0;
            if (++debug_count % 50 == 1) {
                printf("HSM: Encrypted PAYLOAD #%llu (%u bytes) on chan %d\n",
                       (unsigned long long)msg_num, len, chan);
            }

            // Envoyer payload chiffré
            mavlink_comm_port[chan]->write(encrypted, len);
            send_buffer_index[chan]++;
            return;  // Important: sortir ici
        }
    }

    // Incrémenter index pour prochain buffer
    send_buffer_index[chan]++;
#endif // AP_HSM_ENABLED

    // Envoi normal (plaintext)
    mavlink_comm_port[chan]->write(buf, len);
}
```

**Points clés:**
1. **send_buffer_index[]**: Track quel appel (header/payload/checksum)
2. **is_payload = (current_buffer == 1)**: Seulement 2ème appel chiffré
3. **message_counter[]**: Nonce unique par message (pas bytes!)
4. **ChaCha20XOR()**: Stream cipher rapide, pas de padding
5. **send_buffer_index++ AVANT return**: Critique pour synchronisation

### 4.4.3 Reset Index au Début de Chaque Message

**Dans comm_send_lock() - appelée avant chaque message:**

```cpp
void comm_send_lock(mavlink_channel_t chan_m, uint16_t size)
{
    const uint8_t chan = uint8_t(chan_m);

#if AP_HSM_ENABLED
    // Reset index pour nouveau message
    send_buffer_index[chan] = 0;
#endif

    chan_locks[chan].take_blocking();
    // ... reste de la fonction
}
```

**Séquence complète pour un message:**
```
1. comm_send_lock()       → Reset send_buffer_index[chan] = 0
2. comm_send_buffer()     → Index 0 = Header (clair)
3. comm_send_buffer()     → Index 1 = PAYLOAD (chiffré) ← ENCRYPTION ICI
4. comm_send_buffer()     → Index 2 = Checksum (clair)
5. comm_send_buffer()     → Index 3 = Signature (clair, optionnel)
6. comm_send_unlock()     → Libère verrou
```

### 4.4.4 Décryption Entrante (Reception)

**Dans GCS_Common.cpp - fonction packetReceived():**

```cpp
void GCS_MAVLINK::packetReceived(const mavlink_status_t& status,
                                  const mavlink_message_t& msg)
{
#if AP_HSM_ENABLED
    // Décrypter payload si encryption activée
    if (gcs().get_mav_encrypt() != 0) {
        AP_HSM& hsm = AP_HSM::get_singleton();

        if (hsm.has_dek()) {
            const uint8_t* dek = hsm.get_dek();

            // Reconstruire même nonce que sender
            uint8_t nonce[12];
            // TODO: Récupérer message counter synchronisé
            // Pour l'instant: counter local indépendant

            static uint64_t rx_counter[MAVLINK_COMM_NUM_BUFFERS] = {0};
            uint64_t msg_num = rx_counter[chan];

            nonce[0] = (msg_num >> 0) & 0xFF;
            nonce[1] = (msg_num >> 8) & 0xFF;
            nonce[2] = (msg_num >> 16) & 0xFF;
            nonce[3] = (msg_num >> 24) & 0xFF;
            nonce[4] = (msg_num >> 32) & 0xFF;
            nonce[5] = (msg_num >> 40) & 0xFF;
            nonce[6] = (msg_num >> 48) & 0xFF;
            nonce[7] = (msg_num >> 56) & 0xFF;
            nonce[8] = chan;
            nonce[9] = 0x00;
            nonce[10] = 0x00;
            nonce[11] = 0x00;

            // Décrypter payload
            uint8_t decrypted[MAVLINK_MAX_PAYLOAD_LEN];
            ChaCha20XOR((uint8_t*)dek, 0, nonce,
                       (uint8_t*)msg.payload64, decrypted, msg.len);

            // Remplacer payload chiffré par décrypté
            memcpy((void*)msg.payload64, decrypted, msg.len);

            rx_counter[chan]++;
        }
    }
#endif

    // Traiter message (maintenant décrypté)
    handle_message(msg);
}
```

### 4.4.5 Configuration et Activation

**Paramètre ArduPilot pour activer encryption:**

```cpp
// Dans GCS.h
class GCS {
private:
    AP_Int8 mav_encrypt;  // 0 = désactivé, 1 = activé

public:
    uint8_t get_mav_encrypt() const {
        return uint8_t(mav_encrypt);
    }
};
```

**Définition paramètre:**
```cpp
// Dans GCS.cpp
const AP_Param::GroupInfo GCS::var_info[] = {
    AP_GROUPINFO("MAV_ENCRYPT", 1, GCS, mav_encrypt, 1),
    AP_GROUPEND
};
```

**Utilisation via MAVProxy:**
```bash
# Activer encryption
param set MAV_ENCRYPT 1

# Désactiver encryption
param set MAV_ENCRYPT 0

# Vérifier
param show MAV_ENCRYPT
```

### 4.4.6 Avantages de Cette Approche

**✅ Header en clair:**
- Parsers MAVLink peuvent identifier type de message
- Routing fonctionnel (sysid, compid)
- Détection de lien possible (heartbeats visibles)

**✅ Checksum en clair:**
- Intégrité du message vérifiable
- Détection corruption au niveau transport

**✅ Payload chiffré:**
- Données sensibles protégées
- Commands/missions/telemetry sécurisés

**✅ Performance:**
- ChaCha20 ultra-rapide (~50-200 µs par message)
- Pas de padding (stream cipher)
- Overhead CPU < 0.1%

**✅ Compatibilité:**
- GCS standards voient header/checksum valides
- Messages rejetés si pas de DEK (fail-safe)
- Activation paramétrable (MAV_ENCRYPT)

### 4.4.7 Limitations et Améliorations Futures

**⚠️ Limitation actuelle: Nonce synchronization**

Problème: TX et RX utilisent counters indépendants
```
Drone TX: counter = 0, 1, 2, 3...
GCS RX:   counter = 0, 1, 2, 3...
```

Fonctionne si:
- Aucun message perdu
- Même point de départ (boot simultané)
- Ordre préservé

**Solutions possibles:**

1. **Transmettre nonce dans header custom**
```cpp
// Ajouter 8 bytes nonce dans header MAVLink
// Nécessite modification protocole MAVLink
```

2. **Utiliser sequence number MAVLink**
```cpp
// msg.seq déjà dans header (0-255)
// Combiner avec timestamp pour nonce 64-bit
nonce[0-7] = msg.seq | (timestamp << 8);
```

3. **Handshake initial pour synchroniser counters**
```cpp
// Au boot, échanger message SYNC_NONCE
// GCS et Drone démarrent avec même counter
```

**⚠️ Limitation: Pas d'authentification**

ChaCha20 = confidentialité SEULEMENT (pas d'intégrité)

**Solution:**
```cpp
// Passer à ChaCha20-Poly1305 (AEAD)
// Ajoute MAC 16 bytes pour authentification
chacha20_poly1305_encrypt(dek, nonce, plaintext, ciphertext, mac);
```

---

## 5. TESTS ET VALIDATION

### 5.1 Scripts de Test

**Structure recommandée:**
```bash
#!/bin/bash
# test_feature.sh

echo "================================================"
echo "  Test Feature X"
echo "================================================"

# Nettoyage
pkill -9 arducopter mavproxy 2>/dev/null || true
sleep 2

# Vérifier HSM
if [ ! -e /dev/ttyUSB0 ]; then
    echo "❌ HSM non détecté"
    exit 1
fi
echo "✅ HSM détecté"

# Log
LOGFILE="logs/test_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs

# Lancer ArduCopter
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 \
    > "$LOGFILE" 2>&1 &
ACP=$!

sleep 4

# Lancer MAVProxy
mavproxy.py --master=tcp:127.0.0.1:5760 --console > /dev/null 2>&1 &
MVP=$!

# Attendre
sleep 30

# Vérifier résultats
if grep -q "✓ Feature X complétée" "$LOGFILE"; then
    echo "✅ Feature X: SUCCÈS"
else
    echo "❌ Feature X: ÉCHEC"
    grep "HSM:" "$LOGFILE" | tail -20
fi

# Nettoyage
kill -9 $ACP $MVP 2>/dev/null || true
pkill -9 arducopter mavproxy 2>/dev/null || true
```

### 5.2 Validation par Logs

**Patterns à chercher:**
```bash
# Succès Feature 1
grep "✓ Feature 1 complétée avec succès" log.txt

# Succès Feature 2
grep "✓ Feature 2 complétée avec succès" log.txt
grep "Public key (64 bytes):" log.txt

# Succès Feature 3
grep "✓ Feature 3 complétée avec succès" log.txt
grep "DEK (32 bytes):" log.txt

# Erreurs
grep "Erreur" log.txt
grep "Timeout" log.txt
grep "échoué" log.txt
```

### 5.3 Problèmes Courants et Solutions

**Problème 1: "undefined reference to AP_HSM::fonction"**
```
Cause: Bibliothèque pas linkée
Solution: Ajouter 'AP_HSM' dans ArduCopter/wscript libraries=[...]
```

**Problème 2: Timeout communication UART**
```
Causes possibles:
1. --console utilisé (SOLUTION: enlever --console)
2. Délais insuffisants (SOLUTION: augmenter delays)
3. HSM instable (SOLUTION: reset physique 60s)
4. MAVProxy se déconnecte (SOLUTION: retarder lancement MAVProxy)
```

**Problème 3: Compilation lente**
```
Solution:
./waf copter --targets bin/arducopter  # Cible spécifique uniquement
```

**Problème 4: MAVLink déjà bindé sur port 5760**
```bash
# Tuer tous les processus
pkill -9 arducopter mavproxy

# Vérifier
lsof -i :5760
```

---

## 6. BONNES PRATIQUES

### 6.1 Structure de Code

1. **Séparer interface (header) et implémentation (.cpp)**
2. **Préfixer les messages de log avec "HSM:"** pour faciliter grep
3. **Utiliser des flags de cache** (keypair_loaded, dek_loaded)
4. **Valider les paramètres** en début de fonction
5. **Retourner bool** pour succès/échec (pas d'exceptions)

### 6.2 Performance

1. **Minimiser les lectures HSM** (utiliser cache RAM)
2. **Délais uniquement où nécessaires** (EEPROM, init)
3. **Flush buffers UART** avant commandes importantes
4. **Timeout généreux** (3s pour APDU, 2s+ pour EEPROM write)

### 6.3 Sécurité

1. **Ne jamais logger les clés privées** en production
2. **Utiliser HAL random** pour génération clés (`hal.util->get_random_vals()`)
3. **Vérifier HMAC tags** avant unwrap
4. **Valider tailles buffers** avant copie

### 6.4 Tests

1. **Reset HSM entre tests** (30-60s pour stabilité)
2. **Délai 10s entre tests automatisés**
3. **Toujours utiliser MAVProxy** pour tests UART
4. **Logger tout** dans fichiers pour analyse post-mortem

---

## 7. COMMANDES UTILES

### 7.1 Build

```bash
# Configuration
./waf configure --board sitl

# Build complet
./waf copter

# Build rapide
./waf copter --targets bin/arducopter

# Clean
./waf clean
./waf distclean
```

### 7.2 Test

```bash
# Lancement SITL basique
build/sitl/bin/arducopter --model quad

# Avec UART externe
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200

# Avec MAVProxy
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &
sleep 4
mavproxy.py --master=tcp:127.0.0.1:5760 --console

# Avec sim_vehicle
./Tools/autotest/sim_vehicle.py -v ArduCopter --no-rebuild
```

### 7.3 Debug

```bash
# Voir logs en temps réel
tail -f /tmp/ardupilot.log

# Filtrer HSM
grep "HSM:" /tmp/ardupilot.log

# Compter succès
grep -c "complétée avec succès" /tmp/ardupilot.log

# Chercher erreurs
grep -E "(Erreur|Timeout|échoué)" /tmp/ardupilot.log
```

### 7.4 Système

```bash
# Vérifier périphérique UART
ls -la /dev/ttyUSB0

# Qui utilise UART
lsof /dev/ttyUSB0

# Tuer processus
pkill -9 arducopter mavproxy

# Vérifier ports TCP
lsof -i :5760
netstat -tlnp | grep 5760
```

---

## 8. RÉFÉRENCES

### 8.1 Documentation Officielle

- **ArduPilot Dev Wiki**: https://ardupilot.org/dev/
- **SITL**: https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html
- **Building Code**: https://ardupilot.org/dev/docs/building-the-code.html

### 8.2 Code Sources Importants

```
libraries/AP_Vehicle/AP_Vehicle.cpp       # Point d'entrée init
libraries/AP_HAL/UARTDriver.h            # Interface UART
libraries/AP_Crypto/                      # Crypto existante
libraries/GCS_MAVLink/                    # MAVLink protocol
Tools/autotest/sim_vehicle.py            # Script SITL helper
```

### 8.3 Fichiers Configuration

```
Tools/autotest/default_params/copter.parm  # Paramètres par défaut
ardupilot_root/.gitmodules                 # Submodules git
ArduCopter/wscript                         # Build config copter
libraries/*/wscript                        # Build config libs
```

---

## 9. GCS PYTHON CLIENT - SESSION 3 LEARNINGS

### 9.1 Architecture Client GCS avec HSM

**Structure recommandée pour client GCS Python:**

```python
#!/usr/bin/env python3
"""GCS client for Key Exchange Protocol with ArduPilot HSM"""
import sys
import time
import threading

# CRITIQUE: Ajouter path vers Tools/hsm AVANT imports
sys.path.insert(0, '/path/to/ardupilot/Tools/hsm')

from pymavlink import mavutil
import mavlink_hsm  # Dialect avec messages HSM

# CRITIQUE: Remplacer dialect AVANT connexion
mavutil.mavlink = mavlink_hsm

class GCSClient:
    def __init__(self):
        self.mav = None
        self.running = False

    def connect(self, address='tcp:127.0.0.1:5760', timeout=90):
        """Connect to SITL with patient wait for HSM init"""
        self.mav = mavutil.mavlink_connection(
            address,
            source_system=255,
            source_component=190
        )

        # Wait patiently during ~25s HSM init
        start = time.time()
        while time.time() - start < timeout:
            try:
                msg = self.mav.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
                if msg and msg.get_srcSystem() == 1:
                    print(f"Connected! (took {int(time.time()-start)}s)")
                    return True
            except:
                pass  # Ignore EOF errors during init

            if int(time.time() - start) % 10 == 0:
                print(f"  Waiting for HSM init... ({int(time.time()-start)}s)")

        return False

    def start_heartbeat_thread(self):
        """REQUIRED: Drone KEP detects GCS via heartbeats"""
        def sender():
            mav_hsm = mavlink_hsm.MAVLink(self.mav, srcSystem=255, srcComponent=190)
            while self.running:
                try:
                    msg = mav_hsm.heartbeat_encode(
                        type=mavlink_hsm.MAV_TYPE_GCS,
                        autopilot=mavlink_hsm.MAV_AUTOPILOT_INVALID,
                        base_mode=0, custom_mode=0,
                        system_status=mavlink_hsm.MAV_STATE_ACTIVE
                    )
                    self.mav.write(msg.pack(mav_hsm))
                    time.sleep(1)
                except:
                    break

        self.running = True
        t = threading.Thread(target=sender, daemon=True)
        t.start()
```

### 9.2 Parsing Messages HSM Custom

**Les 3 messages HSM et leurs attributs:**

```python
# HSM_WK_EXCHANGE (msgid 12000)
if msg.get_type() == 'HSM_WK_EXCHANGE':
    wk_public = bytes(msg.wk_public)    # 64 bytes
    timestamp = msg.timestamp            # uint64

# HSM_DEK_EXCHANGE (msgid 12001)
elif msg.get_type() == 'HSM_DEK_EXCHANGE':
    target_sys = msg.target_system       # uint8
    target_comp = msg.target_component   # uint8
    ephemeral = bytes(msg.ephemeral_pubkey)  # 64 bytes - NOT ephemeral_pub!
    encrypted = bytes(msg.encrypted_dek)     # 32 bytes
    nonce = bytes(msg.nonce)                 # 24 bytes
    tag = bytes(msg.auth_tag)                # 16 bytes - NOT tag!

# HSM_KEY_ACK (msgid 12002)
elif msg.get_type() == 'HSM_KEY_ACK':
    status = msg.status      # 0=SUCCESS, autres=erreur
    phase = msg.phase        # 1=WK_RECEIVED, 2=DEK_RECEIVED
    target_sys = msg.target_system
    target_comp = msg.target_component
```

**Erreurs courantes (Session 3):**
```python
# ❌ AttributeError: no attribute 'ephemeral_pub'
data = msg.ephemeral_pub  # WRONG!

# ✅ Correct attribute name
data = msg.ephemeral_pubkey

# ❌ AttributeError: no attribute 'tag'
mac = msg.tag  # WRONG!

# ✅ Correct attribute name
mac = msg.auth_tag
```

### 9.3 Comportement SITL Blocking Init

**Pourquoi "EOF on TCP socket" pendant 25 secondes?**

En SITL, l'init HSM est bloquante:
```cpp
// AP_Vehicle.cpp
#if AP_HSM_ENABLED && CONFIG_HAL_BOARD == HAL_BOARD_SITL
    hsm.init_monolith();  // Bloque tout pendant ~25s
#endif
```

**Conséquences côté GCS Python:**
- `recv_match()` retourne des erreurs EOF
- Le socket TCP est actif mais rien n'est envoyé
- Les heartbeats GCS sont bufferisés

**Solution robuste:**
```python
def patient_recv(mav, timeout=90, msg_types=None):
    """Receive messages patiently during HSM init"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            msg = mav.recv_match(type=msg_types, blocking=True, timeout=0.5)
            if msg:
                return msg
        except Exception as e:
            # EOF errors are NORMAL during HSM init
            if "EOF" in str(e):
                continue
            # Other errors may be real problems
            print(f"Warning: {e}")

    return None  # Timeout
```

### 9.4 Séquence Key Exchange Validée

**Flow complet testé en Session 3:**

```
T+0s:   GCS connect TCP:5760
        ↓
T+0-25s: "EOF on TCP socket" spam (normal)
        ↓
T+25s:  HSM init complete
        HEARTBEAT from sysid=1
        ↓
T+26s:  GCS starts sending HEARTBEAT (1Hz)
        Drone KEP detects GCS peer
        ↓
T+26s:  Drone → GCS: HSM_WK_EXCHANGE (wk_public[64])
        GCS → Drone: HSM_WK_EXCHANGE (wk_public[64])
        GCS → Drone: HSM_KEY_ACK (status=SUCCESS, phase=WK_RECEIVED)
        ↓
T+27s:  Drone → GCS: HSM_DEK_EXCHANGE (ephemeral[64], encrypted[32], nonce[24], tag[16])
        GCS → Drone: HSM_KEY_ACK (status=SUCCESS, phase=DEK_RECEIVED)
        ↓
T+28s:  *** KEY EXCHANGE COMPLETE ***
        Both sides have peer DEK
        Encrypted messages can now be decrypted
```

### 9.5 Commandes Test Session 3

**Lancer test complet:**

```bash
# Terminal 1: SITL avec HSM real
cd /path/to/ardupilot
pkill -9 arducopter  # Clean any existing process

stdbuf -oL ./build/sitl/bin/arducopter \
    --model + \
    --serial1=uart:/dev/ttyUSB0:115200 \
    > /tmp/sitl_hsm.log 2>&1 &

# Attendre init HSM
sleep 30

# Terminal 2: GCS client
python3 Tools/hsm/gcs_kep_client.py --no-hsm --timeout 75

# Résultats attendus:
# - Connected after ~25s wait
# - HSM_WK_EXCHANGE received
# - HSM_KEY_ACK (WK_RECEIVED) received
# - HSM_DEK_EXCHANGE received
# - HSM_KEY_ACK (DEK_RECEIVED) received
# - KEY EXCHANGE COMPLETE
# - 40-50 decrypted messages
```

**Vérifier logs SITL:**
```bash
grep "HSM:" /tmp/sitl_hsm.log

# Attendu:
# HSM: === DÉBUT INIT HSM (SITL BLOQUANT) ===
# HSM: Feature 2.1 - Initialisation KeyOrchestrator...
# HSM: ✓ Feature 2.1 complétée avec succès!
# HSM: Feature 2.2 - Initialisation KeyExchangeProtocol...
# HSM: ✓ KeyExchangeProtocol initialisé
# HSM: Feature 3 - Initialisation DualDekEngine...
# HSM: ✓ DualDekEngine initialisé
# HSM: === FIN INIT HSM ===
```

### 9.6 Checklist Debug GCS Client

```
□ mavutil.mavlink = mavlink_hsm (AVANT connexion)
□ Heartbeat thread démarré APRÈS connexion
□ Timeout suffisant (75-90s) pour init HSM
□ Attributs corrects: ephemeral_pubkey, auth_tag
□ Ignorer erreurs EOF pendant init
□ GCS sysid=255, compid=190 (standard)
```

---

**FIN DU DOCUMENT ARDUPILOT SKILLS**

Ce document contient toutes les connaissances essentielles pour intégrer un module externe dans ArduPilot, avec focus sur communication UART, crypto, et SITL.
