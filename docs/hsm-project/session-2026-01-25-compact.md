# Session 2026-01-25 - Pixhawk Mock HSM Debug

## Objectif
Tester le Mock HSM sur Pixhawk5X et résoudre les problèmes de crash.

## Problèmes découverts et résolus

### 1. Crash `printf()` sur ARM
- **Cause:** `printf()` ne fonctionne pas sur ChibiOS (Pixhawk)
- **Solution:** Remplacé 107 occurrences de `printf()` par `hal.console->printf()` dans `KeyOrchestrator.cpp`
```bash
sed -i 's/printf("/hal.console->printf("/g' libraries/AP_HSM/KeyOrchestrator.cpp
```

### 2. Crash `uECC_compute_public_key()` sur ARM
- **Diagnostic:** Tests étape par étape:
  - RNG seul: ✅ OK
  - RNG + HKDF: ✅ OK
  - RNG + HKDF + uECC: ❌ CRASH
- **Cause:** micro-ecc P-256 crash sur Cortex-M7 (stack overflow probable)
- **Workaround temporaire:** WK_public généré par pseudo-PRNG (non cryptographique)

```cpp
// KeyOrchestrator.cpp - init_mission_keys()
// Pseudo-random WK_public (PAS crypto sécurisé, juste pour tester protocole)
for (int i = 0; i < WK_PUBLIC_SIZE; i++) {
    _wk_public[i] = _wk_private[i % KEY_SIZE] ^ (uint8_t)(i * 17 + 0x5A);
}
```

### 3. Boot delay ajouté
- `hsm_update()` attend 5 secondes après boot avant de démarrer l'init HSM
- Évite les problèmes de timing avec GCS_SEND_TEXT

## État actuel du code

### Fichiers modifiés
1. `libraries/AP_HSM/KeyOrchestrator.cpp`
   - printf → hal.console->printf
   - init_mission_keys() simplifié avec workaround uECC

2. `libraries/AP_Vehicle/AP_Vehicle.cpp`
   - hsm_update() avec boot delay 5s
   - Suppression des GCS_SEND_TEXT dans init path

3. `libraries/AP_HSM/AP_HSM.cpp`
   - Suppression du printf dans constructeur Mock

4. `libraries/AP_HSM/uECC.h`
   - Optimization level réduit à 1
   - Seul secp256r1 activé

### Résultats des tests
```
✅ Pixhawk stable (pas de crash)
✅ HEARTBEAT reçu
✅ RNG fonctionne
✅ HKDF fonctionne
✅ KeyOrchestrator génère MK + WK_priv + pseudo-WK_pub + DEK
✅ KEP initialisé
✅ Pixhawk reçoit WK_EXCHANGE du GCS
✅ Pixhawk envoie KEY_ACK (SUCCESS, WK_RECEIVED)
❌ Pixhawk WK_EXCHANGE response n'arrive pas au GCS
```

## Problème restant: WK_EXCHANGE response

### Symptôme
Le GCS envoie WK_EXCHANGE → Pixhawk répond KEY_ACK → Mais pas de WK_EXCHANGE en retour

### Code concerné
```cpp
// KeyExchangeProtocol.cpp handle_wk_exchange()
if (peer->state == State::IDLE || peer->state == State::WK_SENT) {
    send_wk_exchange(src_sysid, src_compid);  // ← Devrait envoyer
}
send_key_ack(...);  // ← Ceci fonctionne (reçu par GCS)
```

### Hypothèses
1. `send_wk_exchange()` échoue silencieusement
2. Message envoyé mais payload malformé (MAVLink v2 truncation)
3. GCS ne parse pas correctement UNKNOWN_12000

### À investiguer
- Vérifier que `GCS_MAVLINK::active_channel_mask()` retourne > 0
- Vérifier `_my_wk_public` n'est pas tout zéro
- Ajouter debug dans `mavlink_msg_hsm_wk_exchange_send()`

## Commandes utiles

```bash
# Compiler et flasher
./waf configure --board Pixhawk5X && ./waf copter
python3 Tools/scripts/uploader.py build/Pixhawk5X/bin/arducopter.apj

# Test GCS
python3 Tools/hsm/gcs_kep_client.py --no-hsm --mavlink /dev/ttyACM0 --timeout 60

# Monitor brut
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('/dev/ttyACM0', baud=115200)
conn.wait_heartbeat()
while True:
    msg = conn.recv_match(blocking=True, timeout=1)
    if msg and 'UNKNOWN' in msg.get_type():
        print(msg.get_type(), len(msg.get_payload()))
"
```

## Prochaines étapes

1. **Debug WK response** - Ajouter plus de logging dans send_wk_exchange()
2. **Fix uECC** - Options:
   - Augmenter stack size du scheduler task
   - Utiliser thread séparé pour ECC
   - Compiler micro-ecc avec options ARM spécifiques
3. **Test câble TELEM2** - Quand disponible, tester avec vrai HSM

## Notes techniques

- GPS/calibration n'affecte pas le HSM (question posée)
- Latence Mock HSM non importante (question posée) - on teste la logique, pas les délais
- BAD_DATA = messages chiffrés par DualDekEngine (normal)
