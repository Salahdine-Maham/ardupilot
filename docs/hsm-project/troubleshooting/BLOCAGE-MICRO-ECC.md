# Blocage: Compilation micro-ecc dans ArduPilot SITL

**Date**: 2026-01-22
**Statut**: BLOQUÉ

## Contexte

Tentative d'intégration de la bibliothèque micro-ecc dans ArduPilot pour Feature 2 (génération de keypairs P-256 en software).

## Actions Effectuées

1. ✅ Clone micro-ecc depuis GitHub (https://github.com/kmackay/micro-ecc)
2. ✅ Création `libraries/micro-ecc/wscript` pour build ArduPilot
3. ✅ Création `uECC_config.h` pour définir macros et éviter `-Werror=undef`
4. ✅ Modification `uECC.c` pour inclure `uECC_config.h`
5. ❌ **Compilation échoue** avec erreurs assembleur ARM

## Problème Détaillé

### Erreur de Compilation

```
../../libraries/micro-ecc/asm_arm.inc:492: Error: invalid instruction suffix for `adc'
../../libraries/micro-ecc/asm_arm.inc:493: Error: expecting operand after ','; got nothing
../../libraries/micro-ecc/asm_arm.inc:494: Error: expecting operand after ','; got nothing
[...]
Build failed
```

### Cause Racine

Même avec `uECC_OPTIMIZATION_LEVEL=0` dans uECC_config.h, le fichier `asm_arm.inc` (assembleur ARM) est inclus et tente de compiler sur x86_64 (SITL).

**Hypothèse**: Le système de build ArduPilot définit des macros ARM même pour SITL, ou la détection de plateforme de micro-ecc est confuse.

### Tentatives de Résolution

| Tentative | Résultat |
|-----------|----------|
| `-Wno-undef` dans cflags | ❌ Pas pris en compte (ordre flags) |
| `defines=[...]` dans wscript | ❌ Redef warnings, puis erreurs asm |
| `uECC_config.h` avec toutes macros | ❌ asm_arm.inc toujours inclus |
| `uECC_OPTIMIZATION_LEVEL=0` | ❌ Inclusions ARM persistent |
| `__ARM_ARCH=0` | ❌ Erreurs asm persistent |

## Solutions Possibles

### Option 1: Forcer Platform x86_64 ⭐ À TESTER

**Action**: Ajouter dans `uECC_config.h`:

```c
// Force x86_64 platform, disable ARM
#define uECC_ARM 0
#define uECC_X86_64 1
#define uECC_ASM uECC_asm_none

#undef __arm__
#undef __ARM__
#undef __ARM_ARCH
```

**Avantage**: Simple, utilise micro-ecc tel quel
**Inconvénient**: Peut ne pas suffire si détection faite avant

### Option 2: Utiliser mbedTLS ⭐⭐ RECOMMANDÉ

**Action**: Vérifier si mbedTLS est disponible dans ArduPilot et l'utiliser

**Commande**:
```bash
find . -name "*mbedtls*" -o -name "*mbed*"
```

**Avantages**:
- Déjà intégré potentiellement
- Support P-256 complet
- Bien testé

**Inconvénient**: Plus lourd (~50KB vs 3KB)

### Option 3: Implémentation P-256 Minimale Custom

**Action**: Implémenter seulement les primitives nécessaires:
- Génération keypair (via /dev/urandom + validation point)
- Multiplication scalaire (pour ECDH)

**Avantages**:
- Contrôle total
- Optimisé pour notre cas

**Inconvénients**:
- Risque d'erreurs crypto
- Temps de développement
- Maintenance

### Option 4: Génération Offline + Injection

**Action**: Générer keypairs en dehors d'ArduPilot, injecter dans HSM

**Script Python**:
```python
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# Générer keypair P-256
private_key = ec.generate_private_key(ec.SECP256R1())
# Extraire bytes et écrire dans HSM via APDU
```

**Avantages**:
- Contourne le problème compilation
- Utilise crypto Python robuste

**Inconvénients**:
- Pas de génération automatique au boot
- Nécessite étape manuelle

### Option 5: Compiler micro-ecc Séparément

**Action**: Compiler micro-ecc en bibliothèque statique séparée, linker avec ArduPilot

**Avantages**:
- Flags de compilation contrôlés
- Isolation du code problématique

**Inconvénients**:
- Complexité build
- Portabilité réduite

## Recommandation

**Option 2 (mbedTLS)** si disponible, sinon **Option 4 (génération offline)** pour Feature 2 en attendant une solution meilleure pour Feature 3+.

## Fichiers Créés

- `libraries/micro-ecc/` (repository cloné)
- `libraries/micro-ecc/wscript`
- `libraries/micro-ecc/uECC_config.h`
- `feature2/travaille-feature2.md`
- `feature2/BLOCAGE-micro-ecc.md` (ce fichier)

## Solution Trouvée ✅

**Date**: 2026-01-22

### Cause Racine Identifiée

Le problème était dans `uECC_config.h` ligne 16:
```c
#define uECC_PLATFORM 5  /* 64-bit generic */
```

**Erreur**: La valeur `5` correspond à `uECC_arm_thumb2` (pas x86_64!)

Selon `uECC.h` lignes 12-16:
- `uECC_x86        1`
- `uECC_x86_64     2`  ← Valeur correcte
- `uECC_arm        3`
- `uECC_arm_thumb  4`
- `uECC_arm_thumb2 5`  ← Valeur erronée utilisée

### Correction Appliquée

**Fichier**: `libraries/micro-ecc/uECC_config.h`

```c
/* Force x86_64 platform, disable ARM completely */
#undef __arm__
#undef __ARM__
#undef __ARM_ARCH
#undef __ARM_FEATURE_UNALIGNED

#define uECC_ARM 0
#define uECC_ARM_THUMB 0
#define uECC_ARM_THUMB2 0
#define uECC_X86_64 1
#define uECC_ASM uECC_asm_none

/* Platform configuration */
#define uECC_PLATFORM 2  /* uECC_x86_64 */
#define uECC_SUPPORTS_secp256r1 1
#define uECC_OPTIMIZATION_LEVEL 0
```

### Résultat

✅ **Compilation réussie** en 1.177s:
```bash
./waf --targets=objs/micro-ecc
[13/13] Compiling libraries/micro-ecc/uECC.c
'build' finished successfully (1.177s)
```

## Prochaines Actions

1. ✅ Blocage résolu - micro-ecc compilé avec succès
2. Implémenter génération keypair P-256 dans AP_HSM
3. Implémenter stockage/récupération clé dans HSM
4. Tester Feature 2 complète avec HSM réel

---

**Auteur**: Claude Sonnet 4.5
**Statut**: ✅ RÉSOLU - Feature 2 peut continuer
