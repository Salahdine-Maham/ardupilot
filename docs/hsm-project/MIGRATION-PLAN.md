# Plan de Migration: Ancienne Architecture → Nouvelle Architecture Dual-DEK

**Date**: 2026-01-24
**Version**: 2.0

---

## 📊 Comparaison Ancienne vs Nouvelle Architecture

### Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│              ANCIENNE ARCHITECTURE (PRD v1)                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Feature 1 → Feature 2 → Feature 3 → Feature 4 → ... → Feature 9   │
│                                                                     │
│  • Keypair générée aléatoirement                                   │
│  • DEK partagée entre tous                                          │
│  • Échange simple de clés publiques                                │
│  • Pas de hiérarchie de clés                                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ MIGRATION
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              NOUVELLE ARCHITECTURE (Dual-DEK)                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Feature 1 → Feature 2.1 → Feature 2.2 → Feature 2.3 → Feature 3   │
│                                                                     │
│  • Hiérarchie 3 niveaux (MK → WK → DEK)                            │
│  • Dual-DEK (chaque drone sa propre DEK)                           │
│  • Échange ECIES bidirectionnel                                     │
│  • Master Key isolée dans HSM                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Mapping Feature par Feature

| Ancienne Feature | Status | Nouvelle Feature | Changements |
|------------------|--------|------------------|-------------|
| **Feature 1** | ✅ **GARDER** | Feature 1 | Aucun changement |
| **Feature 2** | ❌ REMPLACER | Feature 2.1 | MK + dérivation WK au lieu de keypair aléatoire |
| **Feature 3** | ❌ REMPLACER | Feature 2.2 | ECIES exchange au lieu de simple échange public key |
| **Feature 4** | ❌ REMPLACER | Feature 2.1 + 2.2 | DEK unique par drone, échange bidirectionnel |
| **Feature 5** | ❌ MODIFIER | Feature 2.3 | Dual-DEK, HEARTBEAT non chiffré |
| **Feature 6** | ❌ MODIFIER | Feature 2.3 | Nouveau format message |
| **Feature 7** | ❌ MODIFIER | Feature 2.3 | Réception avec DEK du peer |
| **Feature 8** | ❌ INTÉGRER | 2.1 + 2.2 + 2.3 | Rotation déclenche re-exchange |
| **Feature 9** | ✅ **GARDER** | Feature 3 | Tests de performance |

---

## 🔍 Analyse Détaillée par Feature

### Feature 1: Initialisation HSM ✅ INCHANGÉE

```
Ancienne:                         Nouvelle:
═════════                         ═════════
OFF → ON → SELECT → PIN           OFF → ON → SELECT → PIN
          │                                 │
          ▼                                 ▼
    IDENTIQUE                         IDENTIQUE

Status: ✅ AUCUN CHANGEMENT REQUIS
Le code actuel fonctionne parfaitement.
```

**Code à garder:**
- `AP_HSM::init_monolith()` - Fonctionne
- Séquence OFF → ON → SELECT CC → VERIFY PIN - Fonctionne

---

### Feature 2 (Ancienne) → Feature 2.1 (Nouvelle) ❌ REMPLACER

```
ANCIENNE FEATURE 2:                NOUVELLE FEATURE 2.1:
═══════════════════                ═════════════════════

Keypair aléatoire                  Master Key (MK)
      │                                  │
      ▼                                  │ Stockée HSM
Store privée @ 0x0100                    │ (premier boot)
      │                                  │
      ▼                                  ▼
Cache RAM                          HKDF(MK, salt)
                                         │
                                         ▼
                                   Wrapper Key (WK)
                                   Privée HSM + Publique cache
                                         │
                                         ▼
                                   Generate DEK (RNG)
                                   Cache RAM
```

**Ce qui change:**

| Aspect | Ancien | Nouveau |
|--------|--------|---------|
| Source clé | RNG aléatoire | Dérivée de MK via HKDF |
| Stockage privée | HSM @ 0x0100 | HSM (MK) + dérivation |
| Type clé | 1 niveau (keypair) | 3 niveaux (MK→WK→DEK) |
| Unicité | Par boot | MK permanente, WK par mission |

**Code à SUPPRIMER:**
- `generate_keypair_p256()` - Plus utilisé
- `store_private_key_to_hsm()` - Plus utilisé comme ça
- `load_private_key_from_hsm()` - Plus utilisé comme ça

**Code à CRÉER:**
- `KeyOrchestrator::generate_master_key()` - Génère MK dans HSM
- `KeyOrchestrator::derive_wrapper_key()` - HKDF(MK) → WK
- `KeyOrchestrator::generate_session_dek()` - RNG → DEK

---

### Feature 3 (Ancienne) → Feature 2.2 (Nouvelle) ❌ REMPLACER

```
ANCIENNE FEATURE 3:                NOUVELLE FEATURE 2.2:
═══════════════════                ═════════════════════

Simple échange:                    Protocole complet:

A ──[PubKey_A]──→ B               Phase 1: Handshake
A ←──[PubKey_B]── B                 A ──[WK_A_PUB + sig]──→ B
                                    A ←──[WK_B_PUB + sig]── B
Stockage table
                                   Phase 2: DEK Exchange (ECIES)
                                    A ──[ECIES(DEK_A)]──→ B
                                    A ←──[ECIES(DEK_B)]── B

                                   Phase 3: Confirmation ACK
                                    A ──[ACK(hash DEK_B)]──→ B
                                    A ←──[ACK(hash DEK_A)]── B
```

**Ce qui change:**

| Aspect | Ancien | Nouveau |
|--------|--------|---------|
| Messages | 2 (pub key exchange) | 6 (3 phases × 2 sens) |
| Sécurité | Aucune signature | ECDSA signatures |
| Contenu | Clé publique seule | WK_PUB + DEK chiffrée |
| Protocole | Ad-hoc | ECIES standardisé |

**Code à SUPPRIMER:**
- Ancien `PUBLIC_KEY_EXCHANGE` message

**Code à CRÉER:**
- `KeyExchangeProtocol` classe complète
- Messages MAVLink: `CRYPTO_KEY_HANDSHAKE`, `CRYPTO_DEK_EXCHANGE`, `CRYPTO_DEK_ACK`
- ECIES encrypt/decrypt

---

### Feature 4 (Ancienne) → Intégrée dans 2.1 + 2.2 ❌ REMPLACER

```
ANCIENNE FEATURE 4:                NOUVELLE (dans 2.1 + 2.2):
═══════════════════                ══════════════════════════

DEK partagée:                      DEK unique par drone:

generate_dek()                     Dans 2.1: generate_session_dek()
      │                                  │
      ▼                                  ▼
encrypt_dek(peer_pubkey)           Dans 2.2: ECIES_encrypt(MY_DEK)
      │                                  │
      ▼                                  ▼
Envoyer à peer                     Échange bidirectionnel
                                   (chacun envoie SA DEK)
```

**Ce qui change:**

| Aspect | Ancien | Nouveau |
|--------|--------|---------|
| Modèle DEK | 1 DEK partagée | Dual-DEK (chacun la sienne) |
| Direction | Unidirectionnel | Bidirectionnel |
| Qui génère | Un seul drone | Chaque drone |

**Code à SUPPRIMER:**
- `encrypt_dek()` - Logique différente maintenant

**Code à CRÉER:**
- Intégré dans `KeyOrchestrator` et `KeyExchangeProtocol`

---

### Feature 5, 6, 7 (Anciennes) → Feature 2.3 (Nouvelle) ❌ MODIFIER

```
ANCIENNES FEATURES 5-6-7:          NOUVELLE FEATURE 2.3:
═════════════════════════          ══════════════════════

Une seule DEK partagée:            Dual-DEK:

Envoi:                             Envoi:
  ChaCha20(msg, SHARED_DEK)          ChaCha20(msg, MY_DEK)

Réception:                         Réception:
  ChaCha20_decrypt(SHARED_DEK)       ChaCha20_decrypt(PEER_DEK)

Tous messages chiffrés             HEARTBEAT non chiffré
                                   (pour découverte peers)
```

**Ce qui change:**

| Aspect | Ancien | Nouveau |
|--------|--------|---------|
| Clé envoi | DEK partagée | MA DEK |
| Clé réception | DEK partagée | DEK DU PEER |
| HEARTBEAT | Chiffré | Non chiffré |
| Traçabilité | Limitée | Complète (DEK = identité) |

**Code à MODIFIER:**
- `comm_send_buffer()` - Utiliser MY_DEK pour envoyer
- `handle_message()` - Identifier sender, utiliser PEER_DEK

**Code à CRÉER:**
- `DualDekEngine` classe complète
- Gestion table `peer_deks[]`
- Anti-replay par peer

---

### Feature 8 (Ancienne) → Intégrée dans 2.1 + 2.2 + 2.3 ❌ INTÉGRER

```
ANCIENNE FEATURE 8:                NOUVELLE (distribuée):
═══════════════════                ═══════════════════════

Timer → nouvelle DEK               Dans 2.3:
      │                              check_rotation_needed()
      ▼                                    │
Ré-échange unique                          ▼
                                   Dans 2.1:
                                     generate_new_dek()
                                           │
                                           ▼
                                   Dans 2.2:
                                     re-exchange avec tous peers
```

**Ce qui change:**

| Aspect | Ancien | Nouveau |
|--------|--------|---------|
| Localisation | Feature séparée | Distribuée dans 2.1/2.2/2.3 |
| Trigger | Timer seul | Timer OU 10k messages |
| Scope | Global | Par peer |

---

### Feature 9 (Ancienne) → Feature 3 (Nouvelle) ✅ GARDER

```
Status: ✅ CONCEPT INCHANGÉ

Tests de performance et robustesse:
- Benchmark CPU/mémoire
- Test fallback
- Mesure overhead
```

---

## 📋 Nouveau Plan de Features

### Structure Finale

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NOUVEAU PLAN DE FEATURES                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Feature 1: HSM Init (INCHANGÉ) ✅                                  │
│  ├── OFF → ON → SELECT CC → VERIFY PIN                             │
│  └── Status: TERMINÉ ET FONCTIONNEL                                │
│                                                                     │
│  Feature 2.1: Key Orchestrator (NOUVEAU)                           │
│  ├── Génération Master Key (premier boot)                          │
│  ├── Dérivation Wrapper Key (HKDF)                                 │
│  ├── Génération DEK session                                        │
│  └── Cache sécurisé RAM                                            │
│                                                                     │
│  Feature 2.2: Key Exchange Protocol (NOUVEAU)                      │
│  ├── Découverte peers via HEARTBEAT                                │
│  ├── Phase 1: Handshake (WK_PUB + signature)                       │
│  ├── Phase 2: DEK Exchange (ECIES)                                 │
│  ├── Phase 3: Confirmation ACK                                     │
│  └── Messages MAVLink custom                                       │
│                                                                     │
│  Feature 2.3: Dual-DEK Communication Engine (NOUVEAU)              │
│  ├── Envoi avec MA DEK                                             │
│  ├── Réception avec DEK du peer                                    │
│  ├── Protection anti-replay                                        │
│  ├── Gestion sessions multi-peers                                  │
│  └── Détection rotation nécessaire                                 │
│                                                                     │
│  Feature 3: Tests et Validation (ADAPTÉ)                           │
│  ├── Tests performance                                             │
│  ├── Tests robustesse                                              │
│  └── Benchmarks                                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🗑️ Code à Supprimer/Remplacer

### Fichiers/Fonctions à Supprimer

```cpp
// Dans AP_HSM.cpp - À SUPPRIMER ou REMPLACER:

// ❌ Ancien Feature 2
bool generate_keypair_p256();           // → Remplacé par Key Orchestrator
bool store_private_key_to_hsm();        // → Nouvelle logique MK
bool load_private_key_from_hsm();       // → Nouvelle logique MK

// ❌ Ancien Feature 3
bool compute_ecdh();                    // → Remplacé par ECIES dans Key Exchange
bool derive_wrapping_key();             // → Dans Key Orchestrator (HKDF pour WK)
bool wrap_dek();                        // → Remplacé par ECIES
bool unwrap_dek();                      // → Remplacé par ECIES
bool store_dek_to_hsm();               // → Plus de stockage DEK (RAM only)
bool load_dek_from_hsm();              // → Plus de stockage DEK (RAM only)

// ❌ Ancien Feature 4 (dans GCS_MAVLink.cpp)
// Le chiffrement actuel utilise une DEK unique
// → Remplacer par logique Dual-DEK
```

### Variables/Caches à Modifier

```cpp
// ANCIEN:
uint8_t private_key_cache[32];    // Clé privée keypair
uint8_t public_key_cache[64];     // Clé publique keypair
uint8_t dek_cache[32];            // DEK unique partagée

// NOUVEAU:
// Dans KeyOrchestrator:
uint8_t wk_private[32];           // Wrapper Key privée (dérivée de MK)
uint8_t wk_public[64];            // Wrapper Key publique
uint8_t my_dek[32];               // MA DEK (pour envoyer)

// Dans DualDekEngine:
struct PeerSession {
    char peer_id[32];
    uint8_t peer_dek[32];         // DEK du peer (pour recevoir)
    // ... autres champs
};
PeerSession sessions[MAX_PEERS];
```

---

## 📅 Ordre d'Implémentation Recommandé

```
1. Feature 1: ✅ DÉJÀ TERMINÉ - Ne pas toucher

2. Feature 2.1: Key Orchestrator
   ├── Créer KeyOrchestrator.h/.cpp
   ├── Implémenter génération MK (HSM)
   ├── Implémenter dérivation WK (HKDF)
   ├── Implémenter génération DEK
   └── Tester isolation MK

3. Feature 2.2: Key Exchange Protocol
   ├── Définir messages MAVLink custom
   ├── Créer KeyExchangeProtocol.h/.cpp
   ├── Implémenter handshake (Phase 1)
   ├── Implémenter ECIES exchange (Phase 2)
   ├── Implémenter ACK (Phase 3)
   └── Tester avec 2 SITL

4. Feature 2.3: Dual-DEK Communication Engine
   ├── Créer DualDekEngine.h/.cpp
   ├── Implémenter send_to_peer (MY_DEK)
   ├── Implémenter receive_from_peer (PEER_DEK)
   ├── Implémenter anti-replay
   ├── Modifier comm_send_buffer()
   └── Tester communication chiffrée

5. Feature 3: Tests et Validation
   ├── Benchmark performance
   ├── Test rotation DEK
   ├── Test multi-peers
   └── Documentation finale
```

---

## ⚠️ Points d'Attention

1. **Ne pas casser Feature 1**: Le code HSM init fonctionne, ne pas y toucher

2. **Migration progressive**: Désactiver ancien code avant d'activer nouveau

3. **HEARTBEAT**: Doit rester non chiffré pour découverte peers

4. **Backward compatibility**: Prévoir flag pour ancien/nouveau mode

5. **Tests à chaque étape**: Valider avant de passer à la suivante

---

**Dernière mise à jour**: 2026-01-24
