/*
 * KeyExchangeProtocol.h - HSM Key Exchange Protocol
 *
 * Implements secure key exchange between drones/GCS:
 * 1. Exchange Wrapper Key public (HSM_WK_EXCHANGE)
 * 2. Exchange encrypted DEK via ECIES (HSM_DEK_EXCHANGE)
 * 3. Acknowledge completion (HSM_KEY_ACK)
 *
 * Date: 2026-01-24
 */

#pragma once

#include <AP_HAL/AP_HAL.h>
#include <stdint.h>

// Forward declarations
class KeyOrchestrator;
class GCS_MAVLINK;

// MAVLink message IDs
#define MAVLINK_MSG_ID_HSM_WK_EXCHANGE  12000
#define MAVLINK_MSG_ID_HSM_DEK_EXCHANGE 12001
#define MAVLINK_MSG_ID_HSM_KEY_ACK      12002

// Key sizes
#define KEP_KEY_SIZE        32
#define KEP_PUBKEY_SIZE     64   // P-256 uncompressed X||Y
#define KEP_NONCE_SIZE      24   // XChaCha20-Poly1305 uses 24-byte nonce
#define KEP_TAG_SIZE        16

// Maximum number of peers
#define KEP_MAX_PEERS       5

// Timeout for key exchange (ms)
#define KEP_EXCHANGE_TIMEOUT_MS  10000


class KeyExchangeProtocol {
public:
    // Exchange state machine
    enum class State : uint8_t {
        IDLE = 0,
        WK_SENT,
        WK_RECEIVED,
        DEK_SENT,
        DEK_RECEIVED,
        COMPLETE,
        ERROR
    };

    // ACK status codes
    enum class AckStatus : uint8_t {
        SUCCESS = 0,
        WK_ERROR = 1,
        DEK_ERROR = 2,
        TIMEOUT = 3
    };

    // ACK phase codes
    enum class AckPhase : uint8_t {
        WK_RECEIVED = 1,
        DEK_RECEIVED = 2,
        COMPLETE = 3
    };

    // Peer information
    struct PeerInfo {
        uint8_t sysid;
        uint8_t compid;
        uint8_t wk_public[KEP_PUBKEY_SIZE];
        uint8_t dek[KEP_KEY_SIZE];
        State state;
        uint32_t last_activity_ms;
        bool wk_received;
        bool dek_received;
        bool active;
    };

    // Singleton access (lazy initialization)
    static KeyExchangeProtocol* get_singleton() {
        if (_singleton == nullptr) {
            _singleton = new KeyExchangeProtocol();
        }
        return _singleton;
    }

private:
    KeyExchangeProtocol();

public:

    // Initialization
    bool init(KeyOrchestrator* key_orch);

    // === DISCOVERY ===
    void on_heartbeat_received(uint8_t sysid, uint8_t compid);
    bool is_known_peer(uint8_t sysid, uint8_t compid);

    // === EXCHANGE INITIATION ===
    bool initiate_exchange(uint8_t peer_sysid, uint8_t peer_compid);
    uint8_t initiate_exchange_all_peers();

    // === MESSAGE HANDLERS ===
    void handle_wk_exchange(uint8_t src_sysid, uint8_t src_compid,
                            const uint8_t wk_pub[KEP_PUBKEY_SIZE],
                            uint32_t timestamp);

    void handle_dek_exchange(uint8_t src_sysid, uint8_t src_compid,
                             const uint8_t ephemeral_pub[KEP_PUBKEY_SIZE],
                             const uint8_t encrypted_dek[KEP_KEY_SIZE],
                             const uint8_t nonce[KEP_NONCE_SIZE],
                             const uint8_t tag[KEP_TAG_SIZE]);

    void handle_key_ack(uint8_t src_sysid, uint8_t src_compid,
                        uint8_t status, uint8_t phase);

    // === ECIES ===
    bool ecies_encrypt_dek(const uint8_t peer_wk_pub[KEP_PUBKEY_SIZE],
                           const uint8_t dek[KEP_KEY_SIZE],
                           uint8_t ephemeral_pub_out[KEP_PUBKEY_SIZE],
                           uint8_t encrypted_dek_out[KEP_KEY_SIZE],
                           uint8_t nonce_out[KEP_NONCE_SIZE],
                           uint8_t tag_out[KEP_TAG_SIZE]);

    bool ecies_decrypt_dek(const uint8_t ephemeral_pub[KEP_PUBKEY_SIZE],
                           const uint8_t encrypted_dek[KEP_KEY_SIZE],
                           const uint8_t nonce[KEP_NONCE_SIZE],
                           const uint8_t tag[KEP_TAG_SIZE],
                           uint8_t dek_out[KEP_KEY_SIZE]);

    // === STATE QUERIES ===
    State get_peer_state(uint8_t sysid, uint8_t compid);
    bool is_exchange_complete(uint8_t sysid, uint8_t compid);
    const uint8_t* get_peer_dek(uint8_t sysid, uint8_t compid);
    uint8_t get_num_peers() const { return _num_peers; }
    uint8_t get_num_complete() const;

    // === TIMEOUT CHECK ===
    void check_timeouts();

    // === STATUS ===
    void print_status();

private:
    static KeyExchangeProtocol* _singleton;

    KeyOrchestrator* _key_orch = nullptr;

    // Our keys
    uint8_t _my_wk_public[KEP_PUBKEY_SIZE];
    bool _wk_public_ready = false;

    // Peer table
    PeerInfo _peers[KEP_MAX_PEERS];
    uint8_t _num_peers = 0;

    // Our MAVLink identity
    uint8_t _my_sysid = 1;
    uint8_t _my_compid = 1;

    // Helper functions
    PeerInfo* find_peer(uint8_t sysid, uint8_t compid);
    PeerInfo* add_peer(uint8_t sysid, uint8_t compid);

    bool send_wk_exchange(uint8_t target_sysid, uint8_t target_compid);
    bool send_dek_exchange(PeerInfo* peer);
    bool send_key_ack(uint8_t target_sysid, uint8_t target_compid,
                      AckStatus status, AckPhase phase);

    // ECDH helper
    bool ecdh_compute_shared(const uint8_t* my_private,
                             const uint8_t* peer_public,
                             uint8_t* shared_out);

    // HKDF helper
    void hkdf_derive(const uint8_t* ikm, size_t ikm_len,
                     const uint8_t* salt, size_t salt_len,
                     const uint8_t* info, size_t info_len,
                     uint8_t* okm, size_t okm_len);

    // ChaCha20-Poly1305 helpers
    bool chacha_encrypt(const uint8_t* key,
                        const uint8_t* nonce,
                        const uint8_t* plaintext, size_t plaintext_len,
                        uint8_t* ciphertext,
                        uint8_t* tag);

    bool chacha_decrypt(const uint8_t* key,
                        const uint8_t* nonce,
                        const uint8_t* ciphertext, size_t ciphertext_len,
                        const uint8_t* tag,
                        uint8_t* plaintext);

    // Secure zero
    void secure_zero(void* ptr, size_t len);
};
