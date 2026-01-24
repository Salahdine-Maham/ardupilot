/*
 * KeyExchangeProtocol.cpp - HSM Key Exchange Protocol Implementation
 *
 * Date: 2026-01-24
 */

#include "KeyExchangeProtocol.h"
#include "KeyOrchestrator.h"
#include <AP_HAL/AP_HAL.h>
#include <AP_Math/AP_Math.h>
#include <GCS_MAVLink/GCS.h>

// micro-ecc for ECDH
extern "C" {
#include "uECC.h"
}

extern const AP_HAL::HAL& hal;

// ECIES constants (must match Python implementation)
static const uint8_t ECIES_SALT[] = "ECIES-Salt";
static const uint8_t ECIES_INFO[] = "DEK-Encryption-v1";
#define ECIES_SALT_LEN 10
#define ECIES_INFO_LEN 17

// Singleton
KeyExchangeProtocol* KeyExchangeProtocol::_singleton = nullptr;


// =============================================================================
// CONSTRUCTOR / INIT
// =============================================================================

KeyExchangeProtocol::KeyExchangeProtocol()
{
    _singleton = this;

    // Initialize peer table
    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        memset(&_peers[i], 0, sizeof(PeerInfo));
        _peers[i].state = State::IDLE;
        _peers[i].active = false;
    }
}

bool KeyExchangeProtocol::init(KeyOrchestrator* key_orch)
{
    if (key_orch == nullptr) {
        hal.console->printf("KEP: ERROR - KeyOrchestrator is null\n");
        return false;
    }

    _key_orch = key_orch;

    // Get our WK public from KeyOrchestrator
    const uint8_t* wk_pub = _key_orch->get_wk_public();
    if (wk_pub == nullptr) {
        hal.console->printf("KEP: ERROR - WK public not available\n");
        return false;
    }

    memcpy(_my_wk_public, wk_pub, KEP_PUBKEY_SIZE);
    _wk_public_ready = true;

    hal.console->printf("KEP: Initialized - WK public ready: %02X%02X%02X%02X...\n",
           _my_wk_public[0], _my_wk_public[1], _my_wk_public[2], _my_wk_public[3]);

    return true;
}


// =============================================================================
// PEER MANAGEMENT
// =============================================================================

KeyExchangeProtocol::PeerInfo* KeyExchangeProtocol::find_peer(uint8_t sysid, uint8_t compid)
{
    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (_peers[i].active && _peers[i].sysid == sysid && _peers[i].compid == compid) {
            return &_peers[i];
        }
    }
    return nullptr;
}

KeyExchangeProtocol::PeerInfo* KeyExchangeProtocol::add_peer(uint8_t sysid, uint8_t compid)
{
    // Check if already exists
    PeerInfo* existing = find_peer(sysid, compid);
    if (existing != nullptr) {
        return existing;
    }

    // Find empty slot
    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (!_peers[i].active) {
            memset(&_peers[i], 0, sizeof(PeerInfo));
            _peers[i].sysid = sysid;
            _peers[i].compid = compid;
            _peers[i].state = State::IDLE;
            _peers[i].last_activity_ms = AP_HAL::millis();
            _peers[i].active = true;
            _num_peers++;
            return &_peers[i];
        }
    }

    hal.console->printf("KEP: ERROR - Max peers reached (%d)\n", KEP_MAX_PEERS);
    return nullptr;
}

bool KeyExchangeProtocol::is_known_peer(uint8_t sysid, uint8_t compid)
{
    return find_peer(sysid, compid) != nullptr;
}


// =============================================================================
// DISCOVERY
// =============================================================================

void KeyExchangeProtocol::on_heartbeat_received(uint8_t sysid, uint8_t compid)
{
    // Ignore our own heartbeat
    if (sysid == _my_sysid && compid == _my_compid) {
        return;
    }

    PeerInfo* peer = find_peer(sysid, compid);

    if (peer == nullptr) {
        // New peer detected
        hal.console->printf("KEP: New peer detected: sysid=%d compid=%d\n", sysid, compid);

        peer = add_peer(sysid, compid);
        if (peer != nullptr) {
            // Initiate exchange automatically
            initiate_exchange(sysid, compid);
        }
    } else {
        // Known peer, update timestamp
        peer->last_activity_ms = AP_HAL::millis();
    }
}


// =============================================================================
// EXCHANGE INITIATION
// =============================================================================

bool KeyExchangeProtocol::initiate_exchange(uint8_t peer_sysid, uint8_t peer_compid)
{
    if (!_wk_public_ready) {
        hal.console->printf("KEP: ERROR - WK not initialized\n");
        return false;
    }

    PeerInfo* peer = find_peer(peer_sysid, peer_compid);
    if (peer == nullptr) {
        peer = add_peer(peer_sysid, peer_compid);
        if (peer == nullptr) {
            return false;
        }
    }

    // Send our WK public
    if (send_wk_exchange(peer_sysid, peer_compid)) {
        peer->state = State::WK_SENT;
        peer->last_activity_ms = AP_HAL::millis();
        return true;
    }

    return false;
}

uint8_t KeyExchangeProtocol::initiate_exchange_all_peers()
{
    uint8_t count = 0;
    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (_peers[i].active && _peers[i].state == State::IDLE) {
            if (initiate_exchange(_peers[i].sysid, _peers[i].compid)) {
                count++;
            }
        }
    }
    return count;
}


// =============================================================================
// MESSAGE SENDING
// =============================================================================

bool KeyExchangeProtocol::send_wk_exchange(uint8_t target_sysid, uint8_t target_compid)
{
    // TODO: Implement MAVLink message sending via GCS
    // For now, just log
    hal.console->printf("KEP: WK_EXCHANGE -> sysid=%d (WK: %02X%02X%02X%02X...)\n",
           target_sysid,
           _my_wk_public[0], _my_wk_public[1], _my_wk_public[2], _my_wk_public[3]);

    // The actual sending will be done via GCS_MAVLINK
    // gcs().send_hsm_wk_exchange(target_sysid, target_compid, _my_wk_public);

    return true;
}

bool KeyExchangeProtocol::send_dek_exchange(PeerInfo* peer)
{
    if (peer == nullptr || !peer->wk_received) {
        hal.console->printf("KEP: ERROR - Peer WK not received\n");
        return false;
    }

    // Get our DEK from KeyOrchestrator
    const uint8_t* my_dek = _key_orch->get_my_dek();
    if (my_dek == nullptr) {
        hal.console->printf("KEP: ERROR - DEK not available\n");
        return false;
    }

    // Encrypt DEK with ECIES
    uint8_t ephemeral_pub[KEP_PUBKEY_SIZE];
    uint8_t encrypted_dek[KEP_KEY_SIZE];
    uint8_t nonce[KEP_NONCE_SIZE];
    uint8_t tag[KEP_TAG_SIZE];

    if (!ecies_encrypt_dek(peer->wk_public, my_dek,
                           ephemeral_pub, encrypted_dek, nonce, tag)) {
        hal.console->printf("KEP: ERROR - ECIES encryption failed\n");
        return false;
    }

    hal.console->printf("KEP: DEK_EXCHANGE -> sysid=%d\n", peer->sysid);

    // TODO: Send via MAVLink
    // gcs().send_hsm_dek_exchange(peer->sysid, peer->compid,
    //                              ephemeral_pub, encrypted_dek, nonce, tag);

    return true;
}

bool KeyExchangeProtocol::send_key_ack(uint8_t target_sysid, uint8_t target_compid,
                                        AckStatus status, AckPhase phase)
{
    hal.console->printf("KEP: KEY_ACK -> sysid=%d status=%d phase=%d\n",
           target_sysid, (int)status, (int)phase);

    // TODO: Send via MAVLink
    // gcs().send_hsm_key_ack(target_sysid, target_compid, (uint8_t)status, (uint8_t)phase);

    return true;
}


// =============================================================================
// MESSAGE HANDLERS
// =============================================================================

void KeyExchangeProtocol::handle_wk_exchange(uint8_t src_sysid, uint8_t src_compid,
                                              const uint8_t wk_pub[KEP_PUBKEY_SIZE],
                                              uint32_t timestamp)
{
    PeerInfo* peer = find_peer(src_sysid, src_compid);
    if (peer == nullptr) {
        peer = add_peer(src_sysid, src_compid);
    }

    if (peer == nullptr) {
        return;
    }

    // Store peer's WK public
    memcpy(peer->wk_public, wk_pub, KEP_PUBKEY_SIZE);
    peer->wk_received = true;
    peer->last_activity_ms = AP_HAL::millis();

    hal.console->printf("KEP: WK_EXCHANGE <- sysid=%d: %02X%02X%02X%02X...\n",
           src_sysid, wk_pub[0], wk_pub[1], wk_pub[2], wk_pub[3]);

    // If we haven't sent our WK yet, send it
    if (peer->state == State::IDLE) {
        send_wk_exchange(src_sysid, src_compid);
        peer->state = State::WK_SENT;
    }

    // If WK exchanged both ways, proceed to DEK
    if (peer->state == State::WK_SENT && peer->wk_received) {
        peer->state = State::WK_RECEIVED;
        send_dek_exchange(peer);
        peer->state = State::DEK_SENT;
    }

    // Send ACK
    send_key_ack(src_sysid, src_compid, AckStatus::SUCCESS, AckPhase::WK_RECEIVED);
}

void KeyExchangeProtocol::handle_dek_exchange(uint8_t src_sysid, uint8_t src_compid,
                                               const uint8_t ephemeral_pub[KEP_PUBKEY_SIZE],
                                               const uint8_t encrypted_dek[KEP_KEY_SIZE],
                                               const uint8_t nonce[KEP_NONCE_SIZE],
                                               const uint8_t tag[KEP_TAG_SIZE])
{
    PeerInfo* peer = find_peer(src_sysid, src_compid);
    if (peer == nullptr) {
        hal.console->printf("KEP: ERROR - DEK from unknown peer sysid=%d\n", src_sysid);
        return;
    }

    // Decrypt peer's DEK
    uint8_t decrypted_dek[KEP_KEY_SIZE];

    if (!ecies_decrypt_dek(ephemeral_pub, encrypted_dek, nonce, tag, decrypted_dek)) {
        hal.console->printf("KEP: ERROR - ECIES decryption failed\n");
        send_key_ack(src_sysid, src_compid, AckStatus::DEK_ERROR, AckPhase::DEK_RECEIVED);
        return;
    }

    // Store peer's DEK
    memcpy(peer->dek, decrypted_dek, KEP_KEY_SIZE);
    peer->dek_received = true;
    peer->last_activity_ms = AP_HAL::millis();

    hal.console->printf("KEP: DEK <- sysid=%d: %02X%02X%02X%02X...\n",
           src_sysid, decrypted_dek[0], decrypted_dek[1], decrypted_dek[2], decrypted_dek[3]);

    // Clear sensitive data
    secure_zero(decrypted_dek, KEP_KEY_SIZE);

    // Check if exchange complete
    if (peer->state == State::DEK_SENT && peer->dek_received) {
        peer->state = State::COMPLETE;
        hal.console->printf("KEP: Exchange COMPLETE with sysid=%d\n", src_sysid);
    }

    // Send ACK
    send_key_ack(src_sysid, src_compid, AckStatus::SUCCESS, AckPhase::DEK_RECEIVED);
}

void KeyExchangeProtocol::handle_key_ack(uint8_t src_sysid, uint8_t src_compid,
                                          uint8_t status, uint8_t phase)
{
    PeerInfo* peer = find_peer(src_sysid, src_compid);
    if (peer == nullptr) {
        return;
    }

    peer->last_activity_ms = AP_HAL::millis();

    hal.console->printf("KEP: KEY_ACK <- sysid=%d status=%d phase=%d\n",
           src_sysid, status, phase);

    if (status != (uint8_t)AckStatus::SUCCESS) {
        hal.console->printf("KEP: WARNING - Peer reported error: %d\n", status);
        peer->state = State::ERROR;
    }
}


// =============================================================================
// ECIES IMPLEMENTATION
// =============================================================================

bool KeyExchangeProtocol::ecies_encrypt_dek(const uint8_t peer_wk_pub[KEP_PUBKEY_SIZE],
                                             const uint8_t dek[KEP_KEY_SIZE],
                                             uint8_t ephemeral_pub_out[KEP_PUBKEY_SIZE],
                                             uint8_t encrypted_dek_out[KEP_KEY_SIZE],
                                             uint8_t nonce_out[KEP_NONCE_SIZE],
                                             uint8_t tag_out[KEP_TAG_SIZE])
{
    uECC_Curve curve = uECC_secp256r1();

    // 1. Generate ephemeral keypair
    uint8_t ephemeral_priv[32];
    if (uECC_make_key(ephemeral_pub_out, ephemeral_priv, curve) != 1) {
        hal.console->printf("KEP: ERROR - Ephemeral key generation failed\n");
        return false;
    }

    // 2. ECDH: shared_secret = ephemeral_priv * peer_wk_pub
    uint8_t shared_secret[32];
    if (!ecdh_compute_shared(ephemeral_priv, peer_wk_pub, shared_secret)) {
        hal.console->printf("KEP: ERROR - ECDH failed\n");
        secure_zero(ephemeral_priv, 32);
        return false;
    }

    // 3. Derive encryption key via HKDF
    uint8_t encryption_key[32];
    hkdf_derive(shared_secret, 32,
                ECIES_SALT, ECIES_SALT_LEN,
                ECIES_INFO, ECIES_INFO_LEN,
                encryption_key, 32);

    // 4. Generate random nonce
    hal.util->get_random_vals(nonce_out, KEP_NONCE_SIZE);

    // 5. Encrypt with ChaCha20-Poly1305
    if (!chacha_encrypt(encryption_key, nonce_out, dek, KEP_KEY_SIZE,
                        encrypted_dek_out, tag_out)) {
        hal.console->printf("KEP: ERROR - ChaCha20 encryption failed\n");
        secure_zero(ephemeral_priv, 32);
        secure_zero(shared_secret, 32);
        secure_zero(encryption_key, 32);
        return false;
    }

    // 6. Cleanup secrets
    secure_zero(ephemeral_priv, 32);
    secure_zero(shared_secret, 32);
    secure_zero(encryption_key, 32);

    hal.console->printf("KEP: ECIES encryption OK\n");
    return true;
}

bool KeyExchangeProtocol::ecies_decrypt_dek(const uint8_t ephemeral_pub[KEP_PUBKEY_SIZE],
                                             const uint8_t encrypted_dek[KEP_KEY_SIZE],
                                             const uint8_t nonce[KEP_NONCE_SIZE],
                                             const uint8_t tag[KEP_TAG_SIZE],
                                             uint8_t dek_out[KEP_KEY_SIZE])
{
    // 1. Get our WK private from KeyOrchestrator
    const uint8_t* my_wk_priv = _key_orch->get_wk_private();
    if (my_wk_priv == nullptr) {
        hal.console->printf("KEP: ERROR - WK private not available\n");
        return false;
    }

    // 2. ECDH: shared_secret = my_wk_priv * ephemeral_pub
    uint8_t shared_secret[32];
    if (!ecdh_compute_shared(my_wk_priv, ephemeral_pub, shared_secret)) {
        hal.console->printf("KEP: ERROR - ECDH decryption failed\n");
        return false;
    }

    // 3. Derive same encryption key
    uint8_t encryption_key[32];
    hkdf_derive(shared_secret, 32,
                ECIES_SALT, ECIES_SALT_LEN,
                ECIES_INFO, ECIES_INFO_LEN,
                encryption_key, 32);

    // 4. Decrypt with ChaCha20-Poly1305
    if (!chacha_decrypt(encryption_key, nonce, encrypted_dek, KEP_KEY_SIZE,
                        tag, dek_out)) {
        hal.console->printf("KEP: ERROR - ChaCha20 decryption failed (auth error)\n");
        secure_zero(shared_secret, 32);
        secure_zero(encryption_key, 32);
        return false;
    }

    // 5. Cleanup
    secure_zero(shared_secret, 32);
    secure_zero(encryption_key, 32);

    hal.console->printf("KEP: ECIES decryption OK\n");
    return true;
}


// =============================================================================
// CRYPTO HELPERS
// =============================================================================

bool KeyExchangeProtocol::ecdh_compute_shared(const uint8_t* my_private,
                                               const uint8_t* peer_public,
                                               uint8_t* shared_out)
{
    uECC_Curve curve = uECC_secp256r1();

    if (uECC_shared_secret(peer_public, my_private, shared_out, curve) != 1) {
        return false;
    }

    return true;
}

void KeyExchangeProtocol::hkdf_derive(const uint8_t* ikm, size_t ikm_len,
                                       const uint8_t* salt, size_t salt_len,
                                       const uint8_t* info, size_t info_len,
                                       uint8_t* okm, size_t okm_len)
{
    // HKDF-SHA256 simplified implementation
    // TODO: Replace with proper HKDF from AP_Crypto

    // Simplified key derivation (XOR-based placeholder)
    for (size_t i = 0; i < okm_len && i < 32; i++) {
        okm[i] = ikm[i % ikm_len] ^ salt[i % salt_len] ^ info[i % info_len];
    }

    // Mix with index
    for (size_t i = 0; i < okm_len; i++) {
        okm[i] ^= (uint8_t)i;
    }
}

bool KeyExchangeProtocol::chacha_encrypt(const uint8_t* key,
                                          const uint8_t* nonce,
                                          const uint8_t* plaintext, size_t plaintext_len,
                                          uint8_t* ciphertext,
                                          uint8_t* tag)
{
    // TODO: Implement ChaCha20-Poly1305
    // For now, use XOR as placeholder (INSECURE - for testing only)

    // XOR encryption (placeholder)
    for (size_t i = 0; i < plaintext_len; i++) {
        ciphertext[i] = plaintext[i] ^ key[i % 32] ^ nonce[i % 12];
    }

    // Fake tag (placeholder)
    for (int i = 0; i < KEP_TAG_SIZE; i++) {
        tag[i] = ciphertext[i % plaintext_len] ^ key[i];
    }

    return true;
}

bool KeyExchangeProtocol::chacha_decrypt(const uint8_t* key,
                                          const uint8_t* nonce,
                                          const uint8_t* ciphertext, size_t ciphertext_len,
                                          const uint8_t* tag,
                                          uint8_t* plaintext)
{
    // TODO: Implement ChaCha20-Poly1305 with proper auth
    // For now, use XOR as placeholder (INSECURE - for testing only)

    // Suppress unused parameter warning
    (void)tag;

    // XOR decryption (placeholder)
    for (size_t i = 0; i < ciphertext_len; i++) {
        plaintext[i] = ciphertext[i] ^ key[i % 32] ^ nonce[i % 12];
    }

    return true;
}

void KeyExchangeProtocol::secure_zero(void* ptr, size_t len)
{
    volatile uint8_t* p = (volatile uint8_t*)ptr;
    while (len--) {
        *p++ = 0;
    }
}


// =============================================================================
// STATE QUERIES
// =============================================================================

KeyExchangeProtocol::State KeyExchangeProtocol::get_peer_state(uint8_t sysid, uint8_t compid)
{
    PeerInfo* peer = find_peer(sysid, compid);
    return peer ? peer->state : State::IDLE;
}

bool KeyExchangeProtocol::is_exchange_complete(uint8_t sysid, uint8_t compid)
{
    PeerInfo* peer = find_peer(sysid, compid);
    return peer && peer->state == State::COMPLETE;
}

const uint8_t* KeyExchangeProtocol::get_peer_dek(uint8_t sysid, uint8_t compid)
{
    PeerInfo* peer = find_peer(sysid, compid);
    if (peer && peer->dek_received) {
        return peer->dek;
    }
    return nullptr;
}

uint8_t KeyExchangeProtocol::get_num_complete() const
{
    uint8_t count = 0;
    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (_peers[i].active && _peers[i].state == State::COMPLETE) {
            count++;
        }
    }
    return count;
}


// =============================================================================
// TIMEOUT
// =============================================================================

void KeyExchangeProtocol::check_timeouts()
{
    uint32_t now = AP_HAL::millis();

    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (!_peers[i].active) continue;

        if (_peers[i].state != State::IDLE &&
            _peers[i].state != State::COMPLETE &&
            _peers[i].state != State::ERROR) {

            if ((now - _peers[i].last_activity_ms) > KEP_EXCHANGE_TIMEOUT_MS) {
                hal.console->printf("KEP: TIMEOUT - sysid=%d\n", _peers[i].sysid);
                _peers[i].state = State::ERROR;
            }
        }
    }
}


// =============================================================================
// STATUS
// =============================================================================

void KeyExchangeProtocol::print_status()
{
    hal.console->printf("\nKEP: === Key Exchange Protocol Status ===\n");
    hal.console->printf("KEP:   WK public ready: %s\n", _wk_public_ready ? "YES" : "NO");
    hal.console->printf("KEP:   Peers: %d/%d\n", _num_peers, KEP_MAX_PEERS);
    hal.console->printf("KEP:   Complete: %d\n", get_num_complete());

    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (_peers[i].active) {
            const char* state_str;
            switch (_peers[i].state) {
                case State::IDLE: state_str = "IDLE"; break;
                case State::WK_SENT: state_str = "WK_SENT"; break;
                case State::WK_RECEIVED: state_str = "WK_RECEIVED"; break;
                case State::DEK_SENT: state_str = "DEK_SENT"; break;
                case State::DEK_RECEIVED: state_str = "DEK_RECEIVED"; break;
                case State::COMPLETE: state_str = "COMPLETE"; break;
                case State::ERROR: state_str = "ERROR"; break;
                default: state_str = "UNKNOWN";
            }
            hal.console->printf("KEP:   Peer %d: sysid=%d state=%s wk=%d dek=%d\n",
                   i, _peers[i].sysid, state_str,
                   _peers[i].wk_received, _peers[i].dek_received);
        }
    }
}
