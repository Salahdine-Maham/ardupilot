/*
 * DualDekEngine.h - MAVLink Payload Encryption/Decryption
 *
 * Feature 3: Transparent encryption of MAVLink payloads using:
 * - MY_DEK for encrypting outgoing messages
 * - PEER_DEKs for decrypting incoming messages
 *
 * Uses XChaCha20-Poly1305 (Monocypher) for AEAD encryption.
 *
 * Date: 2026-01-25
 */

#pragma once

#include <AP_HAL/AP_HAL.h>
#include <stdint.h>

// Forward declarations
class KeyOrchestrator;
class KeyExchangeProtocol;

// Crypto constants
#define DDE_KEY_SIZE    32
#define DDE_NONCE_SIZE  24   // XChaCha20-Poly1305
#define DDE_TAG_SIZE    16   // Poly1305 tag
#define DDE_MAX_PAYLOAD 255  // Max MAVLink payload size

// Encrypted message header (prepended to ciphertext)
// Format: [nonce:24][tag:16][ciphertext:N]
#define DDE_HEADER_SIZE (DDE_NONCE_SIZE + DDE_TAG_SIZE)

// Message IDs that should NOT be encrypted (discovery/handshake)
#define MAVLINK_MSG_ID_HEARTBEAT        0
#define MAVLINK_MSG_ID_HSM_WK_EXCHANGE  12000
#define MAVLINK_MSG_ID_HSM_DEK_EXCHANGE 12001
#define MAVLINK_MSG_ID_HSM_KEY_ACK      12002


class DualDekEngine {
public:
    // Singleton access
    static DualDekEngine* get_singleton() {
        if (_singleton == nullptr) {
            _singleton = new DualDekEngine();
        }
        return _singleton;
    }

    // Initialization
    bool init(KeyOrchestrator* ko, KeyExchangeProtocol* kep);

    // Check if encryption is ready (keys available)
    bool is_ready() const { return _ready; }

    // Check if a message should be encrypted/decrypted
    bool should_encrypt(uint32_t msgid) const;

    // === ENCRYPTION (Outgoing messages) ===

    /**
     * Encrypt a MAVLink payload for transmission
     *
     * @param plaintext     Original payload data
     * @param plaintext_len Length of payload
     * @param ciphertext    Output buffer (must be plaintext_len + DDE_HEADER_SIZE)
     * @param ciphertext_len Output: actual ciphertext length
     * @return true on success
     */
    bool encrypt_payload(const uint8_t* plaintext, size_t plaintext_len,
                         uint8_t* ciphertext, size_t* ciphertext_len);

    // === DECRYPTION (Incoming messages) ===

    /**
     * Decrypt a MAVLink payload received from a peer
     *
     * @param src_sysid     Source system ID (to lookup peer DEK)
     * @param ciphertext    Encrypted data (nonce + tag + ciphertext)
     * @param ciphertext_len Length of encrypted data
     * @param plaintext     Output buffer (must be ciphertext_len - DDE_HEADER_SIZE)
     * @param plaintext_len Output: actual plaintext length
     * @return true on success, false if decryption fails
     */
    bool decrypt_payload(uint8_t src_sysid,
                         const uint8_t* ciphertext, size_t ciphertext_len,
                         uint8_t* plaintext, size_t* plaintext_len);

    // === STATUS ===
    void print_status();

    // Statistics
    struct Stats {
        uint32_t tx_encrypted;
        uint32_t tx_plaintext;
        uint32_t rx_decrypted;
        uint32_t rx_failed;
        uint32_t rx_plaintext;
    };

    const Stats& get_stats() const { return _stats; }

private:
    DualDekEngine();

    static DualDekEngine* _singleton;

    KeyOrchestrator* _ko = nullptr;
    KeyExchangeProtocol* _kep = nullptr;

    bool _ready = false;
    Stats _stats = {};

    // Generate random nonce
    void generate_nonce(uint8_t nonce[DDE_NONCE_SIZE]);
};
