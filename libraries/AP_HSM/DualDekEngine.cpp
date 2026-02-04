/*
 * DualDekEngine.cpp - MAVLink Payload Encryption/Decryption
 *
 * Feature 3: Transparent encryption using XChaCha20-Poly1305
 *
 * Date: 2026-01-25
 */

#include "DualDekEngine.h"
#include "KeyOrchestrator.h"
#include "KeyExchangeProtocol.h"
#include <AP_HAL/AP_HAL.h>
#include <AP_CheckFirmware/monocypher.h>
#include <string.h>

extern const AP_HAL::HAL& hal;

// Session 21: Disable verbose console output in SITL to avoid MAVLink stream corruption
#include "AP_HSM.h"
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
  #if AP_HSM_MOCK_ENABLED
    #define DDE_DEBUG(fmt, ...) do { /* disabled in SITL Mock */ } while(0)
  #else
    #define DDE_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
  #endif
#else
  #define DDE_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
#endif

// Singleton instance
DualDekEngine* DualDekEngine::_singleton = nullptr;

DualDekEngine::DualDekEngine()
{
    memset(&_stats, 0, sizeof(_stats));
}

bool DualDekEngine::init(KeyOrchestrator* ko, KeyExchangeProtocol* kep)
{
    if (ko == nullptr) {
        DDE_DEBUG("DDE: ERROR - KeyOrchestrator is null\n");
        return false;
    }

    _ko = ko;
    _kep = kep;  // Can be null initially

    // Check if we have our DEK ready
    if (_ko->get_my_dek() != nullptr) {
        _ready = true;
        DDE_DEBUG("DDE: Initialized - MY_DEK ready for encryption\n");
    } else {
        _ready = false;
        DDE_DEBUG("DDE: Initialized - waiting for DEK\n");
    }

    return true;
}

bool DualDekEngine::should_encrypt(uint32_t msgid) const
{
    // Messages that must stay in plaintext for discovery/handshake
    switch (msgid) {
        case MAVLINK_MSG_ID_HEARTBEAT:
        case MAVLINK_MSG_ID_HSM_WK_EXCHANGE:
        case MAVLINK_MSG_ID_HSM_DEK_EXCHANGE:
        case MAVLINK_MSG_ID_HSM_KEY_ACK:
            return false;
        default:
            return true;
    }
}

void DualDekEngine::generate_nonce(uint8_t nonce[DDE_NONCE_SIZE])
{
    // Use hardware RNG for nonce
    hal.util->get_random_vals(nonce, DDE_NONCE_SIZE);
}

bool DualDekEngine::encrypt_payload(const uint8_t* plaintext, size_t plaintext_len,
                                     uint8_t* ciphertext, size_t* ciphertext_len)
{
    if (!_ready || _ko == nullptr) {
        DDE_DEBUG("DDE: Cannot encrypt - not ready\n");
        return false;
    }

    const uint8_t* my_dek = _ko->get_my_dek();
    if (my_dek == nullptr) {
        DDE_DEBUG("DDE: Cannot encrypt - DEK not available\n");
        return false;
    }

    if (plaintext == nullptr || ciphertext == nullptr || ciphertext_len == nullptr) {
        return false;
    }

    if (plaintext_len > DDE_MAX_PAYLOAD) {
        DDE_DEBUG("DDE: Payload too large (%u > %d)\n",
                           (unsigned)plaintext_len, DDE_MAX_PAYLOAD);
        return false;
    }

    // Output format: [nonce:24][tag:16][ciphertext:N]
    uint8_t* nonce = ciphertext;
    uint8_t* tag = ciphertext + DDE_NONCE_SIZE;
    uint8_t* ct = ciphertext + DDE_HEADER_SIZE;

    // Generate random nonce
    generate_nonce(nonce);

    // Encrypt with XChaCha20-Poly1305 using Monocypher
    // crypto_lock(mac, cipher_text, key, nonce, plain_text, text_size)
    crypto_lock(tag, ct, my_dek, nonce, plaintext, plaintext_len);

    *ciphertext_len = DDE_HEADER_SIZE + plaintext_len;
    _stats.tx_encrypted++;

    return true;
}

bool DualDekEngine::decrypt_payload(uint8_t src_sysid,
                                     const uint8_t* ciphertext, size_t ciphertext_len,
                                     uint8_t* plaintext, size_t* plaintext_len)
{
    if (_kep == nullptr) {
        DDE_DEBUG("DDE: Cannot decrypt - KEP not available\n");
        _stats.rx_failed++;
        return false;
    }

    if (ciphertext == nullptr || plaintext == nullptr || plaintext_len == nullptr) {
        _stats.rx_failed++;
        return false;
    }

    if (ciphertext_len <= DDE_HEADER_SIZE) {
        DDE_DEBUG("DDE: Ciphertext too short (%u <= %d)\n",
                           (unsigned)ciphertext_len, DDE_HEADER_SIZE);
        _stats.rx_failed++;
        return false;
    }

    // Get peer's DEK
    const uint8_t* peer_dek = _kep->get_peer_dek(src_sysid, 0);  // compid=0 for any
    if (peer_dek == nullptr) {
        // No DEK for this peer - might be unencrypted message
        DDE_DEBUG("DDE: No DEK for sysid=%d\n", src_sysid);
        _stats.rx_failed++;
        return false;
    }

    // Parse encrypted format: [nonce:24][tag:16][ciphertext:N]
    const uint8_t* nonce = ciphertext;
    const uint8_t* tag = ciphertext + DDE_NONCE_SIZE;
    const uint8_t* ct = ciphertext + DDE_HEADER_SIZE;
    size_t ct_len = ciphertext_len - DDE_HEADER_SIZE;

    // Decrypt with XChaCha20-Poly1305 using Monocypher
    // crypto_unlock returns 0 on success, -1 on auth failure
    int result = crypto_unlock(plaintext, peer_dek, nonce, tag, ct, ct_len);

    if (result != 0) {
        DDE_DEBUG("DDE: Decryption failed - auth error (sysid=%d)\n", src_sysid);
        _stats.rx_failed++;
        return false;
    }

    *plaintext_len = ct_len;
    _stats.rx_decrypted++;

    return true;
}

void DualDekEngine::print_status()
{
    DDE_DEBUG("DDE: STATUS\n");
    DDE_DEBUG("DDE:   Ready: %s\n", _ready ? "YES" : "NO");
    DDE_DEBUG("DDE:   TX encrypted: %lu\n", (unsigned long)_stats.tx_encrypted);
    DDE_DEBUG("DDE:   TX plaintext: %lu\n", (unsigned long)_stats.tx_plaintext);
    DDE_DEBUG("DDE:   RX decrypted: %lu\n", (unsigned long)_stats.rx_decrypted);
    DDE_DEBUG("DDE:   RX failed:    %lu\n", (unsigned long)_stats.rx_failed);
    DDE_DEBUG("DDE:   RX plaintext: %lu\n", (unsigned long)_stats.rx_plaintext);
}
