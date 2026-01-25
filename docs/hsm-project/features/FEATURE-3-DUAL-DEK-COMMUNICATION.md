# Feature 3: Dual-DEK Communication Engine

**Version**: 2.0
**Date**: 2026-01-24
**Statut**: 🔄 À implémenter

---

## Objectif

Moteur de communication bidirectionnelle où chaque drone utilise **SA propre DEK** pour chiffrer ses messages sortants et **la DEK du peer** pour déchiffrer les messages entrants.

## Dépendances

- **Feature 1**: KeyOrchestrator (my_dek disponible)
- **Feature 2**: KeyExchangeProtocol (peer_deks disponibles)
- **ChaCha20-Poly1305**: Chiffrement AEAD

## Architecture du Moteur

```
╔════════════════════════════════════════════════════════════════════╗
║                 DUAL-DEK COMMUNICATION ENGINE                       ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐   ║
║  │ OUTBOUND PIPELINE (Chiffrement)                              │   ║
║  │                                                               │   ║
║  │  Message MAVLink → Payload                                   │   ║
║  │         │                                                     │   ║
║  │         ▼                                                     │   ║
║  │  ┌─────────────────┐                                         │   ║
║  │  │ ChaCha20-Poly1305│ ◄── MY_DEK (ma clé)                   │   ║
║  │  │    Encrypt      │ ◄── Nonce (random 12 bytes)            │   ║
║  │  └────────┬────────┘                                         │   ║
║  │           │                                                   │   ║
║  │           ▼                                                   │   ║
║  │  [Header clair][Payload chiffré][Nonce][Tag]                 │   ║
║  │                                                               │   ║
║  └─────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐   ║
║  │ INBOUND PIPELINE (Déchiffrement)                             │   ║
║  │                                                               │   ║
║  │  [Header][Encrypted Payload][Nonce][Tag]                     │   ║
║  │         │                                                     │   ║
║  │         ▼                                                     │   ║
║  │  Identifier sender (sysid/compid)                            │   ║
║  │         │                                                     │   ║
║  │         ▼                                                     │   ║
║  │  ┌─────────────────┐                                         │   ║
║  │  │ ChaCha20-Poly1305│ ◄── PEER_DEK[sender] (clé du peer)    │   ║
║  │  │    Decrypt      │ ◄── Nonce (extrait du message)         │   ║
║  │  └────────┬────────┘                                         │   ║
║  │           │                                                   │   ║
║  │           ▼                                                   │   ║
║  │  Payload clair → Traitement MAVLink normal                   │   ║
║  │                                                               │   ║
║  └─────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐   ║
║  │ SESSION MANAGER                                              │   ║
║  │                                                               │   ║
║  │  peer_sessions[MAX_PEERS] = {                                │   ║
║  │    sysid, compid,                                            │   ║
║  │    peer_dek[32],        // DEK du peer pour déchiffrer       │   ║
║  │    nonce_counter,       // Non utilisé (nonce random)        │   ║
║  │    messages_sent,                                            │   ║
║  │    messages_received,                                        │   ║
║  │    last_activity                                             │   ║
║  │  }                                                            │   ║
║  │                                                               │   ║
║  └─────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
╚════════════════════════════════════════════════════════════════════╝
```

## Principe Dual-DEK

```
┌─────────────────┐                      ┌─────────────────┐
│    DRONE A      │                      │    DRONE B      │
│                 │                      │                 │
│  MY_DEK = DEK_A │                      │  MY_DEK = DEK_B │
│  PEER_DEK = DEK_B                      │  PEER_DEK = DEK_A
└────────┬────────┘                      └────────┬────────┘
         │                                        │
         │  Message chiffré avec DEK_A            │
         │───────────────────────────────────────►│
         │                                        │ Déchiffré avec DEK_A
         │                                        │ (PEER_DEK de B)
         │                                        │
         │  Message chiffré avec DEK_B            │
         │◄───────────────────────────────────────│
Déchiffré│                                        │
avec DEK_B                                        │
(PEER_DEK│                                        │
de A)    │                                        │
```

**Avantages:**
- Traçabilité: On sait toujours qui a envoyé (par la DEK utilisée)
- Pas de négociation de clé commune
- Chaque drone contrôle sa propre clé de chiffrement

## Interface C++

### Fichier: `libraries/AP_HSM/DualDekEngine.h`

```cpp
#pragma once

#include <stdint.h>
#include <stdbool.h>

class KeyOrchestrator;
class KeyExchangeProtocol;

class DualDekEngine {
public:
    DualDekEngine();

    // Singleton
    static DualDekEngine& get_singleton();

    // Initialisation
    bool init(KeyOrchestrator* key_orch, KeyExchangeProtocol* key_exchange);

    // === CHIFFREMENT SORTANT ===
    // Utilise MY_DEK pour chiffrer
    bool encrypt_payload(const uint8_t* plaintext, size_t len,
                         uint8_t* ciphertext,
                         uint8_t nonce[12],
                         uint8_t tag[16]);

    // === DÉCHIFFREMENT ENTRANT ===
    // Utilise PEER_DEK selon le sender
    bool decrypt_payload(uint8_t sender_sysid, uint8_t sender_compid,
                         const uint8_t* ciphertext, size_t len,
                         const uint8_t nonce[12],
                         const uint8_t tag[16],
                         uint8_t* plaintext);

    // === VÉRIFICATIONS ===
    bool is_encryption_enabled() const { return encryption_enabled; }
    bool can_send_encrypted() const;
    bool can_decrypt_from(uint8_t sysid, uint8_t compid);

    // === MESSAGES NON CHIFFRÉS ===
    bool should_encrypt_msgid(uint32_t msgid);

    // === STATISTIQUES ===
    struct Stats {
        uint32_t messages_encrypted;
        uint32_t messages_decrypted;
        uint32_t decrypt_failures;
        uint32_t unknown_sender;
    };
    const Stats& get_stats() const { return stats; }

    // === ACTIVATION ===
    void enable_encryption(bool enable) { encryption_enabled = enable; }

private:
    KeyOrchestrator* _key_orch = nullptr;
    KeyExchangeProtocol* _key_exchange = nullptr;

    bool encryption_enabled = false;
    Stats stats = {0};

    // Messages à NE PAS chiffrer
    bool is_plaintext_msgid(uint32_t msgid);
};
```

## Implémentation

### Chiffrement Sortant

```cpp
bool DualDekEngine::encrypt_payload(
    const uint8_t* plaintext, size_t len,
    uint8_t* ciphertext,
    uint8_t nonce[12],
    uint8_t tag[16])
{
    if (!encryption_enabled) {
        // Mode non chiffré: copier tel quel
        memcpy(ciphertext, plaintext, len);
        return true;
    }

    // Vérifier que j'ai ma DEK
    if (!_key_orch->has_dek()) {
        printf("DualDEK: ERREUR - MY_DEK non disponible\n");
        return false;
    }

    const uint8_t* my_dek = _key_orch->get_my_dek();

    // Générer nonce aléatoire (12 bytes)
    if (!hal.util->get_random_vals(nonce, 12)) {
        printf("DualDEK: ERREUR - Génération nonce échouée\n");
        return false;
    }

    // Chiffrer avec ChaCha20-Poly1305
    chacha20_poly1305_encrypt(
        plaintext, len,       // Input
        my_dek,               // Key (MA DEK)
        nonce,                // Nonce
        nullptr, 0,           // AAD (none)
        ciphertext,           // Output
        tag                   // Auth tag
    );

    stats.messages_encrypted++;
    return true;
}
```

### Déchiffrement Entrant

```cpp
bool DualDekEngine::decrypt_payload(
    uint8_t sender_sysid, uint8_t sender_compid,
    const uint8_t* ciphertext, size_t len,
    const uint8_t nonce[12],
    const uint8_t tag[16],
    uint8_t* plaintext)
{
    if (!encryption_enabled) {
        // Mode non chiffré: copier tel quel
        memcpy(plaintext, ciphertext, len);
        return true;
    }

    // Récupérer la DEK du sender
    const uint8_t* peer_dek = _key_exchange->get_peer_dek(sender_sysid, sender_compid);

    if (peer_dek == nullptr) {
        printf("DualDEK: ERREUR - DEK inconnue pour sysid=%d compid=%d\n",
               sender_sysid, sender_compid);
        stats.unknown_sender++;
        return false;
    }

    // Déchiffrer avec ChaCha20-Poly1305
    if (!chacha20_poly1305_decrypt(
            ciphertext, len,  // Input
            peer_dek,         // Key (DEK DU PEER)
            nonce,            // Nonce
            nullptr, 0,       // AAD
            tag,              // Auth tag
            plaintext))       // Output
    {
        printf("DualDEK: ERREUR - Déchiffrement échoué (tag invalide)\n");
        stats.decrypt_failures++;
        return false;
    }

    stats.messages_decrypted++;
    return true;
}
```

### Filtrage des Messages

```cpp
bool DualDekEngine::should_encrypt_msgid(uint32_t msgid) {
    // Messages TOUJOURS en clair (nécessaires pour découverte/handshake)
    switch (msgid) {
        case MAVLINK_MSG_ID_HEARTBEAT:           // Découverte peers
        case MAVLINK_MSG_ID_HSM_WK_EXCHANGE:     // Échange clés
        case MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:    // Échange DEK
        case MAVLINK_MSG_ID_HSM_KEY_ACK:         // ACK clés
            return false;
    }

    // Tous les autres messages sont chiffrés
    return true;
}

bool DualDekEngine::is_plaintext_msgid(uint32_t msgid) {
    return !should_encrypt_msgid(msgid);
}
```

## Intégration GCS_MAVLink

### Point d'Interception: `comm_send_buffer()`

```cpp
// Dans libraries/GCS_MAVLink/GCS_MAVLink.cpp

void comm_send_buffer(mavlink_channel_t chan, const uint8_t *buf, uint8_t len)
{
    const uint8_t current_buffer = send_buffer_index[chan];
    const bool is_payload = (current_buffer == 1);

    // Récupérer le moteur de chiffrement
    DualDekEngine& engine = DualDekEngine::get_singleton();

    if (engine.is_encryption_enabled() && is_payload && len > 0) {
        // Extraire msgid du header précédent
        uint32_t msgid = get_current_msgid(chan);

        if (engine.should_encrypt_msgid(msgid)) {
            uint8_t encrypted[256];
            uint8_t nonce[12];
            uint8_t tag[16];

            if (engine.encrypt_payload(buf, len, encrypted, nonce, tag)) {
                // Envoyer: [encrypted payload][nonce 12B][tag 16B]
                mavlink_comm_port[chan]->write(encrypted, len);
                mavlink_comm_port[chan]->write(nonce, 12);
                mavlink_comm_port[chan]->write(tag, 16);
                send_buffer_index[chan]++;
                return;
            }
        }
    }

    // Envoi normal (non chiffré ou header/checksum)
    mavlink_comm_port[chan]->write(buf, len);
    send_buffer_index[chan]++;
}
```

### Point d'Interception: `packetReceived()`

```cpp
// Dans libraries/GCS_MAVLink/GCS_Common.cpp

void GCS_MAVLINK::packetReceived(const mavlink_status_t &status,
                                  const mavlink_message_t &msg)
{
    DualDekEngine& engine = DualDekEngine::get_singleton();

    if (engine.is_encryption_enabled() &&
        engine.should_encrypt_msgid(msg.msgid))
    {
        // Extraire nonce et tag de la fin du payload
        // Note: Nécessite modification du parsing MAVLink
        uint8_t nonce[12];
        uint8_t tag[16];
        // ... extraction ...

        uint8_t decrypted[MAVLINK_MAX_PAYLOAD_LEN];

        if (!engine.decrypt_payload(
                msg.sysid, msg.compid,
                (uint8_t*)_MAV_PAYLOAD(&msg), msg.len - 28,  // Payload sans nonce/tag
                nonce, tag,
                decrypted))
        {
            // Échec déchiffrement: ignorer le message
            return;
        }

        // Remplacer payload par version déchiffrée
        memcpy((void*)_MAV_PAYLOAD(&msg), decrypted, msg.len - 28);
    }

    // Traitement normal
    handle_message(msg);
}
```

## Format de Message Chiffré

```
┌──────────────────────────────────────────────────────────────────┐
│                    MESSAGE MAVLINK CHIFFRÉ                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌────────────┬────────────────────┬────────┬────────┬──────────┐│
│  │   HEADER   │  ENCRYPTED PAYLOAD │  NONCE │  TAG   │ CHECKSUM ││
│  │  (clair)   │   (ChaCha20)       │ (12B)  │ (16B)  │ (clair)  ││
│  │  10-12B    │     variable       │        │        │   2B     ││
│  └────────────┴────────────────────┴────────┴────────┴──────────┘│
│                                                                    │
│  Header contient: magic, len, seq, sysid, compid, msgid           │
│  → Permet identification sender sans déchiffrer                   │
│                                                                    │
│  Nonce: 12 bytes random (unique par message)                      │
│  Tag: 16 bytes Poly1305 (authentification)                        │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

## Gestion des Sessions

```cpp
// Dans KeyExchangeProtocol (Feature 2), accessible par DualDekEngine

const uint8_t* KeyExchangeProtocol::get_peer_dek(uint8_t sysid, uint8_t compid) {
    PeerInfo* peer = find_peer(sysid, compid);

    if (peer == nullptr || !peer->dek_received) {
        return nullptr;  // DEK pas encore échangée
    }

    return peer->dek;
}
```

## Flux Complet

```
                         DRONE A                                  DRONE B
                            │                                        │
    ┌───────────────────────┴───────────────────────┐               │
    │ ENVOI MESSAGE                                  │               │
    │                                                │               │
    │ 1. Application génère message MAVLink          │               │
    │ 2. should_encrypt_msgid(msgid) → true          │               │
    │ 3. encrypt_payload(payload, MY_DEK_A)          │               │
    │    → ciphertext + nonce + tag                  │               │
    │ 4. Envoyer [header][ciphertext][nonce][tag]    │               │
    └───────────────────────┬───────────────────────┘               │
                            │                                        │
                            │  ════════════════════════════════════► │
                            │                                        │
                            │               ┌───────────────────────┴───────────────────────┐
                            │               │ RÉCEPTION MESSAGE                              │
                            │               │                                                │
                            │               │ 1. Parser header → sysid=A                     │
                            │               │ 2. should_encrypt_msgid(msgid) → true          │
                            │               │ 3. get_peer_dek(sysid=A) → DEK_A               │
                            │               │ 4. decrypt_payload(ciphertext, DEK_A)          │
                            │               │    → plaintext                                 │
                            │               │ 5. Traiter message normalement                 │
                            │               └───────────────────────┬───────────────────────┘
                            │                                        │
                            │  ◄════════════════════════════════════ │
                            │                                        │
    ┌───────────────────────┴───────────────────────┐               │
    │ RÉCEPTION (même logique inversée)              │               │
    │ decrypt_payload(ciphertext, PEER_DEK_B = DEK_B)│               │
    └───────────────────────────────────────────────┘               │
```

## Tests de Validation

### Test 1: Chiffrement/Déchiffrement Local

```cpp
// Test unitaire
void test_dual_dek_encrypt_decrypt() {
    uint8_t plaintext[] = "Hello MAVLink!";
    uint8_t ciphertext[256];
    uint8_t decrypted[256];
    uint8_t nonce[12];
    uint8_t tag[16];

    DualDekEngine& engine = DualDekEngine::get_singleton();

    // Chiffrer
    assert(engine.encrypt_payload(plaintext, sizeof(plaintext),
                                   ciphertext, nonce, tag));

    // Simuler réception depuis notre propre sysid
    // (en utilisant notre propre DEK comme peer_dek)
    assert(engine.decrypt_payload(mavlink_system.sysid, mavlink_system.compid,
                                   ciphertext, sizeof(plaintext),
                                   nonce, tag, decrypted));

    assert(memcmp(plaintext, decrypted, sizeof(plaintext)) == 0);
    printf("TEST: ✓ Chiffrement/Déchiffrement OK\n");
}
```

### Test 2: Communication Drone-GCS

```bash
# 1. Lancer SITL avec HSM
./build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200

# 2. MAVProxy
mavproxy.py --master=tcp:127.0.0.1:5760 --console

# 3. Activer chiffrement
param set MAV_ENCRYPT 1

# 4. Observer les messages chiffrés
# Les payloads doivent apparaître comme données binaires aléatoires

# 5. Vérifier stats
status encryption
# → messages_encrypted: X, messages_decrypted: Y, failures: 0
```

### Test 3: Message Non Chiffré (Heartbeat)

Vérifier que HEARTBEAT reste lisible même avec encryption activée.

## Critères de Succès

- [ ] Chiffrement payload avec MY_DEK fonctionne
- [ ] Déchiffrement avec PEER_DEK correct
- [ ] HEARTBEAT reste en clair
- [ ] Messages HSM_* restent en clair
- [ ] Tag Poly1305 détecte modifications
- [ ] Stats de chiffrement correctes
- [ ] Pas de dégradation performance visible

## Sécurité

### Nonce Unique
- **Random 12 bytes** par message
- Probabilité collision: 2^-48 après 2^24 messages (négligeable)

### Authentification
- **Poly1305 tag** sur chaque message
- Détecte toute modification du ciphertext

### Isolation
- Chaque peer a sa propre DEK
- Compromission d'une DEK n'affecte pas les autres

### Messages en Transit
- Si DEK pas encore échangée → message non envoyé
- HEARTBEAT toujours envoyé pour permettre découverte

---

**Feature précédente**: [FEATURE-2-KEY-EXCHANGE-PROTOCOL.md](FEATURE-2-KEY-EXCHANGE-PROTOCOL.md)
