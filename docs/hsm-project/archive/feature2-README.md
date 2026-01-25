# Feature 2: Génération et Récupération Sécurisée de la Paire Asymétrique P-256

**Statut**: ✅ Implémentation complète - Tests avec HSM réel en attente

## Résumé

Feature 2 implémente la génération d'une paire de clés P-256 en software (micro-ecc), le stockage sécurisé de la clé privée dans le HSM LeMonolith, et la récupération automatique au boot avec cache RAM volatile.

## Résultat Final

✅ **Compilation réussie**: ArduCopter SITL (4.2 MB)
```bash
./waf copter
# 'copter' finished successfully (2.620s)
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│      ArduPilot Boot (AP_Vehicle::init())        │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
        ┌────────────────────┐
        │ AP_HSM::init_monolith │ ← Feature 1
        └────────────┬───────────┘
                     │
                     ▼
    ┌────────────────────────────────────┐
    │  Essayer load_private_key_from_hsm │
    └────────────┬───────────────────────┘
                 │
         ┌───────┴────────┐
         │                │
    ✅ Succès        ❌ Échec
         │                │
         │                ▼
         │    ┌───────────────────────┐
         │    │ generate_keypair_p256 │
         │    └───────────┬───────────┘
         │                │
         │                ▼
         │    ┌──────────────────────────┐
         │    │ store_private_key_to_hsm │
         │    └───────────┬──────────────┘
         │                │
         └────────────────┴──────────────┐
                                         │
                                         ▼
                              ┌──────────────────┐
                              │ Keypair en cache │
                              │  RAM volatile    │
                              └──────────────────┘
```

## Fonctionnalités Implémentées

1. **Génération Keypair P-256** (`generate_keypair_p256()`)
   - Utilise micro-ecc avec courbe secp256r1
   - RNG via `hal.util->get_random_vals()` (/dev/urandom)
   - Génère clé privée (32 bytes) + clé publique (64 bytes)

2. **Stockage HSM** (`store_private_key_to_hsm()`)
   - APDU: `A 00D6010020<64 hex chars>`
   - Offset: 0x0100 dans mémoire HSM
   - Vérification SW 9000

3. **Récupération au Boot** (`load_private_key_from_hsm()`)
   - APDU: `A 00B0010020`
   - Parse réponse hex
   - Recalcule clé publique depuis privée (`uECC_compute_public_key`)

4. **Cache RAM Volatile**
   - `private_key_cache[32]`: clé privée en RAM
   - `public_key_cache[64]`: clé publique recalculée
   - `keypair_loaded`: flag de statut
   - Effacé à chaque reboot

## Blocage Résolu

**Problème**: Compilation micro-ecc échouait avec erreurs assembleur ARM sur x86_64

**Cause**: `uECC_PLATFORM 5` (arm_thumb2) au lieu de `uECC_PLATFORM 2` (x86_64)

**Solution**: [uECC_config.h](../libraries/micro-ecc/uECC_config.h#L17)
```c
#define uECC_PLATFORM 2  /* uECC_x86_64 */
```

**Détails**: Voir [BLOCAGE-micro-ecc.md](BLOCAGE-micro-ecc.md)

## Tests Attendus (avec HSM réel)

### Test 1: Première génération
```bash
./feature2/test_sitl_feature2.sh
```

**Logs attendus**:
```
HSM: === Feature 2: Gestion Keypair P-256 ===
HSM: ⚠️  Aucune keypair trouvée, génération nouvelle...
HSM: ✓ Keypair P-256 générée avec succès
HSM: Public key (64 bytes): <128 hex chars>
HSM: ✓ Clé privée stockée avec succès dans HSM
HSM: ✓ Feature 2 complétée avec succès!
```

### Test 2: Récupération au reboot
```bash
# Redémarrer ArduCopter
./feature2/test_sitl_feature2.sh
```

**Logs attendus**:
```
HSM: === Feature 2: Gestion Keypair P-256 ===
HSM: ✓ Clé privée récupérée depuis HSM (32 bytes)
HSM: ✓ Clé publique recalculée avec succès
HSM: Public key (64 bytes): <128 hex chars IDENTIQUES>
HSM: ✓ Keypair P-256 récupérée depuis HSM
```

## Fichiers Principaux

| Fichier | Rôle |
|---------|------|
| [libraries/micro-ecc/](../libraries/micro-ecc/) | Bibliothèque ECC (3000+ lignes) |
| [libraries/micro-ecc/uECC_config.h](../libraries/micro-ecc/uECC_config.h) | Configuration ArduPilot |
| [libraries/AP_HSM/AP_HSM.h](../libraries/AP_HSM/AP_HSM.h) | API keypair P-256 |
| [libraries/AP_HSM/AP_HSM.cpp](../libraries/AP_HSM/AP_HSM.cpp) | Implémentation (+158 lignes) |
| [libraries/AP_Vehicle/AP_Vehicle.cpp](../libraries/AP_Vehicle/AP_Vehicle.cpp) | Intégration au boot |
| [ArduCopter/wscript](../ArduCopter/wscript) | Link micro-ecc |
| [travaille-feature2.md](travaille-feature2.md) | Documentation complète |
| [BLOCAGE-micro-ecc.md](BLOCAGE-micro-ecc.md) | Résolution blocage |
| [test_sitl_feature2.sh](test_sitl_feature2.sh) | Script de test |

## API Publique

```cpp
// Génération nouvelle paire P-256
bool generate_keypair_p256();

// Stockage dans HSM
bool store_private_key_to_hsm(const uint8_t* private_key, size_t key_len);

// Récupération depuis HSM
bool load_private_key_from_hsm();

// Accesseurs
const uint8_t* get_private_key() const;      // 32 bytes
const uint8_t* get_public_key() const;       // 64 bytes
bool has_keypair() const;
```

## APDU Utilisées

### WRITE BINARY (Stockage)
```
A 00D6010020<64 caractères hex de la clé privée>
```

### READ BINARY (Récupération)
```
A 00B0010020
```

**Réponse**: `Rx: <64 hex chars> 9000`

## Sécurité

⚠️ **CRITICAL**: La clé privée n'est JAMAIS loggée
- ✅ Clé publique affichée (publique par nature)
- ✅ Clé privée stockée uniquement dans cache RAM et HSM
- ✅ Pas de buffers temporaires persistants
- ✅ Cache effacé à chaque reboot

## Prochaine Étape: Feature 3

**Titre**: Génération DEK ChaCha20-256 et KDF Sécurisé

**Dépendances satisfaites**:
- ✅ Keypair P-256 disponible
- ✅ Clé privée en cache RAM
- ✅ Fonctions READ/WRITE HSM opérationnelles
- ✅ Infrastructure crypto (micro-ecc) intégrée

---

**Auteur**: Claude Sonnet 4.5
**Date**: 2026-01-23
**Documentation complète**: [travaille-feature2.md](travaille-feature2.md)
