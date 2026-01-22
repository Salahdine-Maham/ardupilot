# PRD - Implémentation Sécurité MAVLink avec LeMonolith HSM

## Contexte du Projet

Ce document définit le plan d'implémentation progressive d'une couche de chiffrement sécurisée pour les messages MAVLink dans ArduPilot, utilisant le HSM LeMonolith Dev Kit (LEM) v0.6.

### Expert Role
Expert senior en cybersécurité embarquée, JavaCard, cryptographie hybride et développement ArduPilot/PX4, assistant un doctorant dans l'implémentation incrémentale par features consécutives.

---

## Phase 0: Interview Structuré et Progressif

**IMPORTANT**: Avant toute proposition de plan, code ou features, un interview détaillé doit être conduit pour affiner les besoins. Les questions doivent être posées de manière ciblée, une par une ou par groupe thématique.

### 1. Détails Techniques sur LeMonolith
- Quel applet JavaCard exact utilises-tu (nom AID, version) ?
- Quelles APDU précises sont disponibles pour :
  - Générer une paire de clés
  - Récupérer la clé publique
  - Vérifier PIN
  - Autres opérations
- Le secure element supporte-t-il déjà ECDSA secp256k1, P-256 ou Ed25519 ?
- Lequel préfères-tu et pourquoi ?

### 2. Architecture Cryptographique et Tradeoffs
- Quel algorithme asymétrique priorises-tu ?
  - secp256k1 (compatibilité BIP32)
  - P-256
  - Ed25519
- Quels tradeoffs acceptes-tu ?
  - Performance vs taille clé
  - Taille clé vs compatibilité JavaCard
- Veux-tu absolument éviter l'export de la clé privée (même une fois au boot) ou acceptes-tu un cache RAM volatile ?
- Quelle durée de vie pour la DEK ?
  - Par session
  - Toutes les N minutes
  - Par vol
- Quels messages MAVLink critiques veux-tu chiffrer en priorité ?
  - Liste précise (HEARTBEAT, ATTITUDE, COMMAND_LONG, etc.)

### 3. Implémentation et Contraintes ArduPilot
- Quel board utilises-tu (Pixhawk, Cube, autre) ?
- Quelle version ArduPilot ?
- Quelles bibliothèques asymétriques légères es-tu prêt à intégrer ?
  - micro-ecc
  - ed25519-donna
  - autre
- Quelles sont tes contraintes de performance ?
  - Latence max acceptable
  - % CPU max
  - Mémoire disponible
- Compatibilité GCS :
  - Veux-tu un mode « secure » désactivable pour rester compatible QGroundControl/Mission Planner ?

### 4. Tests et Validation
- Quel environnement de test utilises-tu principalement ?
  - SITL
  - HITL
  - Vol réel
- Y a-t-il des contraintes spécifiques ?
  - Batterie
  - Poids
  - Réglementation

---

## Objectif Global du Projet

Chiffrer le payload des messages MAVLink critiques avec ChaCha20 (256 bits). Permettre un échange sécurisé de clés entre drones/swarm ou avec une GCS, compatible autant que possible avec GCS standards (mode « secure » activable).

---

## HSM Utilisé: LeMonolith Dev Kit (LEM) v0.6

### Spécifications Matérielles
- **Microcontrôleur**: ESP32-WROOM-32
- **Secure Element**: JavaCard grade bancaire
- **Applets**: Open-source

### Communication
- **Interface**: UART
- **Baudrate**: 115200 bauds
- **Format**: 8N1

### Commandes
- `on\r\n` - Activer le Secure Element
- `off\r\n` - Désactiver le Secure Element
- **APDU**: Format hexadécimal terminé par `\r\n`
- **Réponse**: Hexadécimal + SW (ex. `9000` = succès)

### Phase Actuelle d'Utilisation
Utilisation **UNIQUEMENT** pour :
- Stockage sécurisé de clés
- Récupération de clés (génération on-card)
- Récupération clé publique via APDU

**Toutes les opérations crypto (ChaCha20 + asymétrique) se font en software dans ArduPilot.**

---

## Contexte Technique Existant

### Classe AP_HSM
- **Fichiers**: `AP_HSM.h` / `AP_HSM.cpp`
- **Configuration UART**: 115200 bauds
- **Commandes disponibles**:
  - `"on"` / `"off"`
  - `send_apdu()` - Envoi commandes APDU
  - `get_key()` - Retourne clé hex → bytes

### Implémentation ChaCha20
- **Fichiers**: `chacha20.h` / `chacha20.c`
- **Langage**: Pure C

### Travaux de Référence
- **MAVSec** (Allouch et al., Mai & Haque 2024)
- **Recommandation**: ChaCha20

---

## Contraintes ArduPilot

### Architecture MAVLink
- **Localisation**: `libraries/GCS_MAVLink/`
- **Envoi de messages**:
  - `GCS_MAVLink::send_message()`
  - `mavlink_msg_xxx_send()`
- **Réception de messages**:
  - `GCS_MAVLink::handle_msg()`

### Contraintes Système
- Code **real-time**
- **Thread-safe**
- **Mémoire limitée**

---

## Plan d'Implémentation Incrémental

Pour chaque feature, le plan doit fournir :
1. **Objectif** et dépendances
2. **Localisation précise** du code (fichiers/classes)
3. **Extraits de code C++** concrets, commentés et intégrables
4. **Test de validation détaillé** avec procédure étape par étape :
   - SITL
   - MAVProxy
   - QGroundControl
   - Logs console
   - Messages observés
   - **Critères de succès/échec clairs**

**La feature doit être validée avant de passer à la suivante.**

---

## Feature 1: Initialisation Fiable et Robuste de LeMonolith

### Objectif
Démarrer l'UART, activer le SE (`on\r\n`), SELECT l'applet JavaCard par défaut, vérifier la réponse (SW 9000). Ajouter gestion d'erreurs (timeout, retry, flush).

### Dépendances
Aucune.

### Implémentation
- Extension de `AP_HSM::begin()`
- Nouvelle fonction `init_monolith()`

### Test de Validation

#### Procédure
1. Lancer SITL:
   ```bash
   sim_vehicle.py -v ArduCopter
   ```

2. Observer la console ArduPilot au boot:
   - Logs "Initialisation du HSM terminée"
   - Réponse APDU SELECT avec SW 9000

3. Simuler erreur:
   - Débrancher UART virtuel OU
   - Envoyer mauvaise APDU
   - Vérifier logs d'erreur et retry

#### Critères de Succès
- Initialisation réussie sans erreur
- Applet SELECT confirmé (SW 9000)

#### Critères d'Échec
- Timeout sans réponse
- SW différent de 9000
- Pas de retry en cas d'erreur

---

## Feature 2: Génération et Récupération Sécurisée de la Paire Asymétrique

### Objectif
Générer une paire ECDSA (secp256k1 ou P-256) on-card via APDU. Récupérer et stocker la clé publique (RAM volatile). **Ne jamais exporter la privée.**

### Dépendances
Feature 1

### Implémentation
- Nouvelles fonctions dans `AP_HSM`:
  - `generate_keypair()`
  - `get_public_key()`
- APDU concrètes à définir

### Test de Validation

#### Procédure
1. Au boot (après Feature 1):
   - Appeler `generate_keypair()`
   - Puis `get_public_key()`

2. Vérifier logs console:
   - Clé publique hex affichée
   - Ex: 65 bytes pour P-256 uncompressed

3. Redémarrer SITL:
   - Vérifier que clé publique est identique
   - (Persistance on-card)

#### Critères de Succès
- Clé publique récupérée correctement
- Identique après reboot
- Aucun export de clé privée

#### Critères d'Échec
- Clé publique change après reboot
- Erreur APDU
- Export accidentel de clé privée

---

## Feature 3: Échange Initial de Clés Publiques (Pairing)

### Objectif
Envoyer sa clé publique à un autre drone/GCS et recevoir la leur via message MAVLink custom (`PUBLIC_KEY_EXCHANGE`). Stocker dans table par sysid/compid.

### Dépendances
Feature 2

### Implémentation
- Nouvelle classe `AP_MAVLink_Secure` pour la table de clés

### Test de Validation

#### Procédure
1. Lancer deux instances SITL:
   - Drone1: sysid=1
   - Drone2: sysid=2
   - Connectées via MAVProxy

2. Trigger pairing:
   - Commande custom OU au boot

3. Observer avec MAVProxy:
   - Messages `PUBLIC_KEY_EXCHANGE` envoyés/reçus
   - Logs "Clé publique de sysid X stockée"

#### Critères de Succès
- Chaque drone voit la clé publique de l'autre dans sa table
- Vérifiable via log ou param debug

#### Critères d'Échec
- Messages non reçus
- Clés non stockées
- Erreur de parsing

---

## Feature 4: Génération et Chiffrement de la Data Encryption Key (DEK)

### Objectif
Générer aléatoirement DEK 256 bits. Chiffrer avec clé publique destinataire (software, ex. micro-ecc).

### Dépendances
Feature 3

### Implémentation
- Fonctions dans `AP_MAVLink_Secure`:
  - `generate_dek()`
  - `encrypt_dek()`

### Test de Validation

#### Procédure
1. Deux SITL pairés

2. Trigger génération DEK:
   - Logs "DEK générée"
   - Logs "DEK chiffrée pour sysid X"
   - Taille ~128 bytes

3. Vérifier que DEK chiffrée est différente pour chaque destinataire

#### Critères de Succès
- DEK chiffrée générée sans erreur
- Taille correcte (~128 bytes selon algorithme)
- Différente pour chaque destinataire

#### Critères d'Échec
- Erreur de génération aléatoire
- Taille incorrecte
- DEK identique pour différents destinataires

---

## Feature 5: Chiffrement du Payload MAVLink avec ChaCha20

### Objectif
Chiffrer payload des messages critiques avec ChaCha20(DEK, nonce). Nonce unique (sysid + compid + counter + seq).

### Dépendances
Feature 4

### Implémentation
- Fonction `encrypt_payload()`

### Test de Validation

#### Procédure
1. Deux SITL pairés, mode secure activé

2. Envoyer HEARTBEAT:
   - Capturer avec MAVProxy
   - Payload chiffré (longueur augmentée, données binaires aléatoires)

3. Comparer payload clair vs chiffré

#### Critères de Succès
- Payload des messages critiques modifié
- Nonce unique à chaque message
- Données apparaissent aléatoires

#### Critères d'Échec
- Payload non modifié
- Nonce répété
- Pattern visible dans données chiffrées

---

## Feature 6: Format et Envoi du Message Sécurisé Complet

### Objectif
Créer message custom `SECURE_PAYLOAD` contenant flag, nonce, DEK_chiffrée, payload_chiffré. Intégrer dans `send_message()`.

### Dépendances
Feature 5

### Test de Validation

#### Procédure
1. Deux SITL, envoyer message critique

2. MAVProxy:
   - Observer uniquement messages `SECURE_PAYLOAD`
   - Pas les messages originaux

3. Vérifier structure:
   - flag=1
   - nonce 12B
   - DEK_chiffrée
   - payload variable

#### Critères de Succès
- Messages critiques remplacés par `SECURE_PAYLOAD`
- Structure correctement formatée
- Tous les champs présents

#### Critères d'Échec
- Messages originaux encore visibles
- Structure incorrecte
- Champs manquants

---

## Feature 7: Réception et Déchiffrement du Message Sécurisé

### Objectif
Dans `handle_msg()`, détecter `SECURE_PAYLOAD` → récupérer clé privée (cache) → déchiffrer DEK → déchiffrer payload → reconstruire message original.

### Dépendances
Feature 6

### Test de Validation

#### Procédure
1. Deux SITL en mode secure

2. Envoyer HEARTBEAT d'un drone à l'autre:
   - Logs récepteur "Payload déchiffré avec succès"

3. QGroundControl connecté au récepteur:
   - Voir HEARTBEAT normal (comme non sécurisé)

#### Critères de Succès
- Messages reçus et traités normalement par le reste du système
- QGC fonctionne sans modifications
- Logs confirment déchiffrement

#### Critères d'Échec
- Erreur de déchiffrement
- Message non reconstruit
- QGC ne voit pas les messages

---

## Feature 8: Gestion de Session et Rotation de DEK

### Objectif
Timer ou trigger pour nouvelle DEK périodique + ré-échange sécurisé.

### Dépendances
Feature 7

### Test de Validation

#### Procédure
1. Deux SITL, attendre timer (ex. 60s)

2. Observer logs:
   - "Nouvelle DEK générée et échangée"
   - Nouveaux messages `SECURE_PAYLOAD` avec nouvelle DEK_chiffrée

#### Critères de Succès
- Communication continue après rotation
- Sans perte de lien
- Nouvelle DEK appliquée automatiquement

#### Critères d'Échec
- Perte de communication lors de la rotation
- DEK non mise à jour
- Messages perdus

---

## Feature 9: Points d'Attention Globaux et Tests de Performance

### Objectif
Mesurer overhead, robustesse, préparation évolution on-card.

### Test de Validation

#### Procédure
1. Benchmark SITL:
   - Taux messages/s avant/après secure
   - Mesure CPU/mémoire

2. Simuler perte HSM:
   - Fallback non sécurisé
   - Vérifier comportement

#### Critères de Succès
- Overhead < 10-20% CPU
- Communication maintenue
- Fallback gracieux

#### Critères d'Échec
- Overhead > 20% CPU
- Crash lors de la perte HSM
- Dégradation significative performance

---

## Notes de Mise en Œuvre

### Approche Incrémentale
- Chaque feature doit être complètement validée avant de passer à la suivante
- Tests documentés avec logs et captures
- Commits git après chaque feature validée

### Documentation
- Code C++ commenté en français et anglais
- Logs de debug clairs et informatifs
- Documentation API pour nouvelles fonctions

### Évolution Future
- Prévoir migration progressive des opérations crypto vers on-card
- Architecture modulaire pour faciliter changements d'algorithmes
- Compatibilité ascendante

---

## Références

### Bibliographie
- **MAVSec**: Allouch et al., Mai & Haque 2024
- **ArduPilot Documentation**: https://ardupilot.org/dev/
- **MAVLink Protocol**: https://mavlink.io/

### Standards Cryptographiques
- ChaCha20: RFC 8439
- ECDSA: FIPS 186-4
- secp256k1: Bitcoin BIP32

---

**Version**: 1.0
**Date**: 2026-01-22
**Statut**: Phase Interview - En attente de réponses utilisateur
