# Build Skills - Base de Connaissances Projet ArduPilot + HSM

**Version**: 2.0
**Date**: 2026-01-24

Ce dossier contient la base de connaissances complète du projet d'intégration HSM LeMonolith avec ArduPilot.

---

## POINTS IMPORTANTS - RÉSUMÉ CONVERSATION

### Décisions Prises (Q&A 2026-01-24)

| Question | Réponse |
|----------|---------|
| Rétro-compatibilité v1? | **NON** - Remplace totalement l'existant |
| Nombre de drones | **2-5 drones** |
| Topologie réseau | **Mesh**, test initial: 1 drone + GCS |
| Master Key génération | **Au boot** (init mission) |
| Master Key unique? | **OUI** - chaque drone a sa propre MK |
| Wrapper Key durée | **Par mission** (3 clés générées une fois) |
| Nonce ChaCha20 | **Random 12 bytes** |
| Rotation DEK | **Par mission** (pas en vol) |
| Messages en transit | **HEARTBEAT en clair**, autres attendent DEK |
| Transport MAVLink | **Nouveau message custom** |
| Authentification | **Trust-on-first-use** (pas de certificats) |
| Découverte drones | **Via HEARTBEAT** |
| PFS (Perfect Forward Secrecy) | **OUI** - ECDH éphémère + rotation WK |
| Stockage HSM | **MK + WK_priv wrappée + DEK wrappée** |
| Langage | **C++ pur** |

---

## Architecture v2.0 (NOUVELLE)

**L'architecture v2.0 remplace totalement les Features 1-4 de la v1.0**

### Hiérarchie de Clés à 3 Niveaux

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                    ║
║  NIVEAU 1: MASTER KEY (MK)                                        ║
║  ├── Type: ChaCha20-256 bits (32 bytes)                           ║
║  ├── Génération: Random au boot (hal.util->get_random_vals)       ║
║  ├── Stockage: HSM exclusif @0x0100                               ║
║  ├── Durée vie: Par mission                                       ║
║  └── UNIQUE par drone                                             ║
║                                                                    ║
║          │ HKDF-SHA256 ("WrapperKey-P256-v1")                     ║
║          ▼                                                         ║
║                                                                    ║
║  NIVEAU 2: WRAPPER KEY (WK)                                        ║
║  ├── Type: secp256r1 (P-256) asymétrique                          ║
║  ├── WK_private: Dérivée de MK via HKDF                           ║
║  ├── WK_public: Calculée depuis WK_private (micro-ecc)            ║
║  ├── Stockage: WK_priv wrappée HSM @0x0120                        ║
║  └── Usage: Échange sécurisé des DEK (ECIES)                      ║
║                                                                    ║
║          │ ECIES (ChaCha20-Poly1305)                              ║
║          ▼                                                         ║
║                                                                    ║
║  NIVEAU 3: DATA ENCRYPTION KEY (DEK)                              ║
║  ├── Type: ChaCha20-256 bits (32 bytes)                           ║
║  ├── MY_DEK: Pour chiffrer MES messages sortants                  ║
║  ├── PEER_DEKs: DEKs reçues pour déchiffrer messages entrants     ║
║  ├── Génération: Random par drone                                 ║
║  └── Stockage: MY_DEK wrappée HSM @0x0140                         ║
║                                                                    ║
╚══════════════════════════════════════════════════════════════════╝
```

### Nouvelles Features v2.0

| Feature | Description | Fichiers à Créer |
|---------|-------------|------------------|
| **F1: Key Orchestrator** | Gestion hiérarchie MK→WK→DEK | `KeyOrchestrator.h/.cpp` |
| **F2: Key Exchange Protocol** | Échange WK_PUB + DEK via MAVLink | `KeyExchangeProtocol.h/.cpp` |
| **F3: Dual-DEK Engine** | Chiffrement bidirectionnel | `DualDekEngine.h/.cpp` |

---

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
         │  3. HSM_DEK_EXCHANGE (ECIES)           │
         │────────────────────────────────────────►│
         │     ECIES(DEK_A, WK_PUB_B)             │
         │◄────────────────────────────────────────│
         │     ECIES(DEK_B, WK_PUB_A)             │
         │                                        │
         │  4. HSM_KEY_ACK                        │
         │◄──────────────────────────────────────►│
         │                                        │
         │  5. COMMUNICATION CHIFFRÉE             │
         │────────────────────────────────────────►│
         │     ChaCha20-Poly1305(payload, DEK_A)  │
         │◄────────────────────────────────────────│
         │     ChaCha20-Poly1305(payload, DEK_B)  │
```

---

## Spécifications Techniques

### Algorithmes Cryptographiques

| Usage | Algorithme | Standard |
|-------|------------|----------|
| Master Key | ChaCha20-256 (32 bytes) | - |
| Dérivation WK | HKDF-SHA256 | RFC 5869 |
| Wrapper Key | secp256r1 (P-256) | FIPS 186-4 |
| Échange DEK | ECIES | IEEE 1363a |
| Chiffrement payload | ChaCha20-Poly1305 | RFC 8439 |
| Nonce | **Random 12 bytes** | - |
| Auth tag | Poly1305 16 bytes | RFC 8439 |

### Stockage HSM LeMonolith

| Offset | Taille | Contenu |
|--------|--------|---------|
| 0x0100 | 32 bytes | Master Key (MK) |
| 0x0120 | 32 bytes | Wrapped WK_private |
| 0x0140 | 32 bytes | Wrapped DEK |
| 0x0160 | 32 bytes | HMAC tag (WK) |
| 0x0180 | 32 bytes | HMAC tag (DEK) |

**Écritures HSM par mission**: 5 WRITE (une seule fois au début)

### Messages MAVLink Custom

| ID | Nom | Taille Payload | Usage |
|----|-----|----------------|-------|
| 12000 | HSM_WK_EXCHANGE | 70 bytes | Échange clé publique WK (64B) + timestamp |
| 12001 | HSM_DEK_EXCHANGE | 126 bytes | DEK chiffrée ECIES |
| 12002 | HSM_KEY_ACK | 4 bytes | Accusé de réception |

### Messages NON Chiffrés

- **HEARTBEAT** - Toujours en clair (découverte peers)
- **HSM_WK_EXCHANGE** - Nécessaire pour établir session
- **HSM_DEK_EXCHANGE** - Nécessaire pour établir session
- **HSM_KEY_ACK** - Nécessaire pour établir session

---

## Principe Dual-DEK

```
DRONE A                              DRONE B
┌─────────────────┐                  ┌─────────────────┐
│ MY_DEK = DEK_A  │                  │ MY_DEK = DEK_B  │
│ PEER_DEK = DEK_B│                  │ PEER_DEK = DEK_A│
└────────┬────────┘                  └────────┬────────┘
         │                                    │
         │  Chiffré avec DEK_A                │
         │───────────────────────────────────►│
         │                    Déchiffré avec DEK_A
         │                                    │
         │  Chiffré avec DEK_B                │
         │◄───────────────────────────────────│
Déchiffré│                                    │
avec DEK_B                                    │
```

**Avantages Dual-DEK:**
- Traçabilité: On sait qui a envoyé (par la DEK utilisée)
- Pas de négociation de clé commune
- Chaque drone contrôle sa propre clé de chiffrement

---

## Point Technique: Dérivation HKDF → P-256

Pour dériver une clé privée P-256 valide depuis la Master Key:

```cpp
bool derive_p256_scalar_from_hkdf(const uint8_t* mk, uint8_t* wk_priv) {
    const char* salt = "ArduPilot-HSM-Salt-v2";
    const char* info = "WrapperKey-P256-v1";

    uint8_t candidate[32];
    uint8_t counter = 0;

    // Boucle jusqu'à scalar valide (< ordre courbe P-256)
    // En pratique: 1 itération suffit 99.99999% des cas
    do {
        char info_counter[64];
        snprintf(info_counter, sizeof(info_counter),
                 counter == 0 ? "%s" : "%s-%d", info, counter);

        hkdf_sha256(salt, strlen(salt), mk, 32,
                    info_counter, strlen(info_counter),
                    candidate, 32);
        counter++;
    } while (!is_valid_p256_scalar(candidate) && counter < 255);

    memcpy(wk_priv, candidate, 32);
    return true;
}
```

---

## Documentation du Projet

### Structure des Fichiers

```
docs/hsm-project/
├── README.md                              # Vue d'ensemble v2.0
├── PRD-V2.md                              # Product Requirements Document
├── features/
│   ├── FEATURE-1-KEY-ORCHESTRATOR.md      # Spec Key Orchestrator
│   ├── FEATURE-2-KEY-EXCHANGE-PROTOCOL.md # Spec Exchange Protocol
│   └── FEATURE-3-DUAL-DEK-COMMUNICATION.md# Spec Dual-DEK Engine
└── archive/
    └── v1/                                # Anciennes features (obsolètes)
```

### Skills Techniques

| Fichier | Contenu |
|---------|---------|
| [ardupilot_skills.md](ardupilot_skills.md) | Build waf, UART, SITL, crypto ArduPilot |
| [hsm_skills.md](hsm_skills.md) | Communication HSM, APDU, timings, debug |

---

## Quick Start

### Compilation

```bash
./waf configure --board sitl
./waf copter
```

### Test avec HSM

```bash
# Lancer SITL (sans --console!)
build/sitl/bin/arducopter --model + --serial1 uart:/dev/ttyUSB0:115200 &

# Connecter MAVProxy
mavproxy.py --master=tcp:127.0.0.1:5760 --console

# Observer logs
grep -E "(KeyOrch|KEP|DualDEK):" /tmp/ardupilot.log
```

---

## Index Rapide

### Par Problème

| Problème | Document | Section |
|----------|----------|---------|
| Timeout SELECT applet | hsm_skills.md | § 4.1 |
| WRITE timeout | hsm_skills.md | § 4.3, 5.1 |
| HSM instable | hsm_skills.md | § 4.4, 9.3 |
| --console interfère UART | ardupilot_skills.md | § 2.3 |
| Dérivation HKDF→P256 | Ce fichier | § Point Technique |

### Par Use Case

| Use Case | Document |
|----------|----------|
| Implémenter Key Orchestrator | FEATURE-1-KEY-ORCHESTRATOR.md |
| Implémenter ECIES | FEATURE-2-KEY-EXCHANGE-PROTOCOL.md |
| Chiffrer payload MAVLink | FEATURE-3-DUAL-DEK-COMMUNICATION.md |

---

## Historique

### v2.0 (2026-01-24)
- Nouvelle architecture 3 niveaux (MK→WK→DEK)
- Protocole d'échange bidirectionnel
- Dual-DEK communication engine
- **Remplace totalement v1.0**

### v1.0 (2026-01-22 - 2026-01-23)
- Features 1-4 initiales (obsolètes)
- Archivé dans docs/hsm-project/archive/v1/

---

## Prochaines Étapes

1. **Feature 1**: Implémenter `KeyOrchestrator.h/.cpp`
2. **Feature 2**: Implémenter `KeyExchangeProtocol.h/.cpp`
3. **Feature 3**: Implémenter `DualDekEngine.h/.cpp`
4. **Tests**: SITL avec HSM réel

---

**Dernière mise à jour**: 2026-01-24
