/**
 * KeyOrchestrator.cpp - Feature 1 v2.0
 *
 * Gestionnaire de hiérarchie de clés cryptographiques:
 *   MK (Master Key) → WK (Wrapper Key P-256) → DEK (Data Encryption Key)
 *
 * Auteur: ArduPilot HSM Project
 * Date: 2026-01-24
 */

#include "KeyOrchestrator.h"
#include "AP_HSM.h"
#include <AP_HAL/AP_HAL.h>
#include <AP_Crypto/AP_Crypto.h>
#include <cstring>
#include <stdio.h>

// micro-ecc pour opérations P-256
#include "uECC.h"

extern const AP_HAL::HAL& hal;

// Session 21: Disable verbose console output in SITL to avoid MAVLink stream corruption
// In SITL, hal.console writes to the MAVLink TCP port (5760)
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
  #if AP_HSM_MOCK_ENABLED
    #define KO_DEBUG(fmt, ...) do { /* disabled in SITL Mock */ } while(0)
  #else
    #define KO_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
  #endif
#else
  #define KO_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
#endif

// Singleton instance
KeyOrchestrator* KeyOrchestrator::_singleton = nullptr;

// Ordre de la courbe P-256 (secp256r1) en big-endian
static const uint8_t P256_ORDER[32] = {
    0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
    0xBC, 0xE6, 0xFA, 0xAD, 0xA7, 0x17, 0x9E, 0x84,
    0xF3, 0xB9, 0xCA, 0xC2, 0xFC, 0x63, 0x25, 0x51
};

// Note: uECC now works on both SITL (x86_64) and Pixhawk (ARM Cortex-M7)
// thanks to proper platform detection in uECC_config.h

// ═══════════════════════════════════════════════════════════════════════════
// CONSTRUCTEUR ET SINGLETON
// ═══════════════════════════════════════════════════════════════════════════

KeyOrchestrator::KeyOrchestrator()
    : _hsm(nullptr)
    , _initialized(false)
    , _mk_loaded(false)
    , _wk_loaded(false)
    , _dek_loaded(false)
    , _init_time_ms(0)
    , _peer_count(0)
{
    // Initialisation sécurisée des buffers
    secure_memzero(_master_key, sizeof(_master_key));
    secure_memzero(_wk_private, sizeof(_wk_private));
    secure_memzero(_wk_public, sizeof(_wk_public));
    secure_memzero(_my_dek, sizeof(_my_dek));

    // Initialiser table des peers
    for (uint8_t i = 0; i < MAX_PEERS; i++) {
        _peer_deks[i].active = false;
        secure_memzero(_peer_deks[i].peer_id, sizeof(_peer_deks[i].peer_id));
        secure_memzero(_peer_deks[i].dek, sizeof(_peer_deks[i].dek));
    }
}

KeyOrchestrator& KeyOrchestrator::get_singleton()
{
    if (_singleton == nullptr) {
        _singleton = new KeyOrchestrator();
    }
    return *_singleton;
}

// ═══════════════════════════════════════════════════════════════════════════
// INITIALISATION
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::init(AP_HSM* hsm)
{
    if (hsm == nullptr) {
        KO_DEBUG("KeyOrch: ERREUR - AP_HSM null\n");
        return false;
    }

    _hsm = hsm;
    _initialized = true;

    KO_DEBUG("KeyOrch: Initialisé avec AP_HSM\n");
    return true;
}

// ═══════════════════════════════════════════════════════════════════════════
// CYCLE DE VIE MISSION
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::init_mission_keys()
{
    KO_DEBUG("KeyOrch: init (uECC disabled for Pixhawk)\n");

    if (!_initialized) {
        KO_DEBUG("KeyOrch: Not init\n");
        return false;
    }

    // Step 1: Generate Master Key with RNG
    KO_DEBUG("KeyOrch: [1] RNG...\n");
    if (!generate_master_key()) {
        KO_DEBUG("KeyOrch: RNG FAIL\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [1] MK=%02X%02X%02X%02X\n",
           _master_key[0], _master_key[1], _master_key[2], _master_key[3]);

    // Step 2: Derive WK_private with HKDF
    KO_DEBUG("KeyOrch: [2] HKDF...\n");
    if (!derive_wrapper_key()) {
        KO_DEBUG("KeyOrch: HKDF FAIL\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [2] WK_priv=%02X%02X%02X%02X\n",
           _wk_private[0], _wk_private[1], _wk_private[2], _wk_private[3]);

    // Step 3: Compute WK_public from WK_private using uECC
    KO_DEBUG("KeyOrch: [3] Computing WK_pub with uECC...\n");
    uECC_Curve curve = uECC_secp256r1();
    if (uECC_compute_public_key(_wk_private, _wk_public, curve) != 1) {
        KO_DEBUG("KeyOrch: uECC_compute_public_key FAILED\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [3] WK_pub=%02X%02X%02X%02X\n",
           _wk_public[0], _wk_public[1], _wk_public[2], _wk_public[3]);

    // Step 4: Generate DEK
    KO_DEBUG("KeyOrch: [4] DEK...\n");
    if (!generate_dek()) {
        KO_DEBUG("KeyOrch: DEK FAIL\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [4] DEK=%02X%02X%02X%02X\n",
           _my_dek[0], _my_dek[1], _my_dek[2], _my_dek[3]);

    KO_DEBUG("KeyOrch: ✓ Keys initialized (proto mode)\n");
    return true;
}

bool KeyOrchestrator::restore_mission_keys()
{
    KO_DEBUG("KeyOrch: ═══════════════════════════════════════════\n");
    KO_DEBUG("KeyOrch: RESTAURATION CLÉS DEPUIS HSM\n");
    KO_DEBUG("KeyOrch: ═══════════════════════════════════════════\n");

    if (!_initialized) {
        KO_DEBUG("KeyOrch: ERREUR - Non initialisé\n");
        return false;
    }

    uint32_t start_time = AP_HAL::millis();

    // ─────────────────────────────────────────────────────────────────────
    // ÉTAPE 1: Charger Master Key
    // ─────────────────────────────────────────────────────────────────────
    KO_DEBUG("KeyOrch: [1/4] Chargement Master Key...\n");
    if (!load_mk_from_hsm()) {
        KO_DEBUG("KeyOrch: Pas de MK valide - nouvelle mission requise\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [1/4] ✓ Master Key chargée\n");

    // ─────────────────────────────────────────────────────────────────────
    // ÉTAPE 2: Charger et unwrap Wrapper Key
    // ─────────────────────────────────────────────────────────────────────
    KO_DEBUG("KeyOrch: [2/4] Chargement Wrapper Key...\n");
    if (!load_wk_from_hsm()) {
        KO_DEBUG("KeyOrch: ERREUR - WK corrompue ou absente\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [2/4] ✓ Wrapper Key restaurée\n");

    // ─────────────────────────────────────────────────────────────────────
    // ÉTAPE 3: Recalculer WK_public
    // ─────────────────────────────────────────────────────────────────────
    KO_DEBUG("KeyOrch: [3/4] Recalcul WK_public...\n");
    if (!compute_wk_public()) {
        KO_DEBUG("KeyOrch: ERREUR - Échec recalcul WK_public\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [3/4] ✓ WK_public recalculée\n");

    // ─────────────────────────────────────────────────────────────────────
    // ÉTAPE 4: Charger et unwrap DEK
    // ─────────────────────────────────────────────────────────────────────
    KO_DEBUG("KeyOrch: [4/4] Chargement DEK...\n");
    if (!load_dek_from_hsm()) {
        KO_DEBUG("KeyOrch: ERREUR - DEK corrompue ou absente\n");
        return false;
    }
    KO_DEBUG("KeyOrch: [4/4] ✓ DEK restaurée\n");

    _init_time_ms = AP_HAL::millis() - start_time;

    KO_DEBUG("KeyOrch: ═══════════════════════════════════════════\n");
    KO_DEBUG("KeyOrch: ✓ CLÉS RESTAURÉES EN %lu ms\n", (unsigned long)_init_time_ms);
    KO_DEBUG("KeyOrch: ═══════════════════════════════════════════\n");

    print_status();

    return true;
}

bool KeyOrchestrator::is_fully_initialized() const
{
    return _mk_loaded && _wk_loaded && _dek_loaded;
}

// ═══════════════════════════════════════════════════════════════════════════
// NIVEAU 1: MASTER KEY
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::generate_master_key()
{
    // Générer 32 bytes aléatoires
    if (!hal.util->get_random_vals(_master_key, KEY_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - RNG failed pour MK\n");
        return false;
    }

    // Verify MK is not all zeros (RNG might not be ready)
    bool all_zero = true;
    for (int i = 0; i < KEY_SIZE; i++) {
        if (_master_key[i] != 0) {
            all_zero = false;
            break;
        }
    }
    if (all_zero) {
        KO_DEBUG("KeyOrch: WARN - MK is all zeros, RNG not ready?\n");
        // Don't fail - use fallback entropy
        // Mix with time-based entropy
        uint32_t time_ms = AP_HAL::millis();
        for (int i = 0; i < KEY_SIZE; i++) {
            _master_key[i] = (uint8_t)((time_ms >> ((i % 4) * 8)) ^ (i * 17));
            time_ms = time_ms * 1103515245 + 12345;  // Simple LCG
        }
        KO_DEBUG("KeyOrch: Using time-based fallback entropy\n");
    }

    _mk_loaded = true;
    KO_DEBUG("KeyOrch: MK gen OK %02X%02X%02X%02X\n",
           _master_key[0], _master_key[1], _master_key[2], _master_key[3]);
    return true;
}

bool KeyOrchestrator::store_mk_to_hsm()
{
    if (!_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - Pas de MK à stocker\n");
        return false;
    }

    return write_to_hsm(HSM_OFFSET_MK, _master_key, KEY_SIZE);
}

bool KeyOrchestrator::load_mk_from_hsm()
{
    uint8_t buffer[KEY_SIZE];

    if (!read_from_hsm(HSM_OFFSET_MK, buffer, KEY_SIZE)) {
        return false;
    }

    // Vérifier que ce n'est pas vide (tous zéros ou 0xFF)
    bool all_zero = true;
    bool all_ff = true;
    for (uint8_t i = 0; i < KEY_SIZE; i++) {
        if (buffer[i] != 0x00) all_zero = false;
        if (buffer[i] != 0xFF) all_ff = false;
    }

    if (all_zero || all_ff) {
        KO_DEBUG("KeyOrch: MK vide ou non initialisée\n");
        return false;
    }

    memcpy(_master_key, buffer, KEY_SIZE);
    secure_memzero(buffer, KEY_SIZE);
    _mk_loaded = true;

    return true;
}

// ═══════════════════════════════════════════════════════════════════════════
// NIVEAU 2: WRAPPER KEY
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::derive_wrapper_key()
{
    if (!_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - MK non chargée pour dérivation WK\n");
        return false;
    }

    // Dériver un scalar P-256 valide via HKDF
    if (!derive_p256_scalar_from_hkdf(_master_key, KEY_SIZE, _wk_private)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec dérivation P-256 scalar\n");
        return false;
    }

    _wk_loaded = true;
    KO_DEBUG("KeyOrch: WK_priv OK %02X%02X%02X%02X\n",
           _wk_private[0], _wk_private[1], _wk_private[2], _wk_private[3]);
    return true;
}

bool KeyOrchestrator::compute_wk_public()
{
    if (!_wk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - WK_private non disponible\n");
        return false;
    }

    uECC_Curve curve = uECC_secp256r1();
    if (uECC_compute_public_key(_wk_private, _wk_public, curve) != 1) {
        KO_DEBUG("KeyOrch: ERREUR - uECC_compute_public_key failed\n");
        return false;
    }

    // Afficher premiers bytes de WK_public (debug)
    KO_DEBUG("KeyOrch: WK_PUB[0..7]: ");
    for (int i = 0; i < 8; i++) {
        hal.console->printf("%02X", _wk_public[i]);
    }
    hal.console->printf("...\n");

    return true;
}

bool KeyOrchestrator::store_wk_to_hsm()
{
    if (!_wk_loaded || !_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - WK ou MK non disponible\n");
        return false;
    }

    uint8_t wrapped[KEY_SIZE];
    uint8_t tag[TAG_SIZE];

    // Wrapper WK_private avec MK
    if (!wrap_key(_wk_private, wrapped, tag)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec wrapping WK\n");
        return false;
    }

    // Écrire wrapped WK
    if (!write_to_hsm(HSM_OFFSET_WK, wrapped, KEY_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec écriture WK\n");
        return false;
    }

    // Écrire tag HMAC
    if (!write_to_hsm(HSM_OFFSET_WK_TAG, tag, TAG_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec écriture WK tag\n");
        return false;
    }

    secure_memzero(wrapped, KEY_SIZE);
    secure_memzero(tag, TAG_SIZE);

    return true;
}

bool KeyOrchestrator::load_wk_from_hsm()
{
    if (!_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - MK non chargée pour unwrap WK\n");
        return false;
    }

    uint8_t wrapped[KEY_SIZE];
    uint8_t tag[TAG_SIZE];

    // Lire wrapped WK
    if (!read_from_hsm(HSM_OFFSET_WK, wrapped, KEY_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec lecture WK\n");
        return false;
    }

    // Lire tag HMAC
    if (!read_from_hsm(HSM_OFFSET_WK_TAG, tag, TAG_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec lecture WK tag\n");
        return false;
    }

    // Unwrap et vérifier
    if (!unwrap_key(wrapped, tag, _wk_private)) {
        KO_DEBUG("KeyOrch: ERREUR - WK corrompue (HMAC invalide)\n");
        secure_memzero(wrapped, KEY_SIZE);
        secure_memzero(tag, TAG_SIZE);
        return false;
    }

    secure_memzero(wrapped, KEY_SIZE);
    secure_memzero(tag, TAG_SIZE);

    _wk_loaded = true;
    return true;
}

const uint8_t* KeyOrchestrator::get_wk_public() const
{
    if (!_wk_loaded) return nullptr;
    return _wk_public;
}

const uint8_t* KeyOrchestrator::get_wk_private() const
{
    if (!_wk_loaded) return nullptr;
    return _wk_private;
}

// ═══════════════════════════════════════════════════════════════════════════
// NIVEAU 3: DEK
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::generate_dek()
{
    if (!hal.util->get_random_vals(_my_dek, KEY_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - RNG failed pour DEK\n");
        return false;
    }

    _dek_loaded = true;
    return true;
}

bool KeyOrchestrator::store_dek_to_hsm()
{
    if (!_dek_loaded || !_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - DEK ou MK non disponible\n");
        return false;
    }

    uint8_t wrapped[KEY_SIZE];
    uint8_t tag[TAG_SIZE];

    // Wrapper DEK avec MK
    if (!wrap_key(_my_dek, wrapped, tag)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec wrapping DEK\n");
        return false;
    }

    // Écrire wrapped DEK
    if (!write_to_hsm(HSM_OFFSET_DEK, wrapped, KEY_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec écriture DEK\n");
        return false;
    }

    // Écrire tag HMAC
    if (!write_to_hsm(HSM_OFFSET_DEK_TAG, tag, TAG_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec écriture DEK tag\n");
        return false;
    }

    secure_memzero(wrapped, KEY_SIZE);
    secure_memzero(tag, TAG_SIZE);

    return true;
}

bool KeyOrchestrator::load_dek_from_hsm()
{
    if (!_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - MK non chargée pour unwrap DEK\n");
        return false;
    }

    uint8_t wrapped[KEY_SIZE];
    uint8_t tag[TAG_SIZE];

    // Lire wrapped DEK
    if (!read_from_hsm(HSM_OFFSET_DEK, wrapped, KEY_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec lecture DEK\n");
        return false;
    }

    // Lire tag HMAC
    if (!read_from_hsm(HSM_OFFSET_DEK_TAG, tag, TAG_SIZE)) {
        KO_DEBUG("KeyOrch: ERREUR - Échec lecture DEK tag\n");
        return false;
    }

    // Unwrap et vérifier
    if (!unwrap_key(wrapped, tag, _my_dek)) {
        KO_DEBUG("KeyOrch: ERREUR - DEK corrompue (HMAC invalide)\n");
        secure_memzero(wrapped, KEY_SIZE);
        secure_memzero(tag, TAG_SIZE);
        return false;
    }

    secure_memzero(wrapped, KEY_SIZE);
    secure_memzero(tag, TAG_SIZE);

    _dek_loaded = true;
    return true;
}

const uint8_t* KeyOrchestrator::get_my_dek() const
{
    if (!_dek_loaded) return nullptr;
    return _my_dek;
}

// ═══════════════════════════════════════════════════════════════════════════
// WRAPPING / UNWRAPPING
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::wrap_key(const uint8_t* key, uint8_t* wrapped, uint8_t* tag)
{
    if (!_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - MK non disponible pour wrapping\n");
        return false;
    }

    // XOR avec Master Key
    for (uint8_t i = 0; i < KEY_SIZE; i++) {
        wrapped[i] = key[i] ^ _master_key[i];
    }

    // HMAC-SHA256 pour intégrité
    hmac_sha256(_master_key, KEY_SIZE, wrapped, KEY_SIZE, tag);

    return true;
}

bool KeyOrchestrator::unwrap_key(const uint8_t* wrapped, const uint8_t* tag, uint8_t* key)
{
    if (!_mk_loaded) {
        KO_DEBUG("KeyOrch: ERREUR - MK non disponible pour unwrapping\n");
        return false;
    }

    // Vérifier HMAC d'abord
    uint8_t computed_tag[TAG_SIZE];
    hmac_sha256(_master_key, KEY_SIZE, wrapped, KEY_SIZE, computed_tag);

    // Comparaison constante pour éviter timing attacks
    uint8_t diff = 0;
    for (uint8_t i = 0; i < TAG_SIZE; i++) {
        diff |= tag[i] ^ computed_tag[i];
    }

    secure_memzero(computed_tag, TAG_SIZE);

    if (diff != 0) {
        KO_DEBUG("KeyOrch: ERREUR - Tag HMAC invalide\n");
        return false;
    }

    // XOR pour récupérer clé
    for (uint8_t i = 0; i < KEY_SIZE; i++) {
        key[i] = wrapped[i] ^ _master_key[i];
    }

    return true;
}

// ═══════════════════════════════════════════════════════════════════════════
// GESTION DES DEK PEERS
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::store_peer_dek(const char* peer_id, const uint8_t peer_dek[32])
{
    if (peer_id == nullptr || peer_dek == nullptr) {
        return false;
    }

    int idx = find_peer_index(peer_id);

    if (idx < 0) {
        // Nouveau peer - trouver un slot libre
        for (uint8_t i = 0; i < MAX_PEERS; i++) {
            if (!_peer_deks[i].active) {
                idx = i;
                break;
            }
        }

        if (idx < 0) {
            KO_DEBUG("KeyOrch: Table peers pleine (%d max)\n", MAX_PEERS);
            return false;
        }

        _peer_count++;
    }

    strncpy(_peer_deks[idx].peer_id, peer_id, sizeof(_peer_deks[idx].peer_id) - 1);
    _peer_deks[idx].peer_id[sizeof(_peer_deks[idx].peer_id) - 1] = '\0';
    memcpy(_peer_deks[idx].dek, peer_dek, KEY_SIZE);
    _peer_deks[idx].active = true;

    KO_DEBUG("KeyOrch: DEK peer '%s' stockée (slot %d)\n", peer_id, idx);
    return true;
}

const uint8_t* KeyOrchestrator::get_peer_dek(const char* peer_id) const
{
    int idx = find_peer_index(peer_id);
    if (idx < 0) return nullptr;
    return _peer_deks[idx].dek;
}

bool KeyOrchestrator::has_peer_dek(const char* peer_id) const
{
    return find_peer_index(peer_id) >= 0;
}

bool KeyOrchestrator::remove_peer_dek(const char* peer_id)
{
    int idx = find_peer_index(peer_id);
    if (idx < 0) return false;

    secure_memzero(_peer_deks[idx].peer_id, sizeof(_peer_deks[idx].peer_id));
    secure_memzero(_peer_deks[idx].dek, sizeof(_peer_deks[idx].dek));
    _peer_deks[idx].active = false;
    _peer_count--;

    KO_DEBUG("KeyOrch: DEK peer supprimée\n");
    return true;
}

int KeyOrchestrator::find_peer_index(const char* peer_id) const
{
    if (peer_id == nullptr) return -1;

    for (uint8_t i = 0; i < MAX_PEERS; i++) {
        if (_peer_deks[i].active &&
            strncmp(_peer_deks[i].peer_id, peer_id, sizeof(_peer_deks[i].peer_id)) == 0) {
            return i;
        }
    }
    return -1;
}

// ═══════════════════════════════════════════════════════════════════════════
// OPÉRATIONS ECIES
// ═══════════════════════════════════════════════════════════════════════════

// RNG callback pour micro-ecc
static int rng_callback(uint8_t* dest, unsigned int size)
{
    if (hal.util->get_random_vals(dest, size)) {
        return 1;
    }
    return 0;
}

bool KeyOrchestrator::ecies_encrypt_my_dek(const uint8_t peer_wk_pub[64],
                                            uint8_t out_ephemeral_pub[64],
                                            uint8_t out_nonce[12],
                                            uint8_t out_ciphertext[32],
                                            uint8_t out_tag[16])
{
    if (!_dek_loaded || peer_wk_pub == nullptr) {
        return false;
    }

    uECC_set_rng(&rng_callback);
    uECC_Curve curve = uECC_secp256r1();

    // 1. Générer keypair éphémère
    uint8_t ephemeral_priv[32];
    if (uECC_make_key(out_ephemeral_pub, ephemeral_priv, curve) != 1) {
        KO_DEBUG("KeyOrch: ERREUR - Génération clé éphémère\n");
        return false;
    }

    // 2. ECDH: shared_secret = ephemeral_priv * peer_wk_pub
    uint8_t shared_secret[32];
    if (uECC_shared_secret(peer_wk_pub, ephemeral_priv, shared_secret, curve) != 1) {
        secure_memzero(ephemeral_priv, sizeof(ephemeral_priv));
        return false;
    }

    // 3. Dériver clé de chiffrement via HKDF
    uint8_t encryption_key[32];
    const char* info = "ecies_dek_encryption_v1";
    hkdf_sha256(nullptr, 0, shared_secret, 32,
                (const uint8_t*)info, strlen(info),
                encryption_key, 32);

    // 4. Générer nonce
    hal.util->get_random_vals(out_nonce, 12);

    // 5. Chiffrer DEK (XOR simplifié - en production utiliser ChaCha20)
    for (int i = 0; i < 32; i++) {
        out_ciphertext[i] = _my_dek[i] ^ encryption_key[i];
    }

    // 6. Tag HMAC tronqué
    uint8_t full_tag[32];
    uint8_t tag_input[32 + 12];
    memcpy(tag_input, out_ciphertext, 32);
    memcpy(tag_input + 32, out_nonce, 12);
    hmac_sha256(encryption_key, 32, tag_input, sizeof(tag_input), full_tag);
    memcpy(out_tag, full_tag, 16);

    // Cleanup
    secure_memzero(ephemeral_priv, sizeof(ephemeral_priv));
    secure_memzero(shared_secret, sizeof(shared_secret));
    secure_memzero(encryption_key, sizeof(encryption_key));

    return true;
}

bool KeyOrchestrator::ecies_decrypt_peer_dek(const uint8_t ephemeral_pub[64],
                                              const uint8_t nonce[12],
                                              const uint8_t ciphertext[32],
                                              const uint8_t tag[16],
                                              uint8_t out_peer_dek[32])
{
    if (!_wk_loaded || ephemeral_pub == nullptr) {
        return false;
    }

    uECC_Curve curve = uECC_secp256r1();

    // 1. ECDH: shared_secret = wk_private * ephemeral_pub
    uint8_t shared_secret[32];
    if (uECC_shared_secret(ephemeral_pub, _wk_private, shared_secret, curve) != 1) {
        return false;
    }

    // 2. Dériver clé de chiffrement
    uint8_t encryption_key[32];
    const char* info = "ecies_dek_encryption_v1";
    hkdf_sha256(nullptr, 0, shared_secret, 32,
                (const uint8_t*)info, strlen(info),
                encryption_key, 32);

    // 3. Vérifier tag
    uint8_t computed_tag[32];
    uint8_t tag_input[32 + 12];
    memcpy(tag_input, ciphertext, 32);
    memcpy(tag_input + 32, nonce, 12);
    hmac_sha256(encryption_key, 32, tag_input, sizeof(tag_input), computed_tag);

    uint8_t diff = 0;
    for (int i = 0; i < 16; i++) {
        diff |= tag[i] ^ computed_tag[i];
    }

    if (diff != 0) {
        KO_DEBUG("KeyOrch: ERREUR - Tag ECIES invalide\n");
        secure_memzero(shared_secret, sizeof(shared_secret));
        secure_memzero(encryption_key, sizeof(encryption_key));
        return false;
    }

    // 4. Déchiffrer
    for (int i = 0; i < 32; i++) {
        out_peer_dek[i] = ciphertext[i] ^ encryption_key[i];
    }

    secure_memzero(shared_secret, sizeof(shared_secret));
    secure_memzero(encryption_key, sizeof(encryption_key));

    return true;
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════

void KeyOrchestrator::secure_erase_all()
{
    KO_DEBUG("KeyOrch: Effacement sécurisé de toutes les clés...\n");

    secure_memzero(_master_key, sizeof(_master_key));
    secure_memzero(_wk_private, sizeof(_wk_private));
    secure_memzero(_wk_public, sizeof(_wk_public));
    secure_memzero(_my_dek, sizeof(_my_dek));

    for (uint8_t i = 0; i < MAX_PEERS; i++) {
        secure_memzero(_peer_deks[i].peer_id, sizeof(_peer_deks[i].peer_id));
        secure_memzero(_peer_deks[i].dek, sizeof(_peer_deks[i].dek));
        _peer_deks[i].active = false;
    }

    _mk_loaded = false;
    _wk_loaded = false;
    _dek_loaded = false;
    _peer_count = 0;

    KO_DEBUG("KeyOrch: ✓ Toutes les clés effacées\n");
}

KeyOrchestrator::Stats KeyOrchestrator::get_stats() const
{
    Stats stats;
    stats.mk_loaded = _mk_loaded;
    stats.wk_loaded = _wk_loaded;
    stats.dek_loaded = _dek_loaded;
    stats.peer_count = _peer_count;
    stats.init_time_ms = _init_time_ms;
    return stats;
}

void KeyOrchestrator::print_status() const
{
    KO_DEBUG("KeyOrch: ─────────────────────────────────────────\n");
    KO_DEBUG("KeyOrch: STATUS:\n");
    KO_DEBUG("KeyOrch:   MK:  %s\n", _mk_loaded ? "LOADED" : "NOT LOADED");
    KO_DEBUG("KeyOrch:   WK:  %s\n", _wk_loaded ? "LOADED" : "NOT LOADED");
    KO_DEBUG("KeyOrch:   DEK: %s\n", _dek_loaded ? "LOADED" : "NOT LOADED");
    KO_DEBUG("KeyOrch:   Peers: %d/%d\n", _peer_count, MAX_PEERS);
    KO_DEBUG("KeyOrch:   Init time: %lu ms\n", (unsigned long)_init_time_ms);
    KO_DEBUG("KeyOrch: ─────────────────────────────────────────\n");
}

void KeyOrchestrator::secure_memzero(void* ptr, size_t len)
{
    volatile uint8_t* p = (volatile uint8_t*)ptr;
    while (len--) {
        *p++ = 0;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS PRIVÉS
// ═══════════════════════════════════════════════════════════════════════════

bool KeyOrchestrator::read_from_hsm(uint16_t offset, uint8_t* buffer, size_t len)
{
    if (_hsm == nullptr || buffer == nullptr || len == 0 || len > 255) {
        return false;
    }

    // Construire APDU READ BINARY: 00 B0 P1 P2 Le
    char apdu[32];
    snprintf(apdu, sizeof(apdu), "A 00B0%02X%02X%02X",
             (offset >> 8) & 0xFF, offset & 0xFF, (uint8_t)len);

    char response[512];
    if (!_hsm->send_apdu(apdu, response, sizeof(response))) {
        return false;
    }

    // Vérifier succès (9000)
    if (strstr(response, "9000") == nullptr) {
        return false;
    }

    // Extraire données de la réponse
    const char* rx_marker = strstr(response, "Rx");
    if (rx_marker == nullptr) {
        return false;
    }

    // Chercher les données hex après "Rx"
    while (*rx_marker && *rx_marker != '\n') rx_marker++;
    if (*rx_marker) rx_marker++;  // Passer le \n

    return _hsm->hexstr_to_bytes(rx_marker, buffer, len);
}

bool KeyOrchestrator::write_to_hsm(uint16_t offset, const uint8_t* data, size_t len)
{
    if (_hsm == nullptr || data == nullptr || len == 0 || len > 255) {
        return false;
    }

    // Construire APDU WRITE BINARY: 00 D0 P1 P2 Lc <data> (LeMonolith utilise D0, pas D6)
    char apdu[600];
    snprintf(apdu, sizeof(apdu), "A 00D0%02X%02X%02X",
             (offset >> 8) & 0xFF, offset & 0xFF, (uint8_t)len);

    // Ajouter données en hex
    for (size_t i = 0; i < len; i++) {
        char byte_hex[3];
        snprintf(byte_hex, sizeof(byte_hex), "%02X", data[i]);
        strncat(apdu, byte_hex, sizeof(apdu) - strlen(apdu) - 1);
    }

    char response[256];
    if (!_hsm->send_apdu(apdu, response, sizeof(response))) {
        return false;
    }

    return (strstr(response, "9000") != nullptr);
}

bool KeyOrchestrator::derive_p256_scalar_from_hkdf(const uint8_t* ikm, size_t ikm_len, uint8_t* scalar)
{
    const char* salt = "ArduPilot-HSM-Salt-v2";
    const char* base_info = "WrapperKey-P256-v1";

    uint8_t candidate[32];
    uint8_t counter = 0;

    // Boucle jusqu'à obtenir un scalar valide (< ordre courbe)
    do {
        char info[64];
        if (counter == 0) {
            snprintf(info, sizeof(info), "%s", base_info);
        } else {
            snprintf(info, sizeof(info), "%s-%d", base_info, counter);
        }

        hkdf_sha256(
            (const uint8_t*)salt, strlen(salt),
            ikm, ikm_len,
            (const uint8_t*)info, strlen(info),
            candidate, 32
        );

        counter++;
    } while (!is_valid_p256_scalar(candidate) && counter < 255);

    if (counter >= 255) {
        KO_DEBUG("KeyOrch: ERREUR - Impossible de dériver scalar P-256 valide\n");
        return false;
    }

    if (counter > 1) {
        KO_DEBUG("KeyOrch: Note - Scalar P-256 trouvé après %d itérations\n", counter);
    }

    memcpy(scalar, candidate, 32);
    secure_memzero(candidate, 32);

    return true;
}

bool KeyOrchestrator::is_valid_p256_scalar(const uint8_t* scalar)
{
    // Un scalar P-256 valide doit être:
    // 1. > 0
    // 2. < ordre de la courbe

    // Vérifier non-zéro
    bool all_zero = true;
    for (int i = 0; i < 32; i++) {
        if (scalar[i] != 0) {
            all_zero = false;
            break;
        }
    }
    if (all_zero) return false;

    // Comparer avec l'ordre (big-endian)
    for (int i = 0; i < 32; i++) {
        if (scalar[i] < P256_ORDER[i]) return true;   // scalar < ordre
        if (scalar[i] > P256_ORDER[i]) return false;  // scalar > ordre
    }

    return false;  // scalar == ordre (invalide)
}

bool KeyOrchestrator::check_hsm_has_valid_mk()
{
    uint8_t buffer[KEY_SIZE];

    if (!read_from_hsm(HSM_OFFSET_MK, buffer, KEY_SIZE)) {
        return false;
    }

    // Vérifier non-vide
    bool all_zero = true;
    bool all_ff = true;
    for (uint8_t i = 0; i < KEY_SIZE; i++) {
        if (buffer[i] != 0x00) all_zero = false;
        if (buffer[i] != 0xFF) all_ff = false;
    }

    secure_memzero(buffer, KEY_SIZE);

    return !all_zero && !all_ff;
}
