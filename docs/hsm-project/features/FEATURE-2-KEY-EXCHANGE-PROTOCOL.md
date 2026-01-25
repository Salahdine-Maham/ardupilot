# Feature 2: Key Exchange Protocol

**Version**: 2.0
**Date**: 2026-01-24
**Statut**: 🔄 À implémenter

---

## Objectif

Implémenter le protocole sécurisé d'échange bidirectionnel des clés entre drones (et GCS) via des messages MAVLink custom, utilisant ECIES pour chiffrer les DEK.

## Dépendances

- **Feature 1**: KeyOrchestrator (MK, WK, DEK disponibles)
- **micro-ecc**: ECDH pour ECIES
- **ChaCha20-Poly1305**: Chiffrement AEAD

## Protocole d'Échange

```
┌─────────────────┐                      ┌─────────────────┐
│    DRONE A      │                      │    DRONE B      │
│                 │                      │    (ou GCS)     │
└────────┬────────┘                      └────────┬────────┘
         │                                        │
         │  1. HEARTBEAT (découverte)             │
         │◄──────────────────────────────────────►│
         │                                        │
         │  2. HSM_WK_EXCHANGE                    │
         │  ┌─────────────────────────────────────►
         │  │  {wk_pub_a[64 bytes]}               │
         │  │                                     │
         │  │◄─────────────────────────────────────┐
         │     {wk_pub_b[64 bytes]}               │
         │                                        │
         │  3. HSM_DEK_EXCHANGE (ECIES)           │
         │  ┌─────────────────────────────────────►
         │  │  {                                  │
         │  │    ephemeral_pub[64],               │
         │  │    encrypted_dek[32],               │
         │  │    nonce[12],                       │
         │  │    tag[16]                          │
         │  │  }                                  │
         │  │                                     │
         │  │◄─────────────────────────────────────┐
         │     (même format avec DEK_B)           │
         │                                        │
         │  4. HSM_KEY_ACK                        │
         │◄──────────────────────────────────────►│
         │     {status: OK}                       │
         │                                        │
         │  ═══════════════════════════════════   │
         │  SESSION SÉCURISÉE ÉTABLIE             │
         │  ═══════════════════════════════════   │
```

## Messages MAVLink Custom

### HSM_WK_EXCHANGE (ID: 12000)

Échange des clés publiques Wrapper Key (P-256).

```xml
<message id="12000" name="HSM_WK_EXCHANGE">
    <description>Exchange Wrapper Key public for HSM secure channel</description>
    <field type="uint8_t" name="target_system">Target system ID (0 for broadcast)</field>
    <field type="uint8_t" name="target_component">Target component ID</field>
    <field type="uint8_t[64]" name="wk_public">Wrapper Key Public (P-256 uncompressed X||Y)</field>
    <field type="uint32_t" name="timestamp">Unix timestamp for freshness</field>
</message>
```

**Taille**: 70 bytes payload

### HSM_DEK_EXCHANGE (ID: 12001)

Échange des DEK chiffrées via ECIES.

```xml
<message id="12001" name="HSM_DEK_EXCHANGE">
    <description>Exchange encrypted DEK using ECIES</description>
    <field type="uint8_t" name="target_system">Target system ID</field>
    <field type="uint8_t" name="target_component">Target component ID</field>
    <field type="uint8_t[64]" name="ephemeral_pubkey">ECIES ephemeral public key (P-256)</field>
    <field type="uint8_t[32]" name="encrypted_dek">DEK encrypted with derived key</field>
    <field type="uint8_t[12]" name="nonce">ChaCha20-Poly1305 nonce</field>
    <field type="uint8_t[16]" name="auth_tag">Poly1305 authentication tag</field>
</message>
```

**Taille**: 126 bytes payload

### HSM_KEY_ACK (ID: 12002)

Accusé de réception de l'échange de clés.

```xml
<message id="12002" name="HSM_KEY_ACK">
    <description>Acknowledgment of key exchange</description>
    <field type="uint8_t" name="target_system">Target system ID</field>
    <field type="uint8_t" name="target_component">Target component ID</field>
    <field type="uint8_t" name="status">0=Success, 1=WK_Error, 2=DEK_Error, 3=Timeout</field>
    <field type="uint8_t" name="phase">1=WK_received, 2=DEK_received, 3=Complete</field>
</message>
```

**Taille**: 4 bytes payload

## Interface C++

### Fichier: `libraries/AP_HSM/KeyExchangeProtocol.h`

```cpp
#pragma once

#include <stdint.h>
#include <stdbool.h>

class KeyOrchestrator;  // Forward declaration

class KeyExchangeProtocol {
public:
    // État de la négociation
    enum class State : uint8_t {
        IDLE = 0,
        WK_SENT,
        WK_RECEIVED,
        DEK_SENT,
        DEK_RECEIVED,
        COMPLETE,
        ERROR
    };

    // Status ACK
    enum class AckStatus : uint8_t {
        SUCCESS = 0,
        WK_ERROR = 1,
        DEK_ERROR = 2,
        TIMEOUT = 3
    };

    // Structure pour un peer
    struct PeerInfo {
        uint8_t sysid;
        uint8_t compid;
        uint8_t wk_public[64];
        uint8_t dek[32];
        State state;
        uint32_t last_activity;
        bool wk_received;
        bool dek_received;
    };

    KeyExchangeProtocol();

    // Singleton
    static KeyExchangeProtocol& get_singleton();

    // Initialisation
    bool init(KeyOrchestrator* key_orch);

    // === DÉCOUVERTE ===
    void on_heartbeat_received(uint8_t sysid, uint8_t compid);
    bool is_known_peer(uint8_t sysid, uint8_t compid);

    // === INITIATION ÉCHANGE ===
    bool initiate_exchange(uint8_t peer_sysid, uint8_t peer_compid);
    bool initiate_exchange_all_peers();

    // === HANDLERS MESSAGES REÇUS ===
    void handle_wk_exchange(uint8_t src_sysid, uint8_t src_compid,
                            const uint8_t wk_pub[64], uint32_t timestamp);

    void handle_dek_exchange(uint8_t src_sysid, uint8_t src_compid,
                             const uint8_t ephemeral_pub[64],
                             const uint8_t encrypted_dek[32],
                             const uint8_t nonce[12],
                             const uint8_t tag[16]);

    void handle_key_ack(uint8_t src_sysid, uint8_t src_compid,
                        uint8_t status, uint8_t phase);

    // === ECIES ===
    bool ecies_encrypt_dek(const uint8_t peer_wk_pub[64],
                           const uint8_t dek[32],
                           uint8_t ephemeral_pub[64],
                           uint8_t encrypted_dek[32],
                           uint8_t nonce[12],
                           uint8_t tag[16]);

    bool ecies_decrypt_dek(const uint8_t ephemeral_pub[64],
                           const uint8_t encrypted_dek[32],
                           const uint8_t nonce[12],
                           const uint8_t tag[16],
                           uint8_t dek[32]);

    // === ÉTAT ===
    State get_peer_state(uint8_t sysid, uint8_t compid);
    bool is_exchange_complete(uint8_t sysid, uint8_t compid);
    const uint8_t* get_peer_dek(uint8_t sysid, uint8_t compid);
    uint8_t get_num_peers() const { return num_peers; }

    // === TIMEOUT ===
    void check_timeouts();

private:
    KeyOrchestrator* _key_orch = nullptr;

    // Table des peers (max 5 drones)
    static const uint8_t MAX_PEERS = 5;
    PeerInfo peers[MAX_PEERS];
    uint8_t num_peers = 0;

    // Timeout en ms
    static const uint32_t EXCHANGE_TIMEOUT_MS = 10000;  // 10 secondes

    // Helpers
    PeerInfo* find_peer(uint8_t sysid, uint8_t compid);
    PeerInfo* add_peer(uint8_t sysid, uint8_t compid);
    bool send_wk_exchange(uint8_t target_sysid, uint8_t target_compid);
    bool send_dek_exchange(PeerInfo* peer);
    bool send_key_ack(uint8_t target_sysid, uint8_t target_compid,
                      AckStatus status, uint8_t phase);
};
```

## Implémentation ECIES

### Chiffrement DEK avec ECIES

```cpp
bool KeyExchangeProtocol::ecies_encrypt_dek(
    const uint8_t peer_wk_pub[64],    // Clé publique du destinataire
    const uint8_t dek[32],             // DEK à chiffrer
    uint8_t ephemeral_pub[64],         // OUT: Clé publique éphémère
    uint8_t encrypted_dek[32],         // OUT: DEK chiffrée
    uint8_t nonce[12],                 // OUT: Nonce
    uint8_t tag[16])                   // OUT: Tag authentification
{
    // 1. Générer keypair éphémère
    uint8_t ephemeral_priv[32];
    uECC_Curve curve = uECC_secp256r1();

    if (uECC_make_key(ephemeral_pub, ephemeral_priv, curve) != 1) {
        printf("KEP: ERREUR - Échec génération clé éphémère\n");
        return false;
    }

    // 2. ECDH: shared_secret = ephemeral_priv * peer_wk_pub
    uint8_t shared_secret[32];
    if (uECC_shared_secret(peer_wk_pub, ephemeral_priv, shared_secret, curve) != 1) {
        printf("KEP: ERREUR - Échec ECDH\n");
        secure_zero(ephemeral_priv, 32);
        return false;
    }

    // 3. Dériver clé de chiffrement via HKDF
    uint8_t encryption_key[32];
    hkdf_sha256(
        (const uint8_t*)"ECIES-Salt", 10,
        shared_secret, 32,
        (const uint8_t*)"DEK-Encryption-v1", 17,
        encryption_key, 32
    );

    // 4. Générer nonce aléatoire
    hal.util->get_random_vals(nonce, 12);

    // 5. Chiffrer avec ChaCha20-Poly1305
    chacha20_poly1305_encrypt(
        dek, 32,                  // Plaintext (DEK)
        encryption_key,           // Key
        nonce,                    // Nonce
        nullptr, 0,               // AAD (none)
        encrypted_dek,            // Ciphertext
        tag                       // Tag
    );

    // 6. Cleanup secrets
    secure_zero(ephemeral_priv, 32);
    secure_zero(shared_secret, 32);
    secure_zero(encryption_key, 32);

    printf("KEP: ✓ DEK chiffrée avec ECIES\n");
    return true;
}
```

### Déchiffrement DEK avec ECIES

```cpp
bool KeyExchangeProtocol::ecies_decrypt_dek(
    const uint8_t ephemeral_pub[64],   // Clé publique éphémère reçue
    const uint8_t encrypted_dek[32],    // DEK chiffrée reçue
    const uint8_t nonce[12],
    const uint8_t tag[16],
    uint8_t dek[32])                    // OUT: DEK déchiffrée
{
    // 1. Récupérer ma clé privée WK
    const uint8_t* my_wk_priv = _key_orch->get_wk_private();
    if (my_wk_priv == nullptr) {
        printf("KEP: ERREUR - WK_private non disponible\n");
        return false;
    }

    // 2. ECDH: shared_secret = my_wk_priv * ephemeral_pub
    uint8_t shared_secret[32];
    uECC_Curve curve = uECC_secp256r1();

    if (uECC_shared_secret(ephemeral_pub, my_wk_priv, shared_secret, curve) != 1) {
        printf("KEP: ERREUR - Échec ECDH déchiffrement\n");
        return false;
    }

    // 3. Dériver même clé de chiffrement
    uint8_t encryption_key[32];
    hkdf_sha256(
        (const uint8_t*)"ECIES-Salt", 10,
        shared_secret, 32,
        (const uint8_t*)"DEK-Encryption-v1", 17,
        encryption_key, 32
    );

    // 4. Déchiffrer avec ChaCha20-Poly1305
    if (!chacha20_poly1305_decrypt(
            encrypted_dek, 32,    // Ciphertext
            encryption_key,        // Key
            nonce,                 // Nonce
            nullptr, 0,            // AAD
            tag,                   // Tag
            dek))                  // Plaintext out
    {
        printf("KEP: ERREUR - Déchiffrement ECIES échoué (tag invalide)\n");
        secure_zero(shared_secret, 32);
        secure_zero(encryption_key, 32);
        return false;
    }

    // 5. Cleanup
    secure_zero(shared_secret, 32);
    secure_zero(encryption_key, 32);

    printf("KEP: ✓ DEK déchiffrée avec succès\n");
    return true;
}
```

## Gestion des Peers

### Découverte via Heartbeat

```cpp
void KeyExchangeProtocol::on_heartbeat_received(uint8_t sysid, uint8_t compid) {
    // Ignorer notre propre heartbeat
    if (sysid == mavlink_system.sysid && compid == mavlink_system.compid) {
        return;
    }

    // Vérifier si peer déjà connu
    PeerInfo* peer = find_peer(sysid, compid);

    if (peer == nullptr) {
        // Nouveau peer détecté
        printf("KEP: Nouveau peer détecté: sysid=%d compid=%d\n", sysid, compid);

        peer = add_peer(sysid, compid);
        if (peer != nullptr) {
            // Initier échange automatiquement
            initiate_exchange(sysid, compid);
        }
    } else {
        // Peer connu, mettre à jour timestamp
        peer->last_activity = AP_HAL::millis();
    }
}
```

### Machine à États par Peer

```cpp
void KeyExchangeProtocol::handle_wk_exchange(
    uint8_t src_sysid, uint8_t src_compid,
    const uint8_t wk_pub[64], uint32_t timestamp)
{
    PeerInfo* peer = find_peer(src_sysid, src_compid);
    if (peer == nullptr) {
        peer = add_peer(src_sysid, src_compid);
    }

    // Stocker WK publique du peer
    memcpy(peer->wk_public, wk_pub, 64);
    peer->wk_received = true;
    peer->last_activity = AP_HAL::millis();

    printf("KEP: WK_PUB reçue de sysid=%d\n", src_sysid);

    // Si on n'a pas encore envoyé notre WK, l'envoyer
    if (peer->state == State::IDLE) {
        send_wk_exchange(src_sysid, src_compid);
        peer->state = State::WK_SENT;
    }

    // Si WK échangées des deux côtés, passer à DEK
    if (peer->state == State::WK_SENT && peer->wk_received) {
        peer->state = State::WK_RECEIVED;
        send_dek_exchange(peer);
        peer->state = State::DEK_SENT;
    }

    // Envoyer ACK
    send_key_ack(src_sysid, src_compid, AckStatus::SUCCESS, 1);
}

void KeyExchangeProtocol::handle_dek_exchange(
    uint8_t src_sysid, uint8_t src_compid,
    const uint8_t ephemeral_pub[64],
    const uint8_t encrypted_dek[32],
    const uint8_t nonce[12],
    const uint8_t tag[16])
{
    PeerInfo* peer = find_peer(src_sysid, src_compid);
    if (peer == nullptr) {
        printf("KEP: ERREUR - DEK reçue de peer inconnu\n");
        return;
    }

    // Déchiffrer DEK du peer
    if (!ecies_decrypt_dek(ephemeral_pub, encrypted_dek, nonce, tag, peer->dek)) {
        send_key_ack(src_sysid, src_compid, AckStatus::DEK_ERROR, 2);
        return;
    }

    peer->dek_received = true;
    peer->last_activity = AP_HAL::millis();

    printf("KEP: DEK reçue et déchiffrée de sysid=%d\n", src_sysid);

    // Vérifier si échange complet
    if (peer->state == State::DEK_SENT && peer->dek_received) {
        peer->state = State::COMPLETE;
        printf("KEP: ✓ Échange complet avec sysid=%d\n", src_sysid);
    }

    // Envoyer ACK
    send_key_ack(src_sysid, src_compid, AckStatus::SUCCESS, 2);
}
```

## Diagramme d'États

```
                    ┌──────────────────┐
                    │      IDLE        │
                    │  (nouveau peer)  │
                    └────────┬─────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            ▼                ▼                ▼
    ┌───────────────┐  Heartbeat reçu  ┌───────────────┐
    │  Initiation   │◄─────────────────│  WK reçue     │
    │  par nous     │                  │  du peer      │
    └───────┬───────┘                  └───────┬───────┘
            │                                  │
            ▼                                  ▼
    ┌───────────────┐                  ┌───────────────┐
    │   WK_SENT     │                  │  (envoyer     │
    │               │◄─────────────────│   notre WK)   │
    └───────┬───────┘                  └───────────────┘
            │
            │ WK peer reçue
            ▼
    ┌───────────────┐
    │  WK_RECEIVED  │
    │ (prêt DEK)    │
    └───────┬───────┘
            │
            │ Envoyer DEK chiffrée
            ▼
    ┌───────────────┐
    │   DEK_SENT    │
    └───────┬───────┘
            │
            │ DEK peer reçue
            ▼
    ┌───────────────┐
    │   COMPLETE    │
    │  ✓ Session    │
    │    établie    │
    └───────────────┘
```

## Tests de Validation

### Test 1: Échange WK avec GCS

```bash
# 1. Lancer drone SITL
./build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200

# 2. Connecter MAVProxy
mavproxy.py --master=tcp:127.0.0.1:5760 --console

# 3. Observer logs
grep "KEP:" /tmp/ardupilot.log

# Attendu:
# KEP: Nouveau peer détecté: sysid=255 compid=0
# KEP: WK_PUB envoyée à sysid=255
# KEP: WK_PUB reçue de sysid=255
# KEP: DEK chiffrée avec ECIES
# KEP: DEK envoyée à sysid=255
# KEP: DEK reçue et déchiffrée de sysid=255
# KEP: ✓ Échange complet avec sysid=255
```

### Test 2: Échange entre 2 Drones SITL

```bash
# Terminal 1: Drone 1 (sysid=1)
SYSID=1 ./build/sitl/bin/arducopter --model + -I0

# Terminal 2: Drone 2 (sysid=2)
SYSID=2 ./build/sitl/bin/arducopter --model + -I1

# Les deux drones doivent s'échanger leurs clés automatiquement
```

## Critères de Succès

- [ ] Message HSM_WK_EXCHANGE envoyé/reçu correctement
- [ ] Message HSM_DEK_EXCHANGE avec ECIES fonctionne
- [ ] Déchiffrement DEK peer réussit
- [ ] Machine à états transitions correctes
- [ ] Timeout détecté si peer ne répond pas
- [ ] Multiple peers supportés (jusqu'à 5)

## Sécurité

- **Perfect Forward Secrecy**: Clé éphémère par échange ECIES
- **Authentification**: Trust-on-first-use (TOFU)
- **Replay Protection**: Timestamp dans WK_EXCHANGE
- **Intégrité**: Tag Poly1305 sur DEK chiffrée

---

**Feature précédente**: [FEATURE-1-KEY-ORCHESTRATOR.md](FEATURE-1-KEY-ORCHESTRATOR.md)
**Prochaine Feature**: [FEATURE-3-DUAL-DEK-COMMUNICATION.md](FEATURE-3-DUAL-DEK-COMMUNICATION.md)
