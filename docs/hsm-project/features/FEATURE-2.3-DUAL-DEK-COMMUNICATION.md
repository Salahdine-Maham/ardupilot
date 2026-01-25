# Feature 2.3: Dual-DEK Communication Engine
## Moteur de Communication à Double Clé Symétrique

**Statut**: En planification
**Dépendance**: Feature 2.2 (Key Exchange Protocol)

---

## 🎯 Objectif

Gérer la communication **bidirectionnelle** où chaque drone utilise **SA propre DEK** pour envoyer et **la DEK du peer** pour recevoir.

---

## 📊 Concept Dual-DEK

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MODÈLE DUAL-DEK                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  DRONE A                              DRONE B                       │
│  ════════                             ════════                      │
│                                                                     │
│  Possède:                             Possède:                      │
│  • DEK_A (sa propre DEK)              • DEK_B (sa propre DEK)      │
│  • DEK_B (reçue de Drone B)           • DEK_A (reçue de Drone A)   │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │                                                           │     │
│  │  ENVOI (Drone A → Drone B):                              │     │
│  │  ─────────────────────────                               │     │
│  │  Drone A chiffre avec DEK_A ──────▶ Drone B déchiffre   │     │
│  │                                     avec DEK_A           │     │
│  │                                                           │     │
│  │  ENVOI (Drone B → Drone A):                              │     │
│  │  ─────────────────────────                               │     │
│  │  Drone B chiffre avec DEK_B ──────▶ Drone A déchiffre   │     │
│  │                                     avec DEK_B           │     │
│  │                                                           │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  RÈGLE FONDAMENTALE:                                               │
│  ════════════════════                                              │
│  • J'ENVOIE avec MA DEK                                            │
│  • JE REÇOIS avec la DEK DU PEER                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Architecture du Moteur

```
┌─────────────────────────────────────────────────────────────────────┐
│              DUAL-DEK COMMUNICATION ENGINE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ OUTBOUND PIPELINE (Envoi avec MA DEK)                       │   │
│  │ ─────────────────────────────────────                       │   │
│  │                                                             │   │
│  │  Plaintext                                                  │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  ┌───────────────────────────────────┐                     │   │
│  │  │ ChaCha20-Poly1305(MY_DEK)         │                     │   │
│  │  │ + nonce (counter || peer_id)      │                     │   │
│  │  │ + AAD (associated data)           │                     │   │
│  │  └───────────────────────────────────┘                     │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  ┌───────────────────────────────────┐                     │   │
│  │  │ Ajout metadata:                   │                     │   │
│  │  │ - sender_id                       │                     │   │
│  │  │ - sequence_number                 │                     │   │
│  │  │ - timestamp                       │                     │   │
│  │  └───────────────────────────────────┘                     │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  Encrypted Message → Send to peer                          │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ INBOUND PIPELINE (Réception avec DEK DU PEER)               │   │
│  │ ─────────────────────────────────────────────               │   │
│  │                                                             │   │
│  │  Encrypted Message (from peer)                              │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  ┌───────────────────────────────────┐                     │   │
│  │  │ Identifier sender_id              │                     │   │
│  │  │ → Récupérer PEER_DEK              │                     │   │
│  │  └───────────────────────────────────┘                     │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  ┌───────────────────────────────────┐                     │   │
│  │  │ Anti-replay check:                │                     │   │
│  │  │ - Vérifier sequence_number        │                     │   │
│  │  │ - Vérifier timestamp              │                     │   │
│  │  └───────────────────────────────────┘                     │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  ┌───────────────────────────────────┐                     │   │
│  │  │ ChaCha20-Poly1305_decrypt         │                     │   │
│  │  │ (PEER_DEK, nonce, ciphertext)     │                     │   │
│  │  │ + Vérifier auth tag               │                     │   │
│  │  └───────────────────────────────────┘                     │   │
│  │      │                                                      │   │
│  │      ▼                                                      │   │
│  │  Plaintext → Process message                               │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ SESSION MANAGER                                             │   │
│  │ ───────────────                                             │   │
│  │                                                             │   │
│  │  • État de session par peer                                 │   │
│  │  • Compteurs de séquence (outbound/inbound)                │   │
│  │  • Détection de rotation DEK nécessaire                     │   │
│  │  • Métriques: messages/sec, latence, erreurs               │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📝 Implémentation

```cpp
class DualDekCommunicationEngine {
public:
    // Initialisation
    bool init(KeyOrchestrator* orchestrator, const char* my_drone_id);

    // ═══════════════════════════════════════════════════════════════
    // OUTBOUND: Envoyer avec MA DEK
    // ═══════════════════════════════════════════════════════════════

    /**
     * Chiffre et prépare un message pour un peer
     *
     * @param peer_id      ID du drone destinataire
     * @param plaintext    Données à chiffrer
     * @param len          Longueur des données
     * @param out_message  Buffer pour message chiffré (alloué par appelant)
     * @param out_len      Longueur du message chiffré
     * @return             true si succès
     */
    bool send_to_peer(const char* peer_id,
                      const uint8_t* plaintext, size_t len,
                      uint8_t* out_message, size_t* out_len);

    // ═══════════════════════════════════════════════════════════════
    // INBOUND: Recevoir avec DEK DU PEER
    // ═══════════════════════════════════════════════════════════════

    /**
     * Déchiffre un message reçu d'un peer
     *
     * @param encrypted_message  Message chiffré reçu
     * @param len                Longueur du message
     * @param out_plaintext      Buffer pour données déchiffrées
     * @param out_len            Longueur des données déchiffrées
     * @param out_sender_id      ID de l'émetteur (optionnel)
     * @return                   true si déchiffrement et vérification OK
     */
    bool receive_from_peer(const uint8_t* encrypted_message, size_t len,
                           uint8_t* out_plaintext, size_t* out_len,
                           char* out_sender_id = nullptr);

    // ═══════════════════════════════════════════════════════════════
    // GESTION DE SESSION
    // ═══════════════════════════════════════════════════════════════

    // Ajouter un peer après Key Exchange réussi
    bool add_peer_session(const char* peer_id, const uint8_t* peer_dek);

    // Supprimer un peer (déconnexion, timeout, etc.)
    bool remove_peer_session(const char* peer_id);

    // Vérifier si un peer est actif
    bool is_peer_active(const char* peer_id) const;

    // Obtenir statistiques de session
    SessionStats get_session_stats(const char* peer_id) const;

    // Vérifier si rotation DEK nécessaire
    bool needs_dek_rotation(const char* peer_id) const;

    // Notifier nouvelle DEK après rotation
    bool update_peer_dek(const char* peer_id, const uint8_t* new_peer_dek);
    bool update_my_dek(const uint8_t* new_my_dek);

private:
    KeyOrchestrator* _orchestrator;
    char _my_drone_id[32];

    // ═══════════════════════════════════════════════════════════════
    // STRUCTURE DE SESSION PAR PEER
    // ═══════════════════════════════════════════════════════════════

    struct PeerSession {
        char peer_id[32];
        uint8_t peer_dek[32];         // DEK du peer (pour RECEVOIR)

        // Compteurs outbound (mes messages envoyés à ce peer)
        uint64_t outbound_sequence;
        uint64_t outbound_nonce_counter;

        // Compteurs inbound (messages reçus de ce peer)
        uint64_t inbound_last_sequence;  // Pour anti-replay
        uint64_t inbound_window[64];     // Bitmap anti-replay (64 derniers)

        // Timestamps
        uint32_t created_at;
        uint32_t last_send_at;
        uint32_t last_receive_at;

        // Métriques
        uint32_t messages_sent;
        uint32_t messages_received;
        uint32_t decrypt_errors;

        // État
        bool active;
    };

    PeerSession _sessions[MAX_PEERS];
    uint8_t _session_count;

    // Ma propre DEK (pour ENVOYER)
    uint8_t _my_dek[32];
    bool _my_dek_loaded;

    // ═══════════════════════════════════════════════════════════════
    // HELPERS CRYPTO
    // ═══════════════════════════════════════════════════════════════

    // Chiffrement ChaCha20-Poly1305
    bool chacha20_poly1305_encrypt(const uint8_t* plaintext, size_t len,
                                    const uint8_t* key,
                                    const uint8_t* nonce,
                                    const uint8_t* aad, size_t aad_len,
                                    uint8_t* ciphertext,
                                    uint8_t* tag);

    // Déchiffrement ChaCha20-Poly1305
    bool chacha20_poly1305_decrypt(const uint8_t* ciphertext, size_t len,
                                    const uint8_t* key,
                                    const uint8_t* nonce,
                                    const uint8_t* aad, size_t aad_len,
                                    const uint8_t* tag,
                                    uint8_t* plaintext);

    // Génération de nonce unique
    void generate_nonce(const char* peer_id, uint64_t counter, uint8_t* nonce);

    // Anti-replay
    bool check_and_update_replay_window(PeerSession* session, uint64_t seq);

    // Recherche de session
    PeerSession* find_session(const char* peer_id);
};
```

---

## 📨 Format de Message Chiffré

```cpp
struct EncryptedDataMessage {
    // Header (non chiffré, mais authentifié via AAD)
    uint8_t type;              // MSG_TYPE_DATA = 0x10
    uint8_t version;           // Protocol version = 1
    char sender_id[32];        // ID de l'émetteur
    char receiver_id[32];      // ID du destinataire
    uint64_t sequence;         // Numéro de séquence (anti-replay)
    uint64_t timestamp;        // Unix timestamp ms

    // Crypto
    uint8_t nonce[12];         // Nonce ChaCha20
    uint16_t payload_len;      // Longueur du payload chiffré

    // Payload chiffré (variable length)
    uint8_t ciphertext[];      // Données chiffrées

    // Auth tag (à la fin)
    // uint8_t tag[16];        // Poly1305 auth tag
};

// Associated Authenticated Data (AAD)
// = header complet (type → payload_len)
// Garantit que le header n'a pas été modifié
```

---

## 🔐 Protection Anti-Replay

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ANTI-REPLAY PROTECTION                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Mécanisme: Sliding Window (64 messages)                           │
│                                                                     │
│  inbound_last_sequence = 1000                                       │
│  inbound_window = bitmap des 64 derniers                           │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Window: [937 ─────────────────────────────────────── 1000]   │  │
│  │         │                                              │      │  │
│  │         └── Rejeté (trop vieux)                        │      │  │
│  │                                                   Accepté     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  Règles:                                                            │
│  • seq > last_sequence + 64  → Accepté, window avance              │
│  • seq <= last_sequence - 64 → REJETÉ (trop vieux)                 │
│  • seq dans window           → Vérifier bitmap                     │
│    - Bit déjà set            → REJETÉ (replay!)                    │
│    - Bit non set             → Accepté, set bit                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Gestion de Session

```cpp
struct SessionStats {
    char peer_id[32];

    // Compteurs
    uint32_t messages_sent;
    uint32_t messages_received;
    uint32_t bytes_sent;
    uint32_t bytes_received;

    // Erreurs
    uint32_t decrypt_errors;       // Auth tag invalid
    uint32_t replay_attempts;      // Replay détectés
    uint32_t unknown_sender;       // Sender non reconnu

    // Timing
    uint32_t session_duration_sec;
    uint32_t last_activity_sec;

    // Rotation
    bool rotation_needed;
    uint32_t messages_until_rotation;
};

// Critères de rotation DEK
bool DualDekCommunicationEngine::needs_dek_rotation(const char* peer_id) const {
    PeerSession* session = find_session(peer_id);
    if (!session) return false;

    // Rotation après 10,000 messages
    if (session->messages_sent + session->messages_received > 10000) {
        return true;
    }

    // Rotation après 1 heure
    uint32_t now = AP_HAL::millis() / 1000;
    if (now - session->created_at > 3600) {
        return true;
    }

    return false;
}
```

---

## 🔄 Workflow de Rotation DEK

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ROTATION DEK EN VOL                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Engine détecte: needs_dek_rotation(peer_id) = true             │
│                                                                     │
│  2. Notifie Key Orchestrator:                                       │
│     orchestrator->rotate_dek()                                      │
│     → Nouvelle MY_DEK générée                                       │
│                                                                     │
│  3. Relance Key Exchange avec le peer:                              │
│     key_exchange->initiate_exchange(peer_id)                        │
│     → Échange des nouvelles DEK                                     │
│                                                                     │
│  4. Met à jour les sessions:                                        │
│     engine->update_my_dek(new_my_dek)                              │
│     engine->update_peer_dek(peer_id, new_peer_dek)                 │
│                                                                     │
│  5. Reset des compteurs de session                                  │
│                                                                     │
│  IMPORTANT: Pendant la rotation, les messages en transit           │
│  peuvent utiliser l'ancienne ou nouvelle DEK.                       │
│  → Garder l'ancienne DEK en backup pendant 30 secondes             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🌐 Support Multi-Peers (Réseau Maillé)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RÉSEAU MAILLÉ DE DRONES                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                         DRONE_A                                     │
│                        /   │   \                                   │
│                       /    │    \                                  │
│                      /     │     \                                 │
│               DRONE_B   DRONE_C   DRONE_D                          │
│                   \       /  \       /                             │
│                    \     /    \     /                              │
│                     \   /      \   /                               │
│                    DRONE_E    DRONE_F                              │
│                                                                     │
│  Chaque drone maintient:                                            │
│  • SA DEK unique (pour envoyer à TOUS)                             │
│  • Une DEK par peer (pour recevoir de chaque peer)                 │
│                                                                     │
│  Exemple DRONE_A:                                                   │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ my_dek = DEK_A                                             │    │
│  │ peer_deks = {                                              │    │
│  │   "DRONE_B": DEK_B,                                        │    │
│  │   "DRONE_C": DEK_C,                                        │    │
│  │   "DRONE_D": DEK_D                                         │    │
│  │ }                                                          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  Avantages:                                                         │
│  ✓ Traçabilité: On sait QUI a envoyé (vérifié par DEK)            │
│  ✓ Isolation: Compromission d'un drone n'affecte pas les autres   │
│  ✓ Évolutif: Ajouter un drone = 1 Key Exchange                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ✅ Critères de Succès

- [ ] Envoi avec MA DEK (ChaCha20-Poly1305)
- [ ] Réception avec DEK du PEER
- [ ] Génération de nonce unique par message
- [ ] Protection anti-replay (sliding window 64)
- [ ] Gestion sessions multi-peers simultanés
- [ ] Détection automatique besoin rotation DEK
- [ ] Support rotation DEK sans perte de messages
- [ ] Métriques de performance par session
- [ ] Gestion gracieuse des erreurs (peer inconnu, auth failed)

---

## 📂 Fichiers à Créer/Modifier

| Fichier | Action | Description |
|---------|--------|-------------|
| `libraries/AP_HSM/DualDekEngine.h` | Créer | Déclarations classe |
| `libraries/AP_HSM/DualDekEngine.cpp` | Créer | Implémentation |
| `libraries/AP_HSM/SessionManager.h` | Créer | Gestion sessions |
| `libraries/AP_HSM/AntiReplay.h` | Créer | Protection replay |

---

## 🔗 Intégration avec MAVLink

```cpp
// Dans GCS_MAVLink.cpp, modification de comm_send_buffer():

void comm_send_buffer(mavlink_channel_t chan, const uint8_t *buf, uint8_t len) {
    // ... existing code ...

    #if AP_HSM_ENABLED
    if (gcs().get_mav_encrypt() != 0 && is_payload) {
        DualDekEngine& engine = DualDekEngine::get_instance();

        // Déterminer le peer_id depuis le channel
        const char* peer_id = get_peer_id_for_channel(chan);

        // Chiffrer avec MA DEK
        uint8_t encrypted[MAX_PAYLOAD_SIZE + 48];  // +header+tag
        size_t encrypted_len;

        if (engine.send_to_peer(peer_id, buf, len, encrypted, &encrypted_len)) {
            mavlink_comm_port[chan]->write(encrypted, encrypted_len);
        }
    }
    #endif
}
```

---

**Dernière mise à jour**: 2026-01-23
