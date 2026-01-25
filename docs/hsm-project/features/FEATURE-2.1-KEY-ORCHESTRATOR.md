# Feature 2.1: Key Orchestrator
## Gestionnaire Centralisé de Clés Cryptographiques

**Statut**: En planification
**Dépendance**: Feature 1 (HSM Init)

---

## 🎯 Objectif

Orchestrer la **génération**, le **stockage sécurisé** et le **cycle de vie** des clés à 3 niveaux pour le système de communication drone-drone.

---

## 📊 Hiérarchie des Clés (3 Niveaux)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HIÉRARCHIE DE CLÉS                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  NIVEAU 1: MASTER KEY (MK)                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Type      : Symétrique                                      │   │
│  │ Algorithme: ChaCha20, 256 bits                              │   │
│  │ Stockage  : HSM EXCLUSIVEMENT (jamais en RAM claire)        │   │
│  │ Durée vie : Permanente (protégée par HSM)                   │   │
│  │ Usage     : Source de dérivation pour WK                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              │ HKDF-SHA256                          │
│                              ▼                                      │
│  NIVEAU 2: WRAPPER KEY (WK)                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Type      : Asymétrique (paire de clés)                     │   │
│  │ Algorithme: secp256r1 (ECC P-256)                           │   │
│  │ Génération: HKDF-SHA256(MK) → clé privée ECC                │   │
│  │ Stockage  : Clé privée HSM, clé publique partageable        │   │
│  │ Durée vie : Par mission                                     │   │
│  │ Usage     : Chiffrement ECIES des DEK échangées             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              │ Génération aléatoire                 │
│                              ▼                                      │
│  NIVEAU 3: DATA ENCRYPTION KEY (DEK)                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Type      : Symétrique                                      │   │
│  │ Algorithme: ChaCha20, 256 bits                              │   │
│  │ Génération: RNG crypto (/dev/urandom ou TRNG)               │   │
│  │ Stockage  : RAM volatile (cache sécurisé)                   │   │
│  │ Durée vie : Par session (1h ou 10,000 messages)             │   │
│  │ Usage     : Chiffrement des données MAVLink                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Fonctionnalités Principales

### 1. Génération Sécurisée des Clés

```cpp
class KeyOrchestrator {
public:
    // Génère la hiérarchie complète au démarrage
    bool generate_key_hierarchy(const char* drone_id);

    // Niveau 1: Master Key dans HSM
    bool generate_master_key();

    // Niveau 2: Dérivation Wrapper Key depuis MK
    bool derive_wrapper_key_from_master();

    // Niveau 3: Génération DEK de session
    bool generate_session_dek();
};
```

### 2. Interface HSM pour Master Key

```
┌─────────────────────────────────────────────────────────────────┐
│                    ISOLATION MASTER KEY                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  La Master Key ne quitte JAMAIS le HSM!                        │
│                                                                 │
│  Opérations supportées:                                         │
│  ┌───────────────┐                                             │
│  │ HSM_DERIVE    │ → HKDF(MK, info) → WK_PRIVATE              │
│  │ HSM_EXPORT_PUB│ → Exporte WK_PUBLIC seulement              │
│  │ HSM_ROTATE_MK │ → Génère nouvelle MK (admin only)          │
│  └───────────────┘                                             │
│                                                                 │
│  Opérations INTERDITES:                                         │
│  ✗ HSM_EXPORT_MK  (jamais!)                                    │
│  ✗ HSM_READ_MK    (jamais!)                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Dérivation HKDF: ChaCha20 → secp256r1

```
Processus de dérivation:

MK (256 bits, symétrique ChaCha20)
         │
         ▼
┌─────────────────────────────────────┐
│ HKDF-SHA256                         │
│ - Salt: drone_id || mission_id      │
│ - Info: "wrapper_key_derivation"    │
│ - Output: 32 bytes                  │
└─────────────────────────────────────┘
         │
         ▼
WK_PRIVATE (32 bytes, scalaire ECC)
         │
         ▼
┌─────────────────────────────────────┐
│ uECC_compute_public_key()           │
│ Calcul point sur courbe P-256       │
└─────────────────────────────────────┘
         │
         ▼
WK_PUBLIC (64 bytes, point X||Y)
```

### 4. Rotation Automatique des Clés

```cpp
// Politique de rotation
struct RotationPolicy {
    // DEK: rotation fréquente
    uint32_t dek_max_messages = 10000;    // Après 10k messages
    uint32_t dek_max_duration_sec = 3600; // Ou après 1 heure

    // WK: rotation par mission
    bool wk_rotate_on_mission_end = true;

    // MK: rotation rare (admin)
    bool mk_rotate_requires_physical_access = true;
};

bool KeyOrchestrator::check_and_rotate() {
    if (should_rotate_dek()) {
        return rotate_keys(LEVEL_DEK);
    }
    return true;
}
```

### 5. Cache Sécurisé en Mémoire

```cpp
// Cache RAM volatile (effacé au reboot)
struct SecureKeyCache {
    // Niveau 2: WK (dérivée depuis HSM)
    uint8_t wk_private[32];    // Clé privée ECC
    uint8_t wk_public[64];     // Clé publique ECC
    bool wk_loaded;

    // Niveau 3: DEK (générée localement)
    uint8_t my_dek[32];        // MA DEK pour envoyer
    bool dek_generated;

    // DEKs des peers (reçues via Key Exchange)
    struct PeerDek {
        char peer_id[32];
        uint8_t dek[32];       // DEK du peer pour recevoir
        uint32_t expires_at;
    };
    PeerDek peer_deks[MAX_PEERS];
    uint8_t peer_count;
};
```

### 6. Logs Audit Cryptographiques

```cpp
// Événements à logger
enum CryptoAuditEvent {
    AUDIT_MK_GENERATED,
    AUDIT_WK_DERIVED,
    AUDIT_DEK_GENERATED,
    AUDIT_DEK_ROTATED,
    AUDIT_KEY_EXCHANGE_INITIATED,
    AUDIT_KEY_EXCHANGE_COMPLETED,
    AUDIT_CRYPTO_ERROR
};

void KeyOrchestrator::log_audit(CryptoAuditEvent event, const char* details);
```

---

## 📝 API Publique

```cpp
class KeyOrchestrator {
public:
    // Singleton
    static KeyOrchestrator& get_instance();

    // Initialisation
    bool init(AP_HSM* hsm);
    bool generate_key_hierarchy(const char* drone_id);

    // Accesseurs Niveau 2 (WK)
    const uint8_t* get_wk_public() const;
    bool has_wrapper_key() const;

    // Accesseurs Niveau 3 (DEK)
    const uint8_t* get_my_dek() const;
    bool has_dek() const;

    // Gestion DEK peers (pour Feature 2.3)
    bool store_peer_dek(const char* peer_id, const uint8_t* peer_dek);
    const uint8_t* get_peer_dek(const char* peer_id) const;

    // Opérations crypto (utilisent HSM pour MK)
    bool ecies_encrypt(const uint8_t* plaintext, size_t len,
                       const uint8_t* peer_wk_pub,
                       uint8_t* ciphertext, size_t* out_len);
    bool ecies_decrypt(const uint8_t* ciphertext, size_t len,
                       uint8_t* plaintext, size_t* out_len);

    // Rotation
    bool rotate_dek();
    bool check_rotation_needed();

private:
    AP_HSM* _hsm;
    SecureKeyCache _cache;
    RotationPolicy _policy;
};
```

---

## 🔗 Interface avec Feature 2.2 (Key Exchange)

```cpp
// Feature 2.1 fournit à Feature 2.2:

// 1. Ma clé publique WK pour l'échange
const uint8_t* my_wk_pub = key_orchestrator.get_wk_public();

// 2. Ma DEK à chiffrer et envoyer
const uint8_t* my_dek = key_orchestrator.get_my_dek();

// 3. Capacité de chiffrement ECIES avec WK du peer
key_orchestrator.ecies_encrypt(my_dek, 32, peer_wk_pub, encrypted_dek, &len);

// 4. Capacité de déchiffrement ECIES avec ma WK privée
key_orchestrator.ecies_decrypt(encrypted_peer_dek, len, peer_dek, &dek_len);

// 5. Stockage de la DEK du peer reçue
key_orchestrator.store_peer_dek(peer_id, peer_dek);
```

---

## ✅ Critères de Succès

- [ ] Master Key générée et stockée dans HSM (jamais exposée)
- [ ] Wrapper Key dérivée via HKDF depuis MK
- [ ] DEK générée aléatoirement pour chaque session
- [ ] Cache RAM sécurisé pour WK et DEK
- [ ] Rotation automatique DEK selon politique
- [ ] Interface ECIES fonctionnelle pour Key Exchange
- [ ] Logs audit de tous les événements crypto

---

## 📂 Fichiers à Créer/Modifier

| Fichier | Action | Description |
|---------|--------|-------------|
| `libraries/AP_HSM/KeyOrchestrator.h` | Créer | Déclarations classe |
| `libraries/AP_HSM/KeyOrchestrator.cpp` | Créer | Implémentation |
| `libraries/AP_HSM/AP_HSM.h` | Modifier | Ajouter interface HSM pour MK |
| `libraries/AP_HSM/AP_HSM.cpp` | Modifier | Implémenter ops HSM |

---

**Dernière mise à jour**: 2026-01-23
