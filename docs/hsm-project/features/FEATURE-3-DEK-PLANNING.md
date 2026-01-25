# Feature 3: Génération DEK ChaCha20-256 et KDF Sécurisé

**Date de début**: 2026-01-23
**Statut**: 🚧 EN COURS

---

## 📋 Objectif de la Feature

Implémenter un système complet de gestion de clés de chiffrement (Data Encryption Key - DEK) avec dérivation sécurisée via ECDH et KDF. La DEK ChaCha20-256 sera générée à chaque session, dérivée depuis un échange ECDH avec une clé distante, et stockée de manière chiffrée dans le HSM.

## 🎯 Critères de Succès

- [ ] Génération DEK ChaCha20-256 (32 bytes) via RNG sécurisé
- [ ] Implémentation ECDH avec keypair locale (Feature 2) et clé publique distante
- [ ] Implémentation KDF (HKDF-SHA256) pour dériver clé de chiffrement
- [ ] Stockage DEK chiffré dans HSM (WRITE BINARY)
- [ ] Récupération et déchiffrement DEK depuis HSM
- [ ] Cache RAM volatile de la DEK (effacé au reboot)
- [ ] Tests avec HSM réel LeMonolith

---

## 🏗️ Architecture

### Composants principaux

1. **DEK (Data Encryption Key)**
   - Clé symétrique ChaCha20-256 (32 bytes)
   - Générée à chaque session (non persistante brute)
   - Utilisée pour chiffrer les données MAVLink

2. **ECDH (Elliptic Curve Diffie-Hellman)**
   - Utilise keypair P-256 de Feature 2 (clé privée locale)
   - Reçoit clé publique distante (GCS ou autre drone)
   - Calcule secret partagé (32 bytes)

3. **KDF (Key Derivation Function)**
   - HKDF-SHA256 (HMAC-based Key Derivation Function)
   - Entrée: secret ECDH + salt + info
   - Sortie: clé de chiffrement pour wrap/unwrap DEK

4. **Stockage HSM**
   - DEK chiffrée (wrappée) stockée dans HSM
   - Offset: 0x0120 (après keypair P-256 à 0x0100)
   - Format: DEK chiffrée (32 bytes) + IV/nonce si nécessaire

### Flux de données

```
Boot ArduPilot:
1. Feature 1: Init HSM
2. Feature 2: Load keypair P-256 → private_key_cache
3. Feature 3:
   a. Générer DEK aléatoire (32 bytes)
   b. Recevoir public_key_remote via MAVLink
   c. ECDH(private_key_cache, public_key_remote) → shared_secret
   d. KDF(shared_secret, salt, info) → wrapping_key
   e. Chiffrer DEK avec wrapping_key → wrapped_DEK
   f. WRITE BINARY wrapped_DEK dans HSM (offset 0x0120)
   g. Stocker DEK en clair dans cache RAM volatile

Session normale:
- Utiliser DEK pour chiffrer/déchiffrer données MAVLink
- DEK reste en cache RAM (pas de lecture HSM à chaque utilisation)

Reboot:
- Feature 3 recharge DEK depuis HSM:
  a. READ BINARY wrapped_DEK depuis HSM (offset 0x0120)
  b. Refaire ECDH + KDF pour obtenir wrapping_key
  c. Déchiffrer wrapped_DEK → DEK
  d. Stocker DEK dans cache RAM
```

---

## 📚 Bibliothèques Nécessaires

### 1. ChaCha20 (pour wrap/unwrap DEK)

**Options**:
- **Option A**: Implémenter ChaCha20-Poly1305 manuellement (complexe)
- **Option B**: Utiliser TinyCrypt (utilisé par ArduPilot pour certains boards)
- **Option C**: Utiliser AES-256-GCM à la place (plus simple, largement supporté)

**Recommandation**: AES-256-GCM pour wrap/unwrap, ChaCha20-Poly1305 pour données MAVLink (Feature 4)

### 2. SHA-256 (pour HKDF)

**ArduPilot inclut déjà**:
- `libraries/AP_HAL/utility/hash.h` - Interface hash
- `libraries/AP_HAL_Linux/Util.cpp` - Implémentation SHA256 pour SITL

**Alternative**: mbedTLS (déjà utilisé par ArduPilot sur certains boards)

### 3. ECDH (Elliptic Curve Diffie-Hellman)

**micro-ecc inclut**:
- `uECC_shared_secret()` - Calcule secret ECDH depuis private_key + public_key_remote
- Déjà intégré dans Feature 2 ✅

---

## 📂 Modifications Prévues

### Fichiers à modifier

1. **libraries/AP_HSM/AP_HSM.h**
   - Ajouter cache DEK (32 bytes)
   - Ajouter wrapping_key (32 bytes)
   - Fonctions: `generate_dek()`, `wrap_dek()`, `unwrap_dek()`, `compute_ecdh()`, `derive_wrapping_key()`

2. **libraries/AP_HSM/AP_HSM.cpp**
   - Implémenter génération DEK via RNG
   - Implémenter ECDH avec micro-ecc
   - Implémenter HKDF-SHA256
   - Implémenter wrap/unwrap DEK (AES-256-GCM)
   - Implémenter READ/WRITE DEK depuis/vers HSM

3. **libraries/AP_Vehicle/AP_Vehicle.cpp**
   - Intégrer Feature 3 dans `setup()` après Feature 2
   - Logique: générer ou charger DEK

4. **Nouvelle bibliothèque**: `libraries/AP_Crypto/` (optionnel)
   - Centraliser fonctions crypto (HKDF, AES-GCM)
   - Utilisable par autres modules ArduPilot

---

## 🔧 Plan d'Implémentation

### Phase 1: Préparation crypto (HKDF + AES-GCM)

- [ ] **Tâche 1.1**: Investiguer bibliothèques crypto disponibles dans ArduPilot
  - Vérifier mbedTLS, TinyCrypt, ou autre
  - Identifier fonctions SHA-256, HMAC, AES-GCM

- [ ] **Tâche 1.2**: Implémenter ou wrapper HKDF-SHA256
  - Créer fonction `hkdf_sha256(ikm, salt, info, okm, okm_len)`
  - Tester avec vecteurs de test RFC 5869

- [ ] **Tâche 1.3**: Implémenter wrap/unwrap DEK avec AES-256-GCM
  - Fonction `aes_gcm_wrap(dek, wrapping_key, wrapped_dek, tag)`
  - Fonction `aes_gcm_unwrap(wrapped_dek, tag, wrapping_key, dek)`
  - Tester avec vecteurs de test NIST

### Phase 2: Génération et gestion DEK

- [ ] **Tâche 2.1**: Implémenter `generate_dek()` dans AP_HSM
  - Utiliser `hal.util->get_random_vals()` (32 bytes)
  - Stocker dans `dek_cache[32]`

- [ ] **Tâche 2.2**: Implémenter `compute_ecdh(public_key_remote)` dans AP_HSM
  - Utiliser `uECC_shared_secret()` de micro-ecc
  - Entrée: `private_key_cache` (Feature 2) + `public_key_remote`
  - Sortie: `shared_secret[32]`

- [ ] **Tâche 2.3**: Implémenter `derive_wrapping_key(shared_secret)` dans AP_HSM
  - Appeler HKDF-SHA256 avec salt et info appropriés
  - Stocker dans `wrapping_key_cache[32]`

### Phase 3: Stockage et récupération HSM

- [ ] **Tâche 3.1**: Implémenter `store_dek_to_hsm(wrapped_dek)`
  - APDU WRITE BINARY à l'offset 0x0120 (32 bytes wrapped_DEK + 16 bytes tag GCM)
  - Total: 48 bytes

- [ ] **Tâche 3.2**: Implémenter `load_dek_from_hsm()`
  - APDU READ BINARY depuis offset 0x0120 (48 bytes)
  - Parser wrapped_DEK + tag
  - Unwrap avec wrapping_key → DEK en clair

### Phase 4: Intégration AP_Vehicle

- [ ] **Tâche 4.1**: Ajouter logique Feature 3 dans `AP_Vehicle::setup()`
  - Après Feature 2 (keypair chargée)
  - Logique: essayer load_dek → sinon generate_dek
  - Nécessite clé publique distante (simulée ou via MAVLink)

- [ ] **Tâche 4.2**: Créer fonction test pour ECDH
  - Générer keypair test distante
  - Tester échange ECDH
  - Vérifier que les deux côtés obtiennent même secret

### Phase 5: Tests

- [ ] **Test 1**: Génération DEK et wrap/unwrap local (sans HSM)
- [ ] **Test 2**: ECDH avec keypairs test
- [ ] **Test 3**: Stockage/récupération DEK depuis HSM réel
- [ ] **Test 4**: Cycle complet: boot → generate → store → reboot → load
- [ ] **Test 5**: Performance (latence ECDH, KDF, wrap/unwrap)

---

## 🔍 Questions Ouvertes

### Q1: Quelle bibliothèque crypto utiliser ?

**Options**:
1. **mbedTLS**: Complet, largement utilisé, mais lourd
2. **TinyCrypt**: Léger, optimisé pour embedded, mais fonctionnalités limitées
3. **Implémentation manuelle**: Contrôle total, mais risque de bugs crypto

**Décision**: À investiguer dans Phase 1

### Q2: Clé publique distante - d'où vient-elle ?

**Options**:
1. **Hardcodée pour tests**: Simplest pour développement
2. **Via MAVLink custom message**: Requiert modification protocole
3. **Via fichier config**: Chargée au boot depuis SD card
4. **Via QGroundControl**: Interface utilisateur pour configurer

**Décision temporaire**: Hardcodée pour tests, MAVLink pour production

### Q3: Fréquence de renouvellement DEK ?

**Options**:
1. **À chaque boot**: DEK persistante dans HSM, rechargée
2. **À chaque session**: DEK nouvelle, ancienne écrasée
3. **Sur demande**: Commande MAVLink pour renouveler

**Recommandation**: À chaque boot pour simplicité (Feature 3), sur demande (Feature 4+)

### Q4: Que faire si unwrap échoue au boot ?

**Options**:
1. **Générer nouvelle DEK**: Perte de capacité à déchiffrer anciennes données
2. **Fail safe mode**: Continuer sans chiffrement, logger erreur
3. **Retry avec fallback**: Essayer plusieurs méthodes

**Recommandation**: Générer nouvelle DEK + logger warning

---

## 📊 Estimation Complexité

**Complexité globale**: Haute (crypto + intégration)

**Temps estimé**:
- Phase 1 (crypto): 3-4h (investigation + implémentation HKDF + AES-GCM)
- Phase 2 (DEK management): 2h
- Phase 3 (HSM storage): 1h (similaire à Feature 2)
- Phase 4 (intégration): 1h
- Phase 5 (tests): 2h

**Total**: 9-10h de développement + debugging

**Dépendances**:
- ✅ Feature 1 complète (HSM init)
- ✅ Feature 2 complète (keypair P-256)
- ⚠️ Bibliothèque crypto (à déterminer)

---

## 🎯 Prochaines Étapes Immédiates

1. **Investigation bibliothèques crypto** (Tâche 1.1)
   - Chercher mbedTLS dans ArduPilot
   - Chercher TinyCrypt
   - Vérifier fonctions SHA-256/HMAC disponibles

2. **Créer structure AP_Crypto** (si nécessaire)
   - Dossier `libraries/AP_Crypto/`
   - Wrappers pour HKDF, AES-GCM

3. **Commencer Phase 1** (HKDF + AES-GCM)

---

**Dernière mise à jour**: 2026-01-23
**Auteur**: Claude Sonnet 4.5
**Statut**: 🚧 Planification initiale complète - Investigation crypto à démarrer
