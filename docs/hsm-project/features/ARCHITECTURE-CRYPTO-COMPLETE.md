# Architecture Cryptographique Complète
## Réseau de Drones Sécurisé - Vue d'Ensemble

**Date**: 2026-01-24
**Version**: 2.0 (Nouvelle architecture Dual-DEK)

---

## 📋 Résumé Exécutif

Architecture de chiffrement à **3 niveaux** pour communication sécurisée drone-drone avec modèle **Dual-DEK** où chaque drone utilise sa propre DEK pour envoyer.

---

## 🏗️ Hiérarchie des Clés

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HIÉRARCHIE 3 NIVEAUX                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ╔═══════════════════════════════════════════════════════════════╗ │
│  ║ NIVEAU 1: MASTER KEY (MK)                                     ║ │
│  ╠═══════════════════════════════════════════════════════════════╣ │
│  ║ • Type: Symétrique (ChaCha20-256)                             ║ │
│  ║ • Génération: Premier boot du drone                           ║ │
│  ║ • Stockage: HSM EXCLUSIVEMENT (jamais en RAM claire)          ║ │
│  ║ • Durée de vie: Permanente (vie du drone)                     ║ │
│  ║ • Export: INTERDIT                                            ║ │
│  ╚═══════════════════════════════════════════════════════════════╝ │
│                              │                                      │
│                              │ HKDF-SHA256                          │
│                              │ salt = drone_id + mission_id +       │
│                              │        timestamp                     │
│                              ▼                                      │
│  ╔═══════════════════════════════════════════════════════════════╗ │
│  ║ NIVEAU 2: WRAPPER KEY (WK)                                    ║ │
│  ╠═══════════════════════════════════════════════════════════════╣ │
│  ║ • Type: Asymétrique (secp256r1 / P-256)                       ║ │
│  ║ • Génération: Dérivée de MK via HKDF                          ║ │
│  ║ • WK_PRIVATE: Stockée HSM                                     ║ │
│  ║ • WK_PUBLIC: Partagée via MAVLink (handshake)                 ║ │
│  ║ • Durée de vie: Par mission                                   ║ │
│  ║ • Usage: Chiffrement ECIES des DEK lors de l'échange          ║ │
│  ╚═══════════════════════════════════════════════════════════════╝ │
│                              │                                      │
│                              │ Génération aléatoire (RNG)           │
│                              │ + Échange via ECIES                  │
│                              ▼                                      │
│  ╔═══════════════════════════════════════════════════════════════╗ │
│  ║ NIVEAU 3: DATA ENCRYPTION KEY (DEK)                           ║ │
│  ╠═══════════════════════════════════════════════════════════════╣ │
│  ║ • Type: Symétrique (ChaCha20-256)                             ║ │
│  ║ • Génération: RNG crypto, UNIQUE par drone                    ║ │
│  ║ • Stockage: RAM volatile (cache sécurisé)                     ║ │
│  ║ • Durée de vie: Par session (1h ou 10k messages)              ║ │
│  ║ • Modèle: DUAL-DEK (chacun sa DEK)                            ║ │
│  ╚═══════════════════════════════════════════════════════════════╝ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Modèle Dual-DEK Expliqué

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DUAL-DEK MODEL                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Principe fondamental:                                              │
│  ═════════════════════                                              │
│  • Chaque drone génère SA PROPRE DEK unique                        │
│  • J'ENVOIE avec MA DEK                                            │
│  • JE REÇOIS avec la DEK DU PEER                                   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                                                             │   │
│  │   DRONE_A                           DRONE_B                 │   │
│  │   ════════                          ════════                │   │
│  │                                                             │   │
│  │   Possède:                          Possède:                │   │
│  │   • DEK_A (sa DEK)                  • DEK_B (sa DEK)       │   │
│  │   • DEK_B (reçue de B)              • DEK_A (reçue de A)   │   │
│  │                                                             │   │
│  │   ══════════════════════════════════════════════════════   │   │
│  │                                                             │   │
│  │   A envoie à B:                                             │   │
│  │   [Plaintext] ──ChaCha20(DEK_A)──→ [Ciphertext] ──→ B      │   │
│  │                                      B déchiffre avec DEK_A │   │
│  │                                                             │   │
│  │   B envoie à A:                                             │   │
│  │   [Plaintext] ──ChaCha20(DEK_B)──→ [Ciphertext] ──→ A      │   │
│  │                                      A déchiffre avec DEK_B │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Avantages:                                                         │
│  ══════════                                                         │
│  ✓ Traçabilité: La DEK utilisée identifie l'émetteur              │
│  ✓ Isolation: Compromission d'un drone n'affecte pas les autres   │
│  ✓ Indépendance: Chaque drone contrôle son chiffrement            │
│  ✓ Évolutivité: Réseau maillé N drones sans point central         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔗 Workflow Complet

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WORKFLOW DE A À Z                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ══════════════════════════════════════════════════════════════    │
│  PHASE 0: PREMIER BOOT (Feature 2.1)                               │
│  ══════════════════════════════════════════════════════════════    │
│                                                                     │
│  1. Drone démarre pour la première fois                            │
│  2. HSM génère Master Key (MK) - stockée définitivement            │
│  3. MK ──HKDF(salt)──→ WK_PRIVATE                                  │
│  4. WK_PRIVATE ──uECC──→ WK_PUBLIC                                 │
│  5. RNG ──────────────→ DEK (ma propre DEK)                        │
│  6. Cache RAM: WK + DEK prêts                                      │
│                                                                     │
│  ══════════════════════════════════════════════════════════════    │
│  PHASE 1: DÉCOUVERTE DE PEER (via Heartbeat)                       │
│  ══════════════════════════════════════════════════════════════    │
│                                                                     │
│  1. Drone A reçoit HEARTBEAT de Drone B (non chiffré)              │
│  2. A vérifie: "B est-il dans ma liste de peers connus?"           │
│  3. Si NON → Initier Key Exchange avec B                           │
│                                                                     │
│  Note: HEARTBEAT reste en clair pour permettre la découverte       │
│                                                                     │
│  ══════════════════════════════════════════════════════════════    │
│  PHASE 2: KEY EXCHANGE (Feature 2.2)                               │
│  ══════════════════════════════════════════════════════════════    │
│                                                                     │
│  Via messages MAVLink custom sur le canal opérationnel:            │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Step 1: Handshake (échange WK_PUB)                           │  │
│  │                                                              │  │
│  │   A ────[WK_A_PUB + ECDSA_sig]────→ B                       │  │
│  │   A ←───[WK_B_PUB + ECDSA_sig]──── B                        │  │
│  │                                                              │  │
│  │   Vérification mutuelle des signatures                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                         │                                          │
│                         ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Step 2: DEK Exchange (ECIES)                                 │  │
│  │                                                              │  │
│  │   A: ECIES_encrypt(DEK_A, WK_B_PUB) → E_DEK_A               │  │
│  │   A ────[E_DEK_A]────→ B                                    │  │
│  │   B: ECIES_decrypt(E_DEK_A, WK_B_PRIV) → DEK_A              │  │
│  │                                                              │  │
│  │   B: ECIES_encrypt(DEK_B, WK_A_PUB) → E_DEK_B               │  │
│  │   B ────[E_DEK_B]────→ A                                    │  │
│  │   A: ECIES_decrypt(E_DEK_B, WK_A_PRIV) → DEK_B              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                         │                                          │
│                         ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Step 3: Confirmation ACK                                     │  │
│  │                                                              │  │
│  │   A ────[ACK + hash(DEK_B)]────→ B   (prouve réception)     │  │
│  │   A ←───[ACK + hash(DEK_A)]──── B   (prouve réception)      │  │
│  │                                                              │  │
│  │   Session établie!                                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ══════════════════════════════════════════════════════════════    │
│  PHASE 3: COMMUNICATION SÉCURISÉE (Feature 2.3)                    │
│  ══════════════════════════════════════════════════════════════    │
│                                                                     │
│  Tous les messages (sauf HEARTBEAT) sont chiffrés:                 │
│                                                                     │
│  A → B: ChaCha20-Poly1305(payload, DEK_A, nonce)                   │
│  B → A: ChaCha20-Poly1305(payload, DEK_B, nonce)                   │
│                                                                     │
│  Protection anti-replay: sequence numbers + sliding window         │
│                                                                     │
│  ══════════════════════════════════════════════════════════════    │
│  PHASE 4: ROTATION (périodique)                                    │
│  ══════════════════════════════════════════════════════════════    │
│                                                                     │
│  Après 10,000 messages OU 1 heure:                                 │
│  1. Générer nouvelle DEK                                           │
│  2. Relancer Key Exchange (Phase 2)                                │
│  3. Continuer avec nouvelles DEK                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📡 Messages MAVLink pour Key Exchange

```
┌─────────────────────────────────────────────────────────────────────┐
│                 MESSAGES MAVLINK CUSTOM                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Message ID Range: À définir (ex: 12000-12010)                     │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ CRYPTO_KEY_HANDSHAKE (12001)                               │    │
│  ├────────────────────────────────────────────────────────────┤    │
│  │ Field              Type        Description                 │    │
│  │ ─────────────────────────────────────────────────────────  │    │
│  │ target_system      uint8       Système destinataire        │    │
│  │ target_component   uint8       Composant destinataire      │    │
│  │ wk_public          uint8[64]   Clé publique WK             │    │
│  │ timestamp          uint64      Unix timestamp ms           │    │
│  │ nonce              uint8[16]   Anti-replay                 │    │
│  │ signature          uint8[64]   ECDSA signature             │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ CRYPTO_DEK_EXCHANGE (12002)                                │    │
│  ├────────────────────────────────────────────────────────────┤    │
│  │ Field              Type        Description                 │    │
│  │ ─────────────────────────────────────────────────────────  │    │
│  │ target_system      uint8       Système destinataire        │    │
│  │ target_component   uint8       Composant destinataire      │    │
│  │ session_id         uint8[16]   UUID session                │    │
│  │ ephemeral_pub      uint8[64]   Clé éphémère ECIES          │    │
│  │ encrypted_dek      uint8[32]   DEK chiffrée                │    │
│  │ nonce              uint8[12]   Nonce ChaCha20              │    │
│  │ auth_tag           uint8[16]   Poly1305 tag                │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ CRYPTO_DEK_ACK (12003)                                     │    │
│  ├────────────────────────────────────────────────────────────┤    │
│  │ Field              Type        Description                 │    │
│  │ ─────────────────────────────────────────────────────────  │    │
│  │ target_system      uint8       Système destinataire        │    │
│  │ target_component   uint8       Composant destinataire      │    │
│  │ session_id         uint8[16]   UUID session                │    │
│  │ dek_hash           uint8[16]   SHA256(DEK)[0:16]           │    │
│  │ status             uint8       0=OK, 1=Error               │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🌐 Réseau Maillé Multi-Drones

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RÉSEAU MAILLÉ (5 DRONES)                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                           DRONE_A                                   │
│                          /   |   \                                  │
│                         /    |    \                                 │
│                    DRONE_B   |   DRONE_C                            │
│                        \     |     /                                │
│                         \    |    /                                 │
│                          DRONE_D                                    │
│                              |                                      │
│                          DRONE_E                                    │
│                                                                     │
│  Chaque drone maintient:                                            │
│  ═══════════════════════                                            │
│                                                                     │
│  DRONE_A:                                                           │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ my_dek = DEK_A  (pour envoyer à TOUS)                      │    │
│  │ peer_deks = {                                              │    │
│  │   "DRONE_B": DEK_B,  // pour recevoir de B                 │    │
│  │   "DRONE_C": DEK_C,  // pour recevoir de C                 │    │
│  │   "DRONE_D": DEK_D   // pour recevoir de D                 │    │
│  │ }                                                          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  Quand A envoie un message:                                         │
│  → Chiffre avec DEK_A                                              │
│  → B, C, D peuvent tous déchiffrer (ils ont DEK_A)                 │
│                                                                     │
│  Quand A reçoit un message de B:                                    │
│  → Identifie sender = B                                            │
│  → Déchiffre avec peer_deks["DRONE_B"] = DEK_B                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔐 Récapitulatif Sécurité

| Propriété | Mécanisme | Garanti par |
|-----------|-----------|-------------|
| **Confidentialité** | ChaCha20-Poly1305 | DEK unique par drone |
| **Intégrité** | Poly1305 auth tag | Détection modification |
| **Authenticité** | ECDSA signatures | Vérification identité |
| **PFS** | Clés éphémères ECIES | Pas de compromission historique |
| **Anti-replay** | Sequence + sliding window | Détection messages dupliqués |
| **Isolation MK** | HSM only | MK jamais exposée |
| **Traçabilité** | Dual-DEK | On sait qui a envoyé |

---

## 📂 Features et Fichiers

| Feature | Responsabilité | Fichiers Principaux |
|---------|----------------|---------------------|
| **2.1 Key Orchestrator** | Génération/gestion clés | `KeyOrchestrator.cpp` |
| **2.2 Key Exchange** | Protocole échange DEK | `KeyExchangeProtocol.cpp` |
| **2.3 Dual-DEK Engine** | Communication chiffrée | `DualDekEngine.cpp` |

---

## ⚠️ Points Importants

1. **HEARTBEAT non chiffré**: Permet la découverte de peers
2. **MK génération unique**: Premier boot seulement, jamais régénérée
3. **Salt HKDF**: `drone_id + mission_id + timestamp` pour unicité WK
4. **Messages MAVLink custom**: Sur le même canal que données opérationnelles
5. **Rotation DEK**: Automatique après 1h ou 10k messages

---

**Dernière mise à jour**: 2026-01-24
**Approuvé par**: [En attente validation utilisateur]
