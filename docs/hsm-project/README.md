# Projet HSM LeMonolith - Sécurité MAVLink v2.0

**Version**: 2.0
**Date**: 2026-01-24
**Statut**: Refonte architecture - Nouvelle implémentation

---

## Objectif

Implémenter une couche de chiffrement sécurisée pour les communications MAVLink dans ArduPilot, utilisant le HSM LeMonolith Dev Kit v0.6 avec une architecture cryptographique à 3 niveaux.

## Changement Majeur v2.0

**L'architecture v2.0 remplace totalement les Features 1-4 de la v1.0** avec un nouveau système de gestion de clés hiérarchique et un protocole d'échange bidirectionnel.

## Architecture v2.0

```
╔════════════════════════════════════════════════════════════════════╗
║            HIÉRARCHIE DE CLÉS À 3 NIVEAUX                          ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  NIVEAU 1: MASTER KEY (MK)                                          ║
║  ├── Type: ChaCha20-256 bits                                        ║
║  ├── Stockage: HSM exclusif @0x0100                                 ║
║  ├── Génération: Au boot (init mission)                             ║
║  └── Durée de vie: Par mission                                      ║
║                                                                      ║
║          │ HKDF-SHA256                                               ║
║          ▼                                                           ║
║                                                                      ║
║  NIVEAU 2: WRAPPER KEY (WK)                                         ║
║  ├── Type: secp256r1 (P-256) asymétrique                            ║
║  ├── WK_priv: Dérivée de MK, stockée wrappée HSM @0x0120            ║
║  ├── WK_pub: Échangée avec peers via MAVLink                        ║
║  └── Durée de vie: Par mission                                      ║
║                                                                      ║
║          │ ECIES (échange)                                          ║
║          ▼                                                           ║
║                                                                      ║
║  NIVEAU 3: DATA ENCRYPTION KEY (DEK)                                ║
║  ├── Type: ChaCha20-256 bits                                        ║
║  ├── MY_DEK: Pour chiffrer MES messages sortants                    ║
║  ├── PEER_DEKs: DEKs reçues des peers pour déchiffrer               ║
║  ├── Stockage: MY_DEK wrappée HSM @0x0140                           ║
║  └── Durée de vie: Par mission                                      ║
║                                                                      ║
╚════════════════════════════════════════════════════════════════════╝
```

## Nouvelles Features (v2.0)

| Feature | Document | Statut | Description |
|---------|----------|--------|-------------|
| F1 | [FEATURE-1-KEY-ORCHESTRATOR.md](features/FEATURE-1-KEY-ORCHESTRATOR.md) | 🔄 À implémenter | Gestionnaire centralisé de clés MK→WK→DEK |
| F2 | [FEATURE-2-KEY-EXCHANGE-PROTOCOL.md](features/FEATURE-2-KEY-EXCHANGE-PROTOCOL.md) | 🔄 À implémenter | Protocole d'échange WK_PUB + DEK via MAVLink |
| F3 | [FEATURE-3-DUAL-DEK-COMMUNICATION.md](features/FEATURE-3-DUAL-DEK-COMMUNICATION.md) | 🔄 À implémenter | Moteur chiffrement bidirectionnel |

## Spécifications Techniques

### Réseau de Drones
- **Nombre**: 2-5 drones
- **Topologie**: Mesh (maillé)
- **Test initial**: 1 drone + Ground Control Station
- **Découverte**: Via heartbeats MAVLink

### Algorithmes Cryptographiques
| Usage | Algorithme |
|-------|------------|
| Master Key | ChaCha20-256 (32 bytes) |
| Dérivation WK | HKDF-SHA256 (RFC 5869) |
| Wrapper Key | secp256r1 / P-256 (ECDH) |
| Échange DEK | ECIES (ChaCha20-Poly1305) |
| Chiffrement payload | ChaCha20-Poly1305 |
| Nonce | Random 12 bytes |

### Stockage HSM LeMonolith

| Offset | Taille | Contenu |
|--------|--------|---------|
| 0x0100 | 32 bytes | Master Key (MK) |
| 0x0120 | 32 bytes | Wrapped WK_private |
| 0x0140 | 32 bytes | Wrapped DEK |
| 0x0160 | 32 bytes | HMAC tag (WK) |
| 0x0180 | 32 bytes | HMAC tag (DEK) |

### Messages MAVLink Custom (à définir)
- `HSM_WK_EXCHANGE` (ID: 12000) - Échange clé publique WK
- `HSM_DEK_EXCHANGE` (ID: 12001) - Échange DEK chiffrée ECIES
- `HSM_KEY_ACK` (ID: 12002) - Accusé de réception

### Messages Non Chiffrés
- **HEARTBEAT**: Toujours en clair (découverte peers)
- Autres messages: Attendent l'échange DEK avant envoi

## Flux de Communication

```
┌─────────────────┐                      ┌─────────────────┐
│    DRONE A      │                      │    DRONE B      │
│    (ou GCS)     │                      │                 │
└────────┬────────┘                      └────────┬────────┘
         │                                        │
         │  1. HEARTBEAT (clair)                  │
         │◄──────────────────────────────────────►│
         │     Découverte mutuelle                │
         │                                        │
         │  2. HSM_WK_EXCHANGE                    │
         │────────────────────────────────────────►│
         │◄────────────────────────────────────────│
         │     Échange WK_PUB_A ↔ WK_PUB_B        │
         │                                        │
         │  3. HSM_DEK_EXCHANGE                   │
         │────────────────────────────────────────►│
         │     ECIES(DEK_A, WK_PUB_B)             │
         │◄────────────────────────────────────────│
         │     ECIES(DEK_B, WK_PUB_A)             │
         │                                        │
         │  4. HSM_KEY_ACK                        │
         │◄──────────────────────────────────────►│
         │     Confirmation mutuelle              │
         │                                        │
         │  5. COMMUNICATION CHIFFRÉE             │
         │────────────────────────────────────────►│
         │     ChaCha20-Poly1305(payload, DEK_A)  │
         │◄────────────────────────────────────────│
         │     ChaCha20-Poly1305(payload, DEK_B)  │
         │                                        │
```

## Documentation

### Documents Principaux
| Document | Description |
|----------|-------------|
| [PRD-V2.md](PRD-V2.md) | Product Requirements Document v2.0 |
| [ARCHITECTURE-CRYPTO-COMPLETE.md](features/ARCHITECTURE-CRYPTO-COMPLETE.md) | Architecture détaillée |

### Anciennes Features (v1.0 - Archivées)
Les anciennes features sont archivées dans [archive/v1/](archive/v1/)

## Progression

```
Feature 1 (Key Orchestrator)     ░░░░░░░░░░░░░░░░░░░░   0%
Feature 2 (Key Exchange)         ░░░░░░░░░░░░░░░░░░░░   0%
Feature 3 (Dual-DEK Comm)        ░░░░░░░░░░░░░░░░░░░░   0%

GLOBAL:                          ░░░░░░░░░░░░░░░░░░░░   0%
```

## Décisions Techniques Clés

| Question | Décision |
|----------|----------|
| Rétro-compatibilité v1? | Non - Remplacement total |
| Master Key partagée? | Non - Unique par drone |
| Authentification initiale | Trust-on-first-use (pas de certificats) |
| Perfect Forward Secrecy | Oui - ECDH éphémère + rotation WK |
| Rotation DEK | Par mission (pas de rotation en vol) |

## Références

- **HSM Skills**: [/build_skill/hsm_skills.md](../../build_skill/hsm_skills.md)
- **ArduPilot**: https://ardupilot.org/dev/
- **MAVLink**: https://mavlink.io/
- **ChaCha20-Poly1305**: RFC 8439
- **HKDF**: RFC 5869
- **ECIES**: IEEE 1363a

---

**Dernière mise à jour**: 2026-01-24
