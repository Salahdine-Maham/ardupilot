# PRD v2.0 - Architecture Cryptographique pour Réseau de Drones

**Version**: 2.0
**Date**: 2026-01-24
**Statut**: Approuvé - En attente d'implémentation

---

## Résumé Exécutif

Ce document définit l'architecture cryptographique v2.0 pour la sécurisation des communications MAVLink entre drones (et GCS) utilisant le HSM LeMonolith Dev Kit v0.6.

**Changement majeur**: Cette architecture **remplace totalement** les Features 1-4 de la v1.0 avec un système de gestion de clés hiérarchique à 3 niveaux et un protocole d'échange bidirectionnel.

---

## Contexte et Objectifs

### Objectif Principal
Chiffrer les communications MAVLink critiques entre drones d'un swarm avec une architecture cryptographique robuste, évolutive et sécurisée.

### Contraintes
- **Réseau**: 2-5 drones en topologie mesh
- **Test initial**: 1 drone + Ground Control Station
- **Hardware**: HSM LeMonolith v0.6 (UART 115200)
- **Framework**: ArduPilot Copter-4.5.x
- **Langage**: C++ pur

---

## Architecture Cryptographique

### Hiérarchie de Clés à 3 Niveaux

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                    ║
║  NIVEAU 1: MASTER KEY (MK)                                        ║
║  ┌────────────────────────────────────────────────────────────┐  ║
║  │ Type:        ChaCha20-256 bits (32 bytes)                  │  ║
║  │ Génération:  Random au boot (init mission)                 │  ║
║  │ Stockage:    HSM exclusif @0x0100                          │  ║
║  │ Durée vie:   Par mission                                   │  ║
║  │ Unique:      OUI - chaque drone a sa propre MK             │  ║
║  │ Export:      JAMAIS après initialisation                   │  ║
║  └────────────────────────────────────────────────────────────┘  ║
║                           │                                        ║
║                           │ HKDF-SHA256                            ║
║                           ▼                                        ║
║  NIVEAU 2: WRAPPER KEY (WK)                                        ║
║  ┌────────────────────────────────────────────────────────────┐  ║
║  │ Type:        secp256r1 (P-256) asymétrique                 │  ║
║  │ WK_private:  Dérivée de MK via HKDF                        │  ║
║  │ WK_public:   Calculée depuis WK_private                    │  ║
║  │ Stockage:    WK_priv wrappée dans HSM @0x0120              │  ║
║  │ Durée vie:   Par mission                                   │  ║
║  │ Usage:       Échange sécurisé des DEK (ECIES)              │  ║
║  └────────────────────────────────────────────────────────────┘  ║
║                           │                                        ║
║                           │ ECIES (pour échange)                   ║
║                           ▼                                        ║
║  NIVEAU 3: DATA ENCRYPTION KEY (DEK)                              ║
║  ┌────────────────────────────────────────────────────────────┐  ║
║  │ Type:        ChaCha20-256 bits (32 bytes)                  │  ║
║  │ MY_DEK:      Pour chiffrer MES messages sortants           │  ║
║  │ PEER_DEKs:   DEKs reçues pour déchiffrer messages entrants │  ║
║  │ Génération:  Random par drone                              │  ║
║  │ Stockage:    MY_DEK wrappée dans HSM @0x0140               │  ║
║  │ Durée vie:   Par mission (pas de rotation en vol)          │  ║
║  └────────────────────────────────────────────────────────────┘  ║
║                                                                    ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Features

### Feature 1: Key Orchestrator

**Objectif**: Gestionnaire centralisé de la hiérarchie de clés MK → WK → DEK.

**Fonctionnalités**:
- Génération Master Key (256 bits random)
- Dérivation Wrapper Key (HKDF-SHA256 → P-256 scalar)
- Génération DEK (256 bits random)
- Wrapping/unwrapping avec MK
- Stockage/restauration HSM
- Cycle de vie par mission

**Fichiers**:
- `libraries/AP_HSM/KeyOrchestrator.h`
- `libraries/AP_HSM/KeyOrchestrator.cpp`

**Documentation**: [FEATURE-1-KEY-ORCHESTRATOR.md](features/FEATURE-1-KEY-ORCHESTRATOR.md)

---

### Feature 2: Key Exchange Protocol

**Objectif**: Protocole d'échange bidirectionnel des clés WK_PUB et DEK via MAVLink.

**Protocole**:
1. Découverte via HEARTBEAT
2. Échange WK_PUB (message custom)
3. Échange DEK chiffrée via ECIES
4. ACK confirmation

**Messages MAVLink Custom**:
| ID | Nom | Description |
|----|-----|-------------|
| 12000 | HSM_WK_EXCHANGE | Échange clé publique WK |
| 12001 | HSM_DEK_EXCHANGE | DEK chiffrée ECIES |
| 12002 | HSM_KEY_ACK | Accusé de réception |

**Fichiers**:
- `libraries/AP_HSM/KeyExchangeProtocol.h`
- `libraries/AP_HSM/KeyExchangeProtocol.cpp`

**Documentation**: [FEATURE-2-KEY-EXCHANGE-PROTOCOL.md](features/FEATURE-2-KEY-EXCHANGE-PROTOCOL.md)

---

### Feature 3: Dual-DEK Communication Engine

**Objectif**: Moteur de chiffrement bidirectionnel où chaque drone utilise sa DEK pour envoyer et la DEK du peer pour recevoir.

**Principe**:
```
ENVOI:     payload → ChaCha20-Poly1305(MY_DEK) → ciphertext
RÉCEPTION: ciphertext → ChaCha20-Poly1305(PEER_DEK) → payload
```

**Messages non chiffrés**:
- HEARTBEAT (découverte)
- HSM_WK_EXCHANGE
- HSM_DEK_EXCHANGE
- HSM_KEY_ACK

**Fichiers**:
- `libraries/AP_HSM/DualDekEngine.h`
- `libraries/AP_HSM/DualDekEngine.cpp`
- `libraries/GCS_MAVLink/GCS_MAVLink.cpp` (modification)
- `libraries/GCS_MAVLink/GCS_Common.cpp` (modification)

**Documentation**: [FEATURE-3-DUAL-DEK-COMMUNICATION.md](features/FEATURE-3-DUAL-DEK-COMMUNICATION.md)

---

## Spécifications Techniques

### Algorithmes Cryptographiques

| Usage | Algorithme | Standard |
|-------|------------|----------|
| Master Key | ChaCha20-256 | - |
| Dérivation WK | HKDF-SHA256 | RFC 5869 |
| Wrapper Key | secp256r1 (P-256) | FIPS 186-4 |
| Échange DEK | ECIES | IEEE 1363a |
| Chiffrement payload | ChaCha20-Poly1305 | RFC 8439 |
| Nonce | Random 12 bytes | - |
| Auth tag | Poly1305 16 bytes | RFC 8439 |

### Stockage HSM

| Offset | Taille | Contenu |
|--------|--------|---------|
| 0x0100 | 32 bytes | Master Key |
| 0x0120 | 32 bytes | Wrapped WK_private |
| 0x0140 | 32 bytes | Wrapped DEK |
| 0x0160 | 32 bytes | HMAC tag (WK) |
| 0x0180 | 32 bytes | HMAC tag (DEK) |

**Écritures HSM par mission**: 5 WRITE (une seule fois au début)

### Communication UART

- **Port**: /dev/ttyUSB0 (ou SERIAL1)
- **Baudrate**: 115200
- **Protocole**: Commandes APDU avec préfixe "A "
- **Timings critiques**:
  - WRITE EEPROM: 2-3 secondes
  - READ EEPROM: 100-200 ms

---

## Décisions Techniques

| Question | Décision | Justification |
|----------|----------|---------------|
| Rétro-compatibilité v1? | Non | Architecture fondamentalement différente |
| Master Key partagée? | Non | Unique par drone pour isolation |
| Authentification initiale | Trust-on-first-use | Simplicité, pas de PKI |
| Certificats X.509 | Non | Overhead trop important |
| Rotation DEK en vol | Non | Une seule par mission |
| Découverte peers | Via HEARTBEAT | Standard MAVLink existant |
| Perfect Forward Secrecy | Oui | ECDH éphémère dans ECIES |
| Nonce strategy | Random 12 bytes | Évite gestion compteur |

---

## Flux de Communication

### Initialisation Mission

```
1. Boot ArduPilot
2. KeyOrchestrator::init_mission_keys()
   ├── generate_master_key() → HSM @0x0100
   ├── derive_wrapper_key()  → HSM @0x0120
   └── generate_dek()        → HSM @0x0140
3. Attente HEARTBEAT peers
4. Pour chaque nouveau peer:
   └── KeyExchangeProtocol::initiate_exchange()
```

### Échange de Clés

```
Drone A                              Drone B
   │                                    │
   │  HSM_WK_EXCHANGE(WK_PUB_A)         │
   ├───────────────────────────────────►│
   │                                    │
   │  HSM_WK_EXCHANGE(WK_PUB_B)         │
   │◄───────────────────────────────────┤
   │                                    │
   │  HSM_DEK_EXCHANGE(ECIES(DEK_A))    │
   ├───────────────────────────────────►│
   │                                    │
   │  HSM_DEK_EXCHANGE(ECIES(DEK_B))    │
   │◄───────────────────────────────────┤
   │                                    │
   │  HSM_KEY_ACK(OK)                   │
   │◄──────────────────────────────────►│
   │                                    │
   ═══════════════════════════════════════
         SESSION SÉCURISÉE ÉTABLIE
```

### Communication Chiffrée

```
Drone A                              Drone B
   │                                    │
   │ [Header][Enc(payload,DEK_A)][nonce][tag]
   ├───────────────────────────────────►│
   │                     Decrypt with DEK_A
   │                                    │
   │ [Header][Enc(payload,DEK_B)][nonce][tag]
   │◄───────────────────────────────────┤
   │ Decrypt with DEK_B                 │
```

---

## Plan d'Implémentation

### Phase 1: Feature 1 - Key Orchestrator
1. Créer `KeyOrchestrator.h/.cpp`
2. Implémenter génération MK
3. Implémenter dérivation WK (HKDF → P-256)
4. Implémenter génération DEK
5. Implémenter wrapping/unwrapping
6. Implémenter stockage/restauration HSM
7. Tests avec HSM réel

### Phase 2: Feature 2 - Key Exchange Protocol
1. Définir messages MAVLink custom (XML)
2. Créer `KeyExchangeProtocol.h/.cpp`
3. Implémenter ECIES encrypt/decrypt
4. Implémenter machine à états
5. Implémenter handlers messages
6. Tests drone-GCS

### Phase 3: Feature 3 - Dual-DEK Engine
1. Créer `DualDekEngine.h/.cpp`
2. Modifier `comm_send_buffer()` pour chiffrement
3. Modifier `packetReceived()` pour déchiffrement
4. Implémenter filtrage messages
5. Tests communication chiffrée

### Phase 4: Intégration et Tests
1. Tests unitaires complets
2. Tests SITL multi-drones
3. Tests avec HSM réel
4. Documentation finale

---

## Sécurité

### Propriétés Garanties

- **Confidentialité**: ChaCha20-Poly1305 sur payloads
- **Intégrité**: Tag Poly1305 sur chaque message
- **Authenticité**: DEK unique par drone identifie la source
- **Perfect Forward Secrecy**: Clé éphémère ECIES par échange
- **Isolation des clés**: MK jamais exportée après init

### Menaces Mitigées

| Menace | Mitigation |
|--------|------------|
| Interception payload | Chiffrement ChaCha20 |
| Modification message | Tag Poly1305 |
| Replay attack | Nonce random unique |
| Compromission DEK | Isolation par drone, pas de rotation forcée |
| Compromission HSM | MK unique par drone |

### Menaces Non Couvertes (v2.0)

- Authentification initiale forte (pas de certificats)
- Protection contre DoS
- Key revocation

---

## Références

### Standards
- **RFC 5869**: HKDF
- **RFC 8439**: ChaCha20-Poly1305
- **FIPS 186-4**: ECDSA / P-256
- **IEEE 1363a**: ECIES

### Documentation Projet
- [FEATURE-1-KEY-ORCHESTRATOR.md](features/FEATURE-1-KEY-ORCHESTRATOR.md)
- [FEATURE-2-KEY-EXCHANGE-PROTOCOL.md](features/FEATURE-2-KEY-EXCHANGE-PROTOCOL.md)
- [FEATURE-3-DUAL-DEK-COMMUNICATION.md](features/FEATURE-3-DUAL-DEK-COMMUNICATION.md)
- [HSM Skills](../../build_skill/hsm_skills.md)

### Ressources Externes
- ArduPilot: https://ardupilot.org/dev/
- MAVLink: https://mavlink.io/
- micro-ecc: https://github.com/kmackay/micro-ecc

---

**Approuvé par**: [En attente]
**Date approbation**: 2026-01-24
