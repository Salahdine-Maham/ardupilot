# 📋 À FAIRE - Tâches Restantes Projet ArduPilot + HSM

**Date création**: 2026-01-23
**Priorité**: Par ordre d'importance

---

## 🔴 PRIORITÉ HAUTE (Bloquants Production)

### 1. ⏳ Résoudre Timeout WRITE BINARY HSM

**Problème:**
```
Après 10+ tests rapides, WRITE BINARY timeout systématique
HSM entre en état instable, ne répond plus aux commandes d'écriture
```

**Impact:**
- Feature 3 stockage DEK échoue (10% du projet)
- DEK non persistante entre reboots
- Re-négociation clé avec GCS nécessaire à chaque boot (+5-10s)

**Solutions Proposées:**
1. **Court terme:** Mode RAM-only (commenter store_dek_to_hsm)
2. **Moyen terme:** Retry logic avec backoff exponentiel
3. **Long terme:** Contact créateur HSM pour fix firmware

**Actions:**
- [x] Documenter problème complètement
- [x] Créer script simulation Python
- [ ] Contacter créateur HSM LeMonolith
- [ ] Tester avec délais encore plus longs (5-6s WRITE)
- [ ] Tester après repos HSM 24-48h
- [ ] Implémenter retry logic
- [ ] Envisager stockage SD card backup

**Assigné à:** En attente réponse créateur HSM
**Deadline:** Avant production

---

## 🟡 PRIORITÉ MOYENNE (Améliorations)

### 2. ⚙️ Implémenter Retry Logic pour WRITE

**Description:**
Ajouter logique de retry avec backoff exponentiel pour WRITE BINARY

**Code à implémenter:**
```cpp
bool AP_HSM::store_dek_with_retry(const uint8_t wrapped[32],
                                   const uint8_t tag[32]) {
    for (int retry = 0; retry < 3; retry++) {
        printf("HSM: Tentative WRITE %d/3...\n", retry + 1);

        if (store_dek_to_hsm(wrapped, tag)) {
            return true;
        }

        // Backoff: 2s, 4s, 8s
        uint32_t delay = 2000 * (1 << retry);
        printf("HSM: Pause %dms avant retry...\n", delay);
        hal.scheduler->delay(delay);
    }

    printf("HSM: Mode RAM-only activé\n");
    return false;
}
```

**Actions:**
- [ ] Implémenter dans AP_HSM.cpp
- [ ] Tester avec HSM frais
- [ ] Valider timeouts ajustés
- [ ] Documenter dans build_skill/

**Assigné à:** À faire
**Deadline:** Avant production

---

### 3. 🏥 Ajouter Health Check HSM

**Description:**
Détecter si HSM est en état stable avant opérations critiques

**Code à implémenter:**
```cpp
bool AP_HSM::hsm_is_healthy() {
    // Test rapide: READ offset 0x0000
    uint8_t test[4];
    uint32_t start = AP_HAL::millis();

    if (!read_from_hsm(0x0000, test, 4)) {
        return false;
    }

    uint32_t duration = AP_HAL::millis() - start;
    if (duration > 500) {  // Trop lent
        printf("HSM: ⚠️  Réponse lente (%dms)\n", duration);
        return false;
    }

    return true;
}
```

**Usage:**
```cpp
if (!hsm.hsm_is_healthy()) {
    printf("HSM: État instable, skip WRITE\n");
    return false;
}
```

**Actions:**
- [ ] Implémenter fonction health_check
- [ ] Appeler avant chaque WRITE
- [ ] Logger métriques santé HSM
- [ ] Ajouter dans documentation

**Assigné à:** À faire
**Deadline:** Avant production

---

### 4. 💾 Stockage Alternatif SD Card (Backup)

**Description:**
Si WRITE HSM échoue, fallback sur SD card

**Code à implémenter:**
```cpp
bool AP_HSM::store_dek_fallback(const uint8_t wrapped[32],
                                 const uint8_t tag[32]) {
    // Try HSM first
    if (hsm_is_healthy() && store_dek_to_hsm(wrapped, tag)) {
        printf("HSM: DEK stockée dans HSM\n");
        return true;
    }

    // Fallback SD
    #ifdef HAL_HAVE_SD_CARD
    if (store_dek_to_sd(wrapped, tag)) {
        printf("HSM: DEK stockée sur SD (fallback)\n");
        return true;
    }
    #endif

    // RAM-only mode
    printf("HSM: Mode RAM-only\n");
    return false;
}
```

**Actions:**
- [ ] Implémenter store/load SD
- [ ] Tester avec SD card
- [ ] Documenter trade-offs sécurité
- [ ] Ajouter option configuration

**Assigné à:** À faire
**Deadline:** Optionnel (production avancée)

---

### 5. 📊 Monitoring et Métriques HSM

**Description:**
Logger statistiques utilisation HSM pour debug

**Métriques à tracker:**
```cpp
struct HSM_Stats {
    uint32_t read_count;
    uint32_t write_count;
    uint32_t read_failures;
    uint32_t write_failures;
    uint32_t avg_read_time_ms;
    uint32_t avg_write_time_ms;
    uint32_t last_error_time;
};
```

**Actions:**
- [ ] Ajouter struct stats dans AP_HSM.h
- [ ] Logger chaque opération
- [ ] Exposer via MAVLink (messages custom)
- [ ] Dashboard monitoring

**Assigné à:** À faire
**Deadline:** Post-production

---

## 🟢 PRIORITÉ BASSE (Nice-to-Have)

### 6. 🔧 Améliorer Délais Inter-Tests

**Description:**
Ajouter pauses automatiques entre tests pour éviter HSM instable

**Scripts à modifier:**
```bash
# Dans test_feature123_final.sh
echo "Pause 10s pour récupération HSM..."
sleep 10

# Ajouter warning
echo "⚠️  Ne pas lancer >10 tests sans reset HSM"
```

**Actions:**
- [ ] Modifier tous scripts tests
- [ ] Ajouter compteur tests
- [ ] Warning après 10 tests
- [ ] Auto-reset suggestion

**Assigné à:** À faire
**Deadline:** Quand temps disponible

---

### 7. 📚 Compléter Documentation build_skill

**Description:**
Ajouter sections manquantes dans documentation

**À ajouter:**
- [ ] Section "Troubleshooting WRITE timeout" détaillée
- [ ] Flowchart décision mode stockage
- [ ] Comparaison timings différents HSM
- [ ] Guide update firmware HSM

**Actions:**
- [ ] Mettre à jour hsm_skills.md
- [ ] Ajouter FAQ
- [ ] Screenshots logs
- [ ] Vidéo demo (optionnel)

**Assigné à:** À faire
**Deadline:** Amélioration continue

---

### 8. 🧪 Tests Automatisés CI/CD

**Description:**
Scripts tests automatiques pour validation continue

**À créer:**
```bash
#!/bin/bash
# ci_test_hsm.sh

# 1. Build
./waf copter

# 2. Test Features 1-2-3
./test_feature123_final.sh

# 3. Parse résultats
if [ $? -eq 0 ]; then
    echo "✅ CI PASS"
    exit 0
else
    echo "❌ CI FAIL"
    exit 1
fi
```

**Actions:**
- [ ] Créer script CI
- [ ] Intégrer GitHub Actions
- [ ] Notifications échecs
- [ ] Badges README

**Assigné à:** À faire
**Deadline:** Optionnel

---

### 9. 🔐 Améliorer Sécurité Wrap/Unwrap

**Description:**
Remplacer XOR+HMAC par AES-GCM (standard production)

**Actuellement:**
```cpp
// XOR + HMAC (prototype)
wrapped[i] = dek[i] ^ wrapping_key[i];
hmac_sha256(wrapping_key, 32, wrapped, 32, tag);
```

**Production:**
```cpp
// AES-256-GCM (standard)
aes_gcm_encrypt(wrapping_key, 32, dek, 32, wrapped, tag);
```

**Actions:**
- [ ] Rechercher lib AES-GCM ArduPilot
- [ ] Si pas dispo, utiliser mbedTLS
- [ ] Implémenter wrap/unwrap GCM
- [ ] Tester compatibilité
- [ ] Documenter changement

**Assigné à:** À faire
**Deadline:** Avant production critique

---

### 10. 🚀 Feature 4: Encryption MAVLink

**Description:**
Chiffrement messages MAVLink avec ChaCha20-256

**Dépendances:**
- ✅ DEK disponible (en cache RAM)
- ✅ ChaCha20 existe (GCS_MAVLink/)
- ✅ Crypto validé (ECDH + HKDF)

**À implémenter:**
```cpp
// 1. Hook MAVLink send
void GCS_MAVLINK::send_message_encrypted(const mavlink_message_t* msg) {
    // Get DEK from HSM cache
    const uint8_t* dek = hsm.get_dek();

    // Encrypt with ChaCha20
    uint8_t encrypted[MAVLINK_MAX_PACKET_LEN];
    chacha20_encrypt(dek, msg->payload, encrypted, msg->len);

    // Send encrypted
    send_bytes(encrypted, msg->len);
}

// 2. Hook MAVLink receive
void GCS_MAVLINK::receive_message_encrypted(const uint8_t* data, uint16_t len) {
    // Get DEK
    const uint8_t* dek = hsm.get_dek();

    // Decrypt
    uint8_t decrypted[MAVLINK_MAX_PACKET_LEN];
    chacha20_decrypt(dek, data, decrypted, len);

    // Parse message
    mavlink_parse_char(chan, decrypted, &msg, &status);
}
```

**Actions:**
- [ ] Étudier GCS_MAVLink/
- [ ] Identifier hooks send/receive
- [ ] Implémenter encryption layer
- [ ] Tester avec GCS
- [ ] Documenter protocole
- [ ] Feature 4 complète

**Assigné à:** PRÊT À DÉMARRER
**Deadline:** Prochaine phase projet

---

## 📝 NOTES

### Dépendances

```
Feature 4 ← DEK (Feature 3 crypto ✅)
Feature 4 ← ChaCha20 (existe ✅)
Production ← Stockage HSM (À FAIRE ⏳)
Production ← Retry logic (À FAIRE ⏳)
Production ← Health check (À FAIRE ⏳)
```

### Risques

**Risque 1: HSM Hardware Défectueux**
- Probabilité: 20%
- Impact: ÉLEVÉ
- Mitigation: Contact créateur, test autre HSM

**Risque 2: Firmware HSM Bugué**
- Probabilité: 30%
- Impact: MOYEN
- Mitigation: Update firmware, workaround software

**Risque 3: Timing Incompatibilité ArduPilot**
- Probabilité: 40%
- Impact: FAIBLE
- Mitigation: Délais ajustés, mode RAM-only

**Risque 4: Aucune Solution WRITE**
- Probabilité: 10%
- Impact: FAIBLE (95% projet fonctionne)
- Mitigation: Accepter mode RAM-only permanent

---

## 🎯 PROCHAINES ACTIONS IMMÉDIATES

**Cette semaine:**
1. ✅ Contacter créateur HSM LeMonolith
2. [ ] Tester HSM après repos 24h
3. [ ] Implémenter mode RAM-only (commentaire store)
4. [ ] Démarrer Feature 4 (encryption MAVLink)

**Semaine prochaine:**
1. [ ] Analyser réponse créateur HSM
2. [ ] Implémenter retry logic si réponse positive
3. [ ] Tests Feature 4 basiques

**Mois prochain:**
1. [ ] Feature 4 complète
2. [ ] Tests intégration complète
3. [ ] Documentation finale
4. [ ] Préparation production

---

## 📊 PROGRESSION GLOBALE

**Complété:** 95%
```
✅ Feature 1: 100%
✅ Feature 2: 100%
✅ Feature 3 Crypto: 100%
⏳ Feature 3 Stockage: 10%
⏳ Feature 4: 0% (prêt à démarrer)
```

**Restant:** 5% + Feature 4
```
⏳ Fix WRITE HSM: Priorité haute
⏳ Retry logic: Priorité moyenne
⏳ Health check: Priorité moyenne
⚡ Feature 4: Nouveau développement
```

---

**Dernière mise à jour**: 2026-01-23 12:30
**Responsable**: Équipe ArduPilot+HSM
**Status global**: ✅ Sur les rails malgré limitation WRITE
