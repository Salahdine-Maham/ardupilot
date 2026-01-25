# Feature 1: Key Orchestrator

**Version**: 2.0
**Date**: 2026-01-24
**Statut**: 🔄 À implémenter

---

## Objectif

Gestionnaire centralisé de clés cryptographiques qui orchestre la génération, le stockage sécurisé et le cycle de vie des clés à 3 niveaux (MK → WK → DEK).

## Dépendances

- HSM LeMonolith v0.6 connecté via UART
- Bibliothèque micro-ecc (P-256)
- AP_Crypto (HKDF-SHA256)

## Hiérarchie des Clés

```
┌─────────────────────────────────────────────────────────────┐
│                    KEY ORCHESTRATOR                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  NIVEAU 1: MASTER KEY (MK)                                   │
│  ├── Algorithme: ChaCha20-256 bits (32 bytes)                │
│  ├── Génération: hal.util->get_random_vals()                 │
│  ├── Stockage: HSM @0x0100                                   │
│  ├── Protection: Jamais exportée en clair après init         │
│  └── Durée de vie: Permanente par mission                    │
│                                                               │
│          │                                                    │
│          │ HKDF-SHA256(MK, salt, "WrapperKey-P256-v1")       │
│          ▼                                                    │
│                                                               │
│  NIVEAU 2: WRAPPER KEY (WK)                                  │
│  ├── Algorithme: secp256r1 (P-256)                           │
│  ├── WK_private: Dérivée de MK via HKDF                      │
│  ├── WK_public: Calculée depuis WK_private (micro-ecc)       │
│  ├── Stockage: WK_priv wrappée HSM @0x0120                   │
│  └── Usage: Échange sécurisé des DEK (ECIES)                 │
│                                                               │
│          │                                                    │
│          │ Génération aléatoire                               │
│          ▼                                                    │
│                                                               │
│  NIVEAU 3: DATA ENCRYPTION KEY (DEK)                         │
│  ├── Algorithme: ChaCha20-256 bits (32 bytes)                │
│  ├── Génération: hal.util->get_random_vals()                 │
│  ├── Stockage: DEK wrappée HSM @0x0140                       │
│  └── Usage: Chiffrement payload MAVLink                      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Interface C++

### Fichier: `libraries/AP_HSM/KeyOrchestrator.h`

```cpp
#pragma once

#include <stdint.h>
#include <stdbool.h>

class AP_HSM;  // Forward declaration

class KeyOrchestrator {
public:
    KeyOrchestrator();

    // Singleton
    static KeyOrchestrator& get_singleton();

    // Initialisation complète (appelée au boot)
    bool init(AP_HSM* hsm);

    // === NIVEAU 1: MASTER KEY ===
    bool generate_master_key();
    bool store_mk_to_hsm();
    bool load_mk_from_hsm();
    bool has_master_key() const { return mk_loaded; }

    // === NIVEAU 2: WRAPPER KEY ===
    bool derive_wrapper_key();           // HKDF(MK) → WK_priv
    bool compute_wk_public();            // WK_priv → WK_pub
    bool store_wk_to_hsm();              // Wrapper et stocker
    bool load_wk_from_hsm();             // Charger et unwrap
    const uint8_t* get_wk_public() const { return wk_public; }
    const uint8_t* get_wk_private() const { return wk_private; }
    bool has_wrapper_key() const { return wk_loaded; }

    // === NIVEAU 3: DEK ===
    bool generate_dek();
    bool store_dek_to_hsm();
    bool load_dek_from_hsm();
    const uint8_t* get_my_dek() const { return my_dek; }
    bool has_dek() const { return dek_loaded; }

    // === CYCLE DE VIE ===
    bool init_mission_keys();            // Génère toute la hiérarchie
    bool restore_mission_keys();         // Charge depuis HSM
    bool is_fully_initialized() const;

    // === WRAPPING ===
    bool wrap_key(const uint8_t* key, uint8_t* wrapped, uint8_t* tag);
    bool unwrap_key(const uint8_t* wrapped, const uint8_t* tag, uint8_t* key);

private:
    AP_HSM* _hsm = nullptr;

    // Niveau 1: Master Key
    uint8_t master_key[32];
    bool mk_loaded = false;

    // Niveau 2: Wrapper Key (P-256)
    uint8_t wk_private[32];
    uint8_t wk_public[64];              // Format non compressé X||Y
    bool wk_loaded = false;

    // Niveau 3: DEK
    uint8_t my_dek[32];
    bool dek_loaded = false;

    // Tags HMAC pour vérification intégrité
    uint8_t wk_tag[32];
    uint8_t dek_tag[32];

    // Helpers
    bool derive_p256_scalar_from_hkdf(const uint8_t* ikm, uint8_t* scalar);
    bool is_valid_p256_scalar(const uint8_t* scalar);
    void secure_zero(uint8_t* buf, size_t len);
};
```

## Implémentation Détaillée

### Génération Master Key

```cpp
bool KeyOrchestrator::generate_master_key() {
    printf("KeyOrch: Génération Master Key (256 bits)...\n");

    // Générer 32 bytes aléatoires
    if (!hal.util->get_random_vals(master_key, 32)) {
        printf("KeyOrch: ERREUR - Échec génération aléatoire MK\n");
        return false;
    }

    mk_loaded = true;
    printf("KeyOrch: ✓ Master Key générée\n");
    return true;
}
```

### Dérivation Wrapper Key depuis MK

```cpp
bool KeyOrchestrator::derive_wrapper_key() {
    if (!mk_loaded) {
        printf("KeyOrch: ERREUR - Master Key non disponible\n");
        return false;
    }

    printf("KeyOrch: Dérivation Wrapper Key (P-256) depuis MK...\n");

    // HKDF-SHA256 pour dériver scalar P-256
    if (!derive_p256_scalar_from_hkdf(master_key, wk_private)) {
        printf("KeyOrch: ERREUR - Échec dérivation HKDF\n");
        return false;
    }

    // Calculer clé publique depuis clé privée
    uECC_Curve curve = uECC_secp256r1();
    if (uECC_compute_public_key(wk_private, wk_public, curve) != 1) {
        printf("KeyOrch: ERREUR - Échec calcul WK_public\n");
        return false;
    }

    wk_loaded = true;
    printf("KeyOrch: ✓ Wrapper Key dérivée (P-256)\n");

    // Afficher clé publique (pour debug)
    printf("KeyOrch: WK_PUB: ");
    for (int i = 0; i < 16; i++) printf("%02X", wk_public[i]);
    printf("...\n");

    return true;
}

bool KeyOrchestrator::derive_p256_scalar_from_hkdf(const uint8_t* ikm, uint8_t* scalar) {
    const char* salt = "ArduPilot-HSM-Salt-v2";
    const char* info = "WrapperKey-P256-v1";

    uint8_t candidate[32];
    uint8_t counter = 0;

    // Boucle jusqu'à obtenir un scalar valide (< ordre courbe)
    // En pratique: 1 itération suffit dans 99.99999% des cas
    do {
        char info_with_counter[64];
        if (counter == 0) {
            snprintf(info_with_counter, sizeof(info_with_counter), "%s", info);
        } else {
            snprintf(info_with_counter, sizeof(info_with_counter), "%s-%d", info, counter);
        }

        // HKDF-SHA256
        hkdf_sha256(
            (const uint8_t*)salt, strlen(salt),  // Salt
            ikm, 32,                              // IKM (Master Key)
            (const uint8_t*)info_with_counter, strlen(info_with_counter),  // Info
            candidate, 32                         // Output
        );

        counter++;
    } while (!is_valid_p256_scalar(candidate) && counter < 255);

    if (counter >= 255) {
        return false;  // Échec (quasi-impossible)
    }

    memcpy(scalar, candidate, 32);
    secure_zero(candidate, 32);
    return true;
}
```

### Génération DEK

```cpp
bool KeyOrchestrator::generate_dek() {
    printf("KeyOrch: Génération DEK (256 bits)...\n");

    if (!hal.util->get_random_vals(my_dek, 32)) {
        printf("KeyOrch: ERREUR - Échec génération aléatoire DEK\n");
        return false;
    }

    dek_loaded = true;
    printf("KeyOrch: ✓ DEK générée\n");
    return true;
}
```

### Wrapping avec Master Key

```cpp
bool KeyOrchestrator::wrap_key(const uint8_t* key, uint8_t* wrapped, uint8_t* tag) {
    if (!mk_loaded) {
        printf("KeyOrch: ERREUR - MK non disponible pour wrapping\n");
        return false;
    }

    // XOR avec Master Key
    for (int i = 0; i < 32; i++) {
        wrapped[i] = key[i] ^ master_key[i];
    }

    // HMAC-SHA256 pour intégrité
    hmac_sha256(master_key, 32, wrapped, 32, tag);

    return true;
}

bool KeyOrchestrator::unwrap_key(const uint8_t* wrapped, const uint8_t* tag, uint8_t* key) {
    if (!mk_loaded) {
        printf("KeyOrch: ERREUR - MK non disponible pour unwrapping\n");
        return false;
    }

    // Vérifier HMAC d'abord
    uint8_t computed_tag[32];
    hmac_sha256(master_key, 32, wrapped, 32, computed_tag);

    if (memcmp(tag, computed_tag, 32) != 0) {
        printf("KeyOrch: ERREUR - Tag HMAC invalide (données corrompues)\n");
        secure_zero(computed_tag, 32);
        return false;
    }

    // XOR pour récupérer clé
    for (int i = 0; i < 32; i++) {
        key[i] = wrapped[i] ^ master_key[i];
    }

    secure_zero(computed_tag, 32);
    return true;
}
```

### Initialisation Mission Complète

```cpp
bool KeyOrchestrator::init_mission_keys() {
    printf("KeyOrch: === INITIALISATION MISSION ===\n");

    // Étape 1: Générer Master Key
    if (!generate_master_key()) return false;
    if (!store_mk_to_hsm()) return false;

    // Étape 2: Dériver Wrapper Key
    if (!derive_wrapper_key()) return false;
    if (!store_wk_to_hsm()) return false;

    // Étape 3: Générer DEK
    if (!generate_dek()) return false;
    if (!store_dek_to_hsm()) return false;

    printf("KeyOrch: ✓ Hiérarchie de clés initialisée\n");
    printf("KeyOrch: ✓ MK @0x0100, WK @0x0120, DEK @0x0140\n");

    return true;
}

bool KeyOrchestrator::restore_mission_keys() {
    printf("KeyOrch: === RESTAURATION CLÉS DEPUIS HSM ===\n");

    // Charger MK
    if (!load_mk_from_hsm()) {
        printf("KeyOrch: Aucune MK trouvée, nouvelle mission requise\n");
        return false;
    }

    // Charger et unwrap WK
    if (!load_wk_from_hsm()) {
        printf("KeyOrch: WK non trouvée ou corrompue\n");
        return false;
    }

    // Charger et unwrap DEK
    if (!load_dek_from_hsm()) {
        printf("KeyOrch: DEK non trouvée ou corrompue\n");
        return false;
    }

    printf("KeyOrch: ✓ Clés restaurées depuis HSM\n");
    return true;
}
```

## Stockage HSM

### Adresses EEPROM

| Offset | Contenu | Taille |
|--------|---------|--------|
| 0x0100 | Master Key | 32 bytes |
| 0x0120 | Wrapped WK_private | 32 bytes |
| 0x0140 | Wrapped DEK | 32 bytes |
| 0x0160 | HMAC tag WK | 32 bytes |
| 0x0180 | HMAC tag DEK | 32 bytes |

### APDU Utilisées

```
WRITE MK:      A 00D6010020<64 hex chars MK>
READ MK:       A 00B0010020

WRITE WK:      A 00D6012020<64 hex chars wrapped_wk>
READ WK:       A 00B0012020

WRITE DEK:     A 00D6014020<64 hex chars wrapped_dek>
READ DEK:      A 00B0014020

WRITE WK_TAG:  A 00D6016020<64 hex chars tag>
READ WK_TAG:   A 00B0016020

WRITE DEK_TAG: A 00D6018020<64 hex chars tag>
READ DEK_TAG:  A 00B0018020
```

## Tests de Validation

### Test 1: Génération Hiérarchie

```bash
# Attendre logs au boot
grep "KeyOrch:" /tmp/ardupilot.log

# Résultat attendu:
# KeyOrch: === INITIALISATION MISSION ===
# KeyOrch: Génération Master Key (256 bits)...
# KeyOrch: ✓ Master Key générée
# KeyOrch: Dérivation Wrapper Key (P-256) depuis MK...
# KeyOrch: ✓ Wrapper Key dérivée (P-256)
# KeyOrch: WK_PUB: 7A593180860C4037...
# KeyOrch: Génération DEK (256 bits)...
# KeyOrch: ✓ DEK générée
# KeyOrch: ✓ Hiérarchie de clés initialisée
```

### Test 2: Restauration après Reboot

```bash
# Reboot et vérifier restauration
# Résultat attendu:
# KeyOrch: === RESTAURATION CLÉS DEPUIS HSM ===
# KeyOrch: ✓ Master Key chargée depuis HSM
# KeyOrch: ✓ Wrapper Key restaurée
# KeyOrch: ✓ DEK restaurée
# KeyOrch: ✓ Clés restaurées depuis HSM
```

### Test 3: Intégrité HMAC

Modifier un byte dans HSM et vérifier que le tag HMAC détecte la corruption.

## Critères de Succès

- [ ] Master Key générée et stockée dans HSM
- [ ] Wrapper Key dérivée via HKDF (scalar P-256 valide)
- [ ] WK_public calculée correctement
- [ ] DEK générée et stockée wrappée
- [ ] Restauration depuis HSM fonctionne
- [ ] Tags HMAC détectent les corruptions
- [ ] Aucun secret loggé en clair

## Sécurité

**À NE JAMAIS FAIRE:**
- Logger `master_key` en production
- Logger `wk_private` en production
- Logger `my_dek` en production
- Transmettre MK ou WK_private via MAVLink

**À TOUJOURS FAIRE:**
- `secure_zero()` sur buffers temporaires
- Vérifier tags HMAC avant unwrap
- Utiliser RNG hardware si disponible

---

**Prochaine Feature**: [FEATURE-2-KEY-EXCHANGE-PROTOCOL.md](FEATURE-2-KEY-EXCHANGE-PROTOCOL.md)
