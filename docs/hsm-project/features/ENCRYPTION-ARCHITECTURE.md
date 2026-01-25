# 🔐 Encryption MAVLink - PAYLOAD SEULEMENT

## Approche Correcte

**TU AS RAISON:** On doit chiffrer **SEULEMENT le payload**, pas tout le message!

### Flux MAVLink
```
Message MAVLink envoyé en 4 parties:
1. Header    (10-12 bytes) → EN CLAIR (magic, length, msgid, etc.)
2. PAYLOAD   (0-255 bytes) → À CHIFFRER ✅
3. Checksum  (2 bytes)     → EN CLAIR (calculé sur données non-chiffrées)
4. Signature (13 bytes)    → EN CLAIR (optionnel)
```

### Problème Actuel
Mon code dans `comm_send_buffer()` chiffre **TOUT** comme un stream, ce qui:
- ❌ Chiffre le header → impossible de parser
- ❌ Chiffre le checksum → validation échoue
- ❌ Le récepteur ne peut rien lire

### Solution: Tracker le Buffer Index

**Idée:** `comm_send_buffer()` est appelé 3-4 fois par message:
- Appel #0: Header
- Appel #1: **PAYLOAD** ← Chiffrer ICI seulement!
- Appel #2: Checksum
- Appel #3: Signature (si signée)

**Implémentation:**
1. Dans `comm_send_lock()`: Reset compteur à 0
2. Dans `comm_send_buffer()`:
   - If (index == 1) → Chiffrer (c'est le payload)
   - Else → Envoyer en clair
   - Incrémenter index
3. Dans `comm_send_unlock()`: (rien à faire)

## Code à Modifier

### Fichier: libraries/GCS_MAVLink/GCS_MAVLink.cpp

```cpp
// Avant comm_send_buffer(), ajouter:
static uint8_t send_buffer_index[MAVLINK_COMM_NUM_BUFFERS] = {0};

// Dans comm_send_lock():
void comm_send_lock(mavlink_channel_t chan_m, uint16_t size)
{
    const uint8_t chan = uint8_t(chan_m);
    send_buffer_index[chan] = 0;  // ← AJOUTER: Reset index
    chan_locks[chan].take_blocking();
    // ... rest of function
}

// Dans comm_send_buffer():
void comm_send_buffer(mavlink_channel_t chan, const uint8_t *buf, uint8_t len)
{
    // ... checks ...

#if AP_HSM_ENABLED
    const uint8_t current_buffer = send_buffer_index[chan];
    const bool is_payload = (current_buffer == 1);  // Le 2ème buffer = payload

    if (gcs().mav_encrypt != 0 && is_payload) {
        // CHIFFRER payload avec ChaCha20-256
        uint8_t encrypted[len];
        // ... encryption code ...
        mavlink_comm_port[chan]->write(encrypted, len);
        send_buffer_index[chan]++;
        return;
    }
#endif

    // Envoi normal (header/checksum/signature)
    mavlink_comm_port[chan]->write(buf, len);
    send_buffer_index[chan]++;
}
```

### Fichier: libraries/GCS_MAVLink/GCS_Common.cpp

**Décryption:** Même approche - tracker l'index de réception et déchiffrer seulement le payload.

## Avantages
✅ Header lisible → Parser MAVLink fonctionne
✅ Checksum valide → Vérification intégrité OK
✅ Seulement données sensibles chiffrées
✅ Compatible avec outils MAVLink (peuvent lire header/type)

## Tests Nécessaires
1. Compiler avec nouveau code
2. Lancer avec sim_vehicle.py
3. Vérifier heartbeat visible côté MAVProxy (header en clair)
4. Vérifier payload chiffré dans les logs

---

**STATUS:** Code à corriger maintenant!
