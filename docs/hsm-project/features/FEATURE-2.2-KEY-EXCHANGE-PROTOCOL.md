# Feature 2.2: Key Exchange Protocol
## Protocole d'Échange de Clés Drone-Drone

**Statut**: En planification
**Dépendance**: Feature 2.1 (Key Orchestrator)

---

## 🎯 Objectif

Implémenter le protocole sécurisé d'échange **bidirectionnel** des DEK entre drones via cryptographie ECC (ECIES).

---

## 📊 Vue d'Ensemble du Protocole

```
┌─────────────────────────────────────────────────────────────────────┐
│              PROTOCOLE D'ÉCHANGE DE CLÉS DRONE-DRONE                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  DRONE A                                    DRONE B                 │
│  ════════                                   ════════                │
│                                                                     │
│  ┌─────────────┐                           ┌─────────────┐         │
│  │ WK_A (priv) │                           │ WK_B (priv) │         │
│  │ WK_A (pub)  │                           │ WK_B (pub)  │         │
│  │ DEK_A       │                           │ DEK_B       │         │
│  └─────────────┘                           └─────────────┘         │
│                                                                     │
│  PHASE 1: Handshake & Authentication                               │
│  ─────────────────────────────────────                             │
│       WK_A_PUB + Signature ───────────────────▶                    │
│       ◀─────────────────────── WK_B_PUB + Signature                │
│       (Vérification ECDSA mutuelle)                                │
│                                                                     │
│  PHASE 2: DEK Encryption & Exchange                                │
│  ─────────────────────────────────────                             │
│       ECIES(DEK_A, WK_B_PUB) ─────────────────▶                    │
│       ◀───────────────────────── ECIES(DEK_B, WK_A_PUB)            │
│                                                                     │
│  PHASE 3: Validation & Session Setup                               │
│  ─────────────────────────────────────                             │
│       Déchiffre avec WK_A_PRIV → DEK_B                             │
│                               Déchiffre avec WK_B_PRIV → DEK_A     │
│       ACK_A (hash DEK_B) ─────────────────────▶                    │
│       ◀───────────────────────────── ACK_B (hash DEK_A)            │
│                                                                     │
│  RÉSULTAT:                                                          │
│  ─────────                                                          │
│  Drone A possède: DEK_A (pour envoyer) + DEK_B (pour recevoir)     │
│  Drone B possède: DEK_B (pour envoyer) + DEK_A (pour recevoir)     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Séquence Protocolaire Détaillée

### Phase 1: Handshake & Authentication

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 1: HANDSHAKE                                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Drone A prépare message handshake:                             │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ {                                                        │   │
│     │   "type": "wk_handshake",                                │   │
│     │   "drone_id": "DRONE_A",                                 │   │
│     │   "wk_public": "base64(WK_A_PUB)",                       │   │
│     │   "timestamp": "2026-01-23T10:30:00Z",                   │   │
│     │   "nonce": "random_16_bytes",                            │   │
│     │   "signature": "ECDSA_sign(WK_A_PRIV, hash(payload))"    │   │
│     │ }                                                        │   │
│     └──────────────────────────────────────────────────────────┘   │
│                                                                     │
│  2. Drone B reçoit et vérifie:                                     │
│     - Vérifie timestamp (anti-replay: < 30 secondes)               │
│     - Vérifie signature ECDSA avec WK_A_PUB                        │
│     - Stocke WK_A_PUB pour Phase 2                                 │
│                                                                     │
│  3. Drone B répond avec son propre handshake                       │
│                                                                     │
│  4. Drone A vérifie de la même manière                             │
│                                                                     │
│  ✓ Résultat: Les deux drones ont échangé leurs WK_PUB             │
│              et vérifié l'authenticité mutuellement                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 2: DEK Encryption & Exchange

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 2: ÉCHANGE DEK CHIFFRÉ                                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ECIES (Elliptic Curve Integrated Encryption Scheme):              │
│  ───────────────────────────────────────────────────                │
│                                                                     │
│  Drone A chiffre SA DEK pour Drone B:                              │
│                                                                     │
│  1. Génère keypair éphémère (E_A_priv, E_A_pub)                    │
│  2. Calcule shared_secret = ECDH(E_A_priv, WK_B_PUB)               │
│  3. Dérive encryption_key = HKDF(shared_secret, "ecies_enc")       │
│  4. Chiffre: ciphertext = ChaCha20-Poly1305(DEK_A, encryption_key) │
│                                                                     │
│  Message envoyé:                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │ {                                                        │      │
│  │   "type": "dek_delivery",                                │      │
│  │   "session_id": "uuid_v4",                               │      │
│  │   "sender": "DRONE_A",                                   │      │
│  │   "encrypted_dek": {                                     │      │
│  │     "ephemeral_key": "base64(E_A_pub)",  // 64 bytes    │      │
│  │     "nonce": "base64(12_bytes)",                         │      │
│  │     "ciphertext": "base64(32_bytes)",    // DEK chiffré │      │
│  │     "tag": "base64(16_bytes)"            // Auth tag    │      │
│  │   },                                                     │      │
│  │   "timestamp": "2026-01-23T10:30:05Z"                    │      │
│  │ }                                                        │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                     │
│  Drone B déchiffre:                                                 │
│  1. shared_secret = ECDH(WK_B_PRIV, E_A_pub)                       │
│  2. encryption_key = HKDF(shared_secret, "ecies_enc")              │
│  3. DEK_A = ChaCha20-Poly1305_decrypt(ciphertext, encryption_key)  │
│  4. Vérifie auth tag (intégrité)                                   │
│                                                                     │
│  ✓ Drone B possède maintenant DEK_A de Drone A                     │
│                                                                     │
│  Processus identique dans l'autre sens pour DEK_B → Drone A        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 3: Validation & Session Setup

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 3: VALIDATION ET ÉTABLISSEMENT DE SESSION                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Drone A envoie ACK cryptographique:                            │
│     ┌──────────────────────────────────────────────────────────┐   │
│     │ {                                                        │   │
│     │   "type": "dek_ack",                                     │   │
│     │   "session_id": "uuid_v4",                               │   │
│     │   "dek_hash": "SHA256(DEK_B)[0:16]",  // Preuve réception│   │
│     │   "status": "success"                                    │   │
│     │ }                                                        │   │
│     └──────────────────────────────────────────────────────────┘   │
│                                                                     │
│  2. Drone B vérifie:                                                │
│     - hash correspond à SHA256(DEK_B)[0:16]                        │
│     - Confirme que Drone A a bien reçu et déchiffré DEK_B         │
│                                                                     │
│  3. Drone B envoie son ACK (même format)                           │
│                                                                     │
│  4. Session établie:                                                │
│     - Les deux drones ont confirmé réception des DEK               │
│     - Communication sécurisée peut commencer                       │
│     - Timer de session démarre (1h ou 10k messages)                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔐 Propriétés de Sécurité

### Perfect Forward Secrecy (PFS)

```
┌─────────────────────────────────────────────────────────────────────┐
│ PERFECT FORWARD SECRECY                                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Chaque échange utilise une clé éphémère unique:                   │
│                                                                     │
│  Session 1: E1_priv, E1_pub → shared_secret_1                      │
│  Session 2: E2_priv, E2_pub → shared_secret_2                      │
│  Session 3: E3_priv, E3_pub → shared_secret_3                      │
│                                                                     │
│  Si WK_PRIV est compromis PLUS TARD:                               │
│  ✗ Ne peut PAS déchiffrer les sessions passées                     │
│  ✗ Car les clés éphémères ont été détruites                        │
│                                                                     │
│  Garantie: Compromission future ≠ compromission historique         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Authentification Mutuelle

```
Phase 1 garantit:
- Drone A est sûr de parler à Drone B (signature vérifiée)
- Drone B est sûr de parler à Drone A (signature vérifiée)
- Attaque MITM détectée (signatures invalides)
```

### Protection Anti-Replay

```
- Timestamps avec fenêtre de 30 secondes
- Nonces uniques par message
- Session IDs pour tracer l'échange
```

---

## 📝 Implémentation

```cpp
class KeyExchangeProtocol {
public:
    // Initialisation avec le Key Orchestrator
    bool init(KeyOrchestrator* orchestrator);

    // Phase 1: Initier handshake avec un peer
    bool initiate_handshake(const char* peer_id);

    // Phase 1: Recevoir et traiter handshake
    bool process_handshake(const uint8_t* message, size_t len);

    // Phase 2: Envoyer ma DEK chiffrée au peer
    bool send_encrypted_dek(const char* peer_id);

    // Phase 2: Recevoir et déchiffrer DEK du peer
    bool receive_encrypted_dek(const uint8_t* message, size_t len);

    // Phase 3: Envoyer ACK
    bool send_dek_ack(const char* peer_id);

    // Phase 3: Recevoir et vérifier ACK
    bool process_dek_ack(const uint8_t* message, size_t len);

    // Workflow complet (appelle les phases dans l'ordre)
    bool complete_exchange(const char* peer_id);

    // État de l'échange
    ExchangeState get_state(const char* peer_id) const;

private:
    KeyOrchestrator* _orchestrator;

    // Contexte d'échange par peer
    struct ExchangeContext {
        char peer_id[32];
        uint8_t peer_wk_pub[64];      // WK public du peer
        uint8_t ephemeral_priv[32];   // Ma clé éphémère (temporaire)
        uint8_t ephemeral_pub[64];
        char session_id[37];          // UUID
        ExchangeState state;
        uint32_t started_at;
    };
    ExchangeContext _exchanges[MAX_PEERS];

    // Helpers ECIES
    bool ecies_encrypt_dek(const uint8_t* dek, const uint8_t* peer_wk_pub,
                           EciesPackage* out);
    bool ecies_decrypt_dek(const EciesPackage* package, uint8_t* dek_out);

    // Helpers signature
    bool sign_message(const uint8_t* data, size_t len, uint8_t* signature);
    bool verify_signature(const uint8_t* data, size_t len,
                          const uint8_t* signature, const uint8_t* wk_pub);
};

enum ExchangeState {
    STATE_IDLE,
    STATE_HANDSHAKE_SENT,
    STATE_HANDSHAKE_RECEIVED,
    STATE_DEK_SENT,
    STATE_DEK_RECEIVED,
    STATE_ACK_SENT,
    STATE_COMPLETE,
    STATE_ERROR
};

struct EciesPackage {
    uint8_t ephemeral_pub[64];
    uint8_t nonce[12];
    uint8_t ciphertext[32];   // DEK chiffrée
    uint8_t tag[16];          // Poly1305 auth tag
};
```

---

## 📨 Formats de Messages

### Message 1: WK Handshake

```cpp
struct WkHandshakeMessage {
    uint8_t type;              // MSG_TYPE_WK_HANDSHAKE = 0x01
    char drone_id[32];
    uint8_t wk_public[64];     // Clé publique WK
    uint64_t timestamp;        // Unix timestamp ms
    uint8_t nonce[16];         // Anti-replay
    uint8_t signature[64];     // ECDSA signature
};
```

### Message 2: DEK Delivery

```cpp
struct DekDeliveryMessage {
    uint8_t type;              // MSG_TYPE_DEK_DELIVERY = 0x02
    char session_id[37];       // UUID
    char sender_id[32];
    EciesPackage encrypted_dek;
    uint64_t timestamp;
};
```

### Message 3: DEK ACK

```cpp
struct DekAckMessage {
    uint8_t type;              // MSG_TYPE_DEK_ACK = 0x03
    char session_id[37];
    uint8_t dek_hash[16];      // SHA256(DEK)[0:16]
    uint8_t status;            // 0=success, 1=error
};
```

---

## 🔗 Interface avec Feature 2.1 et 2.3

```cpp
// Depuis Feature 2.1 (Key Orchestrator):
// ─────────────────────────────────────
const uint8_t* my_wk_pub = orchestrator->get_wk_public();
const uint8_t* my_dek = orchestrator->get_my_dek();
orchestrator->ecies_encrypt(...);
orchestrator->ecies_decrypt(...);
orchestrator->store_peer_dek(peer_id, peer_dek);

// Vers Feature 2.3 (Communication Engine):
// ─────────────────────────────────────────
// Après exchange complet:
peer_dek_map[peer_id] = received_peer_dek;
// → Feature 2.3 peut maintenant communiquer avec ce peer
```

---

## ✅ Critères de Succès

- [ ] Phase 1: Échange WK_PUB avec signature ECDSA
- [ ] Phase 1: Vérification mutuelle des signatures
- [ ] Phase 2: Chiffrement ECIES de ma DEK avec WK_PUB du peer
- [ ] Phase 2: Déchiffrement DEK du peer avec ma WK_PRIV
- [ ] Phase 3: Confirmation ACK avec hash de DEK
- [ ] Perfect Forward Secrecy via clés éphémères
- [ ] Protection anti-replay (timestamps + nonces)
- [ ] Gestion multi-peers simultanés

---

## 📂 Fichiers à Créer/Modifier

| Fichier | Action | Description |
|---------|--------|-------------|
| `libraries/AP_HSM/KeyExchangeProtocol.h` | Créer | Déclarations classe |
| `libraries/AP_HSM/KeyExchangeProtocol.cpp` | Créer | Implémentation |
| `libraries/AP_HSM/CryptoMessages.h` | Créer | Structures messages |

---

**Dernière mise à jour**: 2026-01-23
