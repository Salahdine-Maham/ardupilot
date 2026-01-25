# Archive v1.0 - Anciennes Features HSM

**Date d'archivage**: 2026-01-24
**Raison**: Remplacé par architecture v2.0

---

## Contenu Archivé

Les features v1.0 (22-23 janvier 2026) ont été remplacées par l'architecture v2.0.

### Features v1.0 (Obsolètes)

| Feature | Description | Statut Final |
|---------|-------------|--------------|
| F1 | Init HSM (OFF→ON→SELECT→VERIFY) | ✅ Fonctionnelle |
| F2 | Keypair P-256 (micro-ecc) | ✅ Fonctionnelle |
| F3 | DEK + ECDH + HKDF | ✅ Implémentée |
| F4 | Encryption payload MAVLink | ✅ Implémentée |

### Différences v1.0 vs v2.0

| Aspect | v1.0 | v2.0 |
|--------|------|------|
| Hiérarchie clés | Keypair + DEK | MK → WK → DEK (3 niveaux) |
| Échange clés | Non implémenté | Protocole complet |
| Communication | Unidirectionnelle | Dual-DEK bidirectionnelle |
| Messages MAVLink | Pas de custom | 3 messages custom |

---

## Fichiers de Référence

Les fichiers originaux des features v1.0 sont disponibles dans:
- `../features/FEATURE-1-HSM-INIT.md`
- `../features/FEATURE-2-KEYPAIR-P256.md`
- `../features/FEATURE-3-DEK-IMPLEMENTATION.md`
- `../features/FEATURE-4-PAYLOAD-ENCRYPTION.md`

**Note**: Ces fichiers sont conservés pour référence historique mais ne doivent plus être utilisés pour le développement.

---

## Migration vers v2.0

Pour migrer vers la nouvelle architecture:

1. **Supprimer** l'ancien code dans AP_HSM.cpp (fonctions v1.0)
2. **Créer** les nouveaux fichiers:
   - KeyOrchestrator.h/.cpp
   - KeyExchangeProtocol.h/.cpp
   - DualDekEngine.h/.cpp
3. **Modifier** AP_Vehicle.cpp pour utiliser KeyOrchestrator
4. **Ajouter** les messages MAVLink custom

Voir documentation v2.0 dans `docs/hsm-project/`

---

**Ne pas modifier ces fichiers archivés.**
