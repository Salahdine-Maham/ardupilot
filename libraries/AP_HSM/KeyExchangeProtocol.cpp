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
#include <AP_CheckFirmware/monocypher.h>
#include <AP_Crypto/AP_Crypto.h>
#include <cstdio>

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

// Peer reset timeout: if no activity for this long, reset peer to allow re-exchange
#define KEP_PEER_RESET_TIMEOUT_MS  30000  // 30 seconds

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
    hal.console->printf("KEP::init called\n");

    if (key_orch == nullptr) {
        hal.console->printf("KEP: ERROR - KeyOrchestrator is null\n");
        return false;
    }

    _key_orch = key_orch;

    // Get our WK public from KeyOrchestrator
    hal.console->printf("KEP: Getting WK public from KeyOrchestrator...\n");
    const uint8_t* wk_pub = _key_orch->get_wk_public();

    if (wk_pub == nullptr) {
        hal.console->printf("KEP: ERROR - get_wk_public() returned NULL!\n");
        hal.console->printf("KEP: This means _wk_loaded is false in KeyOrchestrator\n");
        return false;
    }

    // Debug: show what we're copying
    hal.console->printf("KEP: Source WK from KO: %02X%02X%02X%02X...\n",
           wk_pub[0], wk_pub[1], wk_pub[2], wk_pub[3]);

    memcpy(_my_wk_public, wk_pub, KEP_PUBKEY_SIZE);
    _wk_public_ready = true;

    // Debug: verify copy
    hal.console->printf("KEP: After copy, _my_wk_public: %02X%02X%02X%02X...\n",
           _my_wk_public[0], _my_wk_public[1], _my_wk_public[2], _my_wk_public[3]);

    GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: WK ready %02X%02X%02X%02X",
                  _my_wk_public[0], _my_wk_public[1], _my_wk_public[2], _my_wk_public[3]);

    return true;
}


// =============================================================================
// PEER MANAGEMENT
// =============================================================================

KeyExchangeProtocol::PeerInfo* KeyExchangeProtocol::find_peer(uint8_t sysid, uint8_t compid)
{
    for (uint8_t i = 0; i < KEP_MAX_PEERS; i++) {
        if (_peers[i].active && _peers[i].sysid == sysid) {
            // compid=0 means "match any compid" (wildcard)
            if (compid == 0 || _peers[i].compid == compid) {
                return &_peers[i];
            }
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
    // Debug entry (stdout pour voir même sans MAVProxy)
    static uint32_t hb_count = 0;
    hb_count++;
    if (hb_count <= 3 || hb_count % 100 == 0) {
        hal.console->printf("KEP: on_heartbeat_received(%d, %d) #%lu my_sysid=%d\n",
               sysid, compid, (unsigned long)hb_count, _my_sysid);
        
    }

    // Ignore our own heartbeat
    if (sysid == _my_sysid && compid == _my_compid) {
        hal.console->printf("KEP: Ignoring own heartbeat (sysid=%d)\n", sysid);
        
        return;
    }

    PeerInfo* peer = find_peer(sysid, compid);

    if (peer == nullptr) {
        // New peer detected
        hal.console->printf("KEP: NEW PEER detected sysid=%d compid=%d\n", sysid, compid);
        
        GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: New peer sysid=%d compid=%d",
                      sysid, compid);

        peer = add_peer(sysid, compid);
        if (peer != nullptr) {
            hal.console->printf("KEP: Peer added, initiating exchange...\n");
            
            GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Initiating exchange");
            // Initiate exchange automatically
            initiate_exchange(sysid, compid);
        } else {
            hal.console->printf("KEP: ERROR - Failed to add peer!\n");
            
            GCS_SEND_TEXT(MAV_SEVERITY_WARNING, "KEP: Failed to add peer");
        }
    } else {
        // Known peer - check if we should reset due to inactivity
        uint32_t now = AP_HAL::millis();
        uint32_t inactive_time = now - peer->last_activity_ms;

        // If peer was inactive for reset timeout, reset state for re-exchange
        if (inactive_time > KEP_PEER_RESET_TIMEOUT_MS &&
            (peer->state == State::COMPLETE ||
             peer->state == State::ERROR ||
             peer->state == State::DEK_SENT ||
             peer->state == State::DEK_RECEIVED)) {

            hal.console->printf("KEP: Resetting peer sysid=%d (inactive %lums)\n",
                   sysid, (unsigned long)inactive_time);
            GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Peer %d reset for re-exchange", sysid);

            peer->state = State::IDLE;
            peer->wk_received = false;
            peer->dek_received = false;
        }

        // Update timestamp AFTER checking for reset
        peer->last_activity_ms = now;

        // If peer is IDLE (just reset or was already idle), re-initiate exchange
        if (peer->state == State::IDLE && _wk_public_ready) {
            hal.console->printf("KEP: Re-initiating exchange with peer sysid=%d\n", sysid);
            GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Re-exchange with peer %d", sysid);
            initiate_exchange(sysid, compid);
        }
    }

    // Also check timeouts for other peers (exchange-in-progress timeouts)
    check_timeouts();
}


// =============================================================================
// EXCHANGE INITIATION
// =============================================================================

bool KeyExchangeProtocol::initiate_exchange(uint8_t peer_sysid, uint8_t peer_compid)
{
    hal.console->printf("KEP: initiate_exchange(%d, %d) wk_ready=%d\n",
           peer_sysid, peer_compid, _wk_public_ready);
    

    if (!_wk_public_ready) {
        hal.console->printf("KEP: ERROR - WK not initialized!\n");
        
        hal.console->printf("KEP: ERROR - WK not initialized\n");
        return false;
    }

    PeerInfo* peer = find_peer(peer_sysid, peer_compid);
    if (peer == nullptr) {
        peer = add_peer(peer_sysid, peer_compid);
        if (peer == nullptr) {
            hal.console->printf("KEP: ERROR - Cannot add peer\n");
            
            return false;
        }
    }

    // Send our WK public
    if (send_wk_exchange(peer_sysid, peer_compid)) {
        peer->state = State::WK_SENT;
        peer->last_activity_ms = AP_HAL::millis();
        hal.console->printf("KEP: ✓ Exchange initiated, state=WK_SENT\n");
        
        return true;
    }

    hal.console->printf("KEP: ERROR - send_wk_exchange failed\n");
    
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
    // Send on all active MAVLink channels
    uint8_t mask = GCS_MAVLINK::active_channel_mask();
    uint32_t timestamp = AP_HAL::millis();

    hal.console->printf("KEP: >>> send_wk_exchange() called for sysid=%d <<<\n", target_sysid);
    hal.console->printf("KEP: send_wk_exchange to sysid=%d, chan_mask=0x%02X\n", target_sysid, mask);
    hal.console->printf("KEP: WK public: %02X%02X%02X%02X...\n",
           _my_wk_public[0], _my_wk_public[1], _my_wk_public[2], _my_wk_public[3]);
    

    // Debug: show first 4 bytes of WK to verify it's not all zeros
    GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: WK->%d mask=0x%02X WK:%02X%02X%02X%02X",
                  target_sysid, mask,
                  _my_wk_public[0], _my_wk_public[1], _my_wk_public[2], _my_wk_public[3]);

    if (mask == 0) {
        hal.console->printf("KEP: ERROR - No active MAVLink channels!\n");
        
        GCS_SEND_TEXT(MAV_SEVERITY_WARNING, "KEP: No active channels!");
        return false;
    }

    // Check if _my_wk_public is all zeros (would cause MAVLink v2 truncation)
    bool wk_all_zeros = true;
    for (int j = 0; j < 64; j++) {
        if (_my_wk_public[j] != 0) {
            wk_all_zeros = false;
            break;
        }
    }
    if (wk_all_zeros) {
        hal.console->printf("KEP: ERROR - _my_wk_public is ALL ZEROS! KEP init failed?\n");
        GCS_SEND_TEXT(MAV_SEVERITY_ERROR, "KEP: WK is ZEROS!");
        return false;
    }

    uint8_t sent = 0;
    for (uint8_t i = 0; i < MAVLINK_COMM_NUM_BUFFERS; i++) {
        if (mask & (1U << i)) {
            mavlink_channel_t chan = (mavlink_channel_t)(MAVLINK_COMM_0 + i);
            hal.console->printf("KEP: Sending HSM_WK_EXCHANGE on chan %d\n", i);

            mavlink_msg_hsm_wk_exchange_send(chan, target_sysid, target_compid,
                                             _my_wk_public, timestamp);
            sent++;
        }
    }

    hal.console->printf("KEP: ✓ WK_EXCHANGE sent on %d channels\n", sent);

    GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: WK sent on %d channels", sent);
    return true;
}

bool KeyExchangeProtocol::send_dek_exchange(PeerInfo* peer)
{
    if (peer == nullptr || !peer->wk_received) {
        return false;
    }

    // Get our DEK from KeyOrchestrator
    const uint8_t* my_dek = _key_orch->get_my_dek();
    if (my_dek == nullptr) {
        GCS_SEND_TEXT(MAV_SEVERITY_ERROR, "KEP: DEK not available");
        return false;
    }

    // Encrypt DEK with ECIES
    uint8_t ephemeral_pub[KEP_PUBKEY_SIZE];
    uint8_t encrypted_dek[KEP_KEY_SIZE];
    uint8_t nonce[KEP_NONCE_SIZE];
    uint8_t tag[KEP_TAG_SIZE];

    if (!ecies_encrypt_dek(peer->wk_public, my_dek,
                           ephemeral_pub, encrypted_dek, nonce, tag)) {
        GCS_SEND_TEXT(MAV_SEVERITY_ERROR, "KEP: ECIES encrypt failed");
        return false;
    }

    // Send on all active MAVLink channels
    uint8_t mask = GCS_MAVLINK::active_channel_mask();

    for (uint8_t i = 0; i < MAVLINK_COMM_NUM_BUFFERS; i++) {
        if (mask & (1U << i)) {
            mavlink_channel_t chan = (mavlink_channel_t)(MAVLINK_COMM_0 + i);
            mavlink_msg_hsm_dek_exchange_send(chan, peer->sysid, peer->compid,
                                              ephemeral_pub, encrypted_dek, nonce, tag);
        }
    }

    GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: DEK sent to %d", peer->sysid);
    return true;
}

bool KeyExchangeProtocol::send_key_ack(uint8_t target_sysid, uint8_t target_compid,
                                        AckStatus status, AckPhase phase)
{
    hal.console->printf("KEP: KEY_ACK -> sysid=%d status=%d phase=%d\n",
           target_sysid, (int)status, (int)phase);

    // Send on all active MAVLink channels
    uint8_t mask = GCS_MAVLINK::active_channel_mask();

    for (uint8_t i = 0; i < MAVLINK_COMM_NUM_BUFFERS; i++) {
        if (mask & (1U << i)) {
            mavlink_channel_t chan = (mavlink_channel_t)(MAVLINK_COMM_0 + i);
            mavlink_msg_hsm_key_ack_send(chan, target_sysid, target_compid,
                                         (uint8_t)status, (uint8_t)phase);
        }
    }

    return true;
}


// =============================================================================
// MESSAGE HANDLERS
// =============================================================================

void KeyExchangeProtocol::handle_wk_exchange(uint8_t src_sysid, uint8_t src_compid,
                                              const uint8_t wk_pub[KEP_PUBKEY_SIZE],
                                              uint32_t timestamp)
{
    hal.console->printf("KEP: handle_wk_exchange from sysid=%d compid=%d\n", src_sysid, src_compid);
    hal.console->printf("KEP:   WK: %02X%02X%02X%02X...\n", wk_pub[0], wk_pub[1], wk_pub[2], wk_pub[3]);
    

    PeerInfo* peer = find_peer(src_sysid, src_compid);
    if (peer == nullptr) {
        hal.console->printf("KEP: Adding new peer for WK exchange\n");
        
        peer = add_peer(src_sysid, src_compid);
    }

    if (peer == nullptr) {
        hal.console->printf("KEP: ERROR - Could not add peer!\n");
        
        return;
    }

    // Store peer's WK public
    memcpy(peer->wk_public, wk_pub, KEP_PUBKEY_SIZE);
    peer->wk_received = true;
    peer->last_activity_ms = AP_HAL::millis();

    hal.console->printf("KEP: ✓ Stored peer WK, state=%d, wk_public_ready=%d\n",
           (int)peer->state, _wk_public_ready);
    GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: WK stored state=%d wk_ready=%d", (int)peer->state, _wk_public_ready);


    // Always send our WK when we receive peer's WK
    // This handles race conditions where our first WK might have been lost
    // (e.g., sent via initiate_exchange before GCS was ready to receive)
    if (peer->state == State::IDLE || peer->state == State::WK_SENT) {
        hal.console->printf("KEP: Sending our WK in response (state=%d)...\n", (int)peer->state);
        GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Sending WK response (state=%d)", (int)peer->state);

        if (!send_wk_exchange(src_sysid, src_compid)) {
            hal.console->printf("KEP: WARNING - send_wk_exchange failed!\n");
            GCS_SEND_TEXT(MAV_SEVERITY_WARNING, "KEP: send_wk_exchange FAILED!");
        } else {
            GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: WK sent OK");
        }
        if (peer->state == State::IDLE) {
            peer->state = State::WK_SENT;
        }
    } else {
        GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Skip WK send (state=%d)", (int)peer->state);
    }

    // If WK exchanged both ways, proceed to DEK
    if (peer->state == State::WK_SENT && peer->wk_received) {
        hal.console->printf("KEP: WK exchange complete, sending DEK...\n");
        GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Sending DEK...");

        peer->state = State::WK_RECEIVED;
        if (!send_dek_exchange(peer)) {
            hal.console->printf("KEP: WARNING - send_dek_exchange failed!\n");
            GCS_SEND_TEXT(MAV_SEVERITY_WARNING, "KEP: send_dek_exchange FAILED!");
        } else {
            GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: DEK sent OK");
        }
        peer->state = State::DEK_SENT;
    }

    // Send ACK
    hal.console->printf("KEP: Sending KEY_ACK for WK\n");
    GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Sending KEY_ACK");
    
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
// Note: uECC now works on both SITL (x86_64) and Pixhawk (ARM Cortex-M7)
// thanks to proper platform detection in uECC_config.h

// RNG callback for uECC - uses ArduPilot's hardware RNG
static int kep_rng_callback(uint8_t* dest, unsigned int size)
{
    if (hal.util->get_random_vals(dest, size)) {
        return 1;  // Success
    }
    return 0;  // Failure
}

bool KeyExchangeProtocol::ecies_encrypt_dek(const uint8_t peer_wk_pub[KEP_PUBKEY_SIZE],
                                             const uint8_t dek[KEP_KEY_SIZE],
                                             uint8_t ephemeral_pub_out[KEP_PUBKEY_SIZE],
                                             uint8_t encrypted_dek_out[KEP_KEY_SIZE],
                                             uint8_t nonce_out[KEP_NONCE_SIZE],
                                             uint8_t tag_out[KEP_TAG_SIZE])
{
    // Configure RNG for uECC (MUST be called before uECC_make_key)
    uECC_set_rng(&kep_rng_callback);

    uint8_t shared_secret[32];
    uint8_t ephemeral_priv[32];
    uECC_Curve curve = uECC_secp256r1();

    // 1. Generate ephemeral keypair
    if (uECC_make_key(ephemeral_pub_out, ephemeral_priv, curve) != 1) {
        GCS_SEND_TEXT(MAV_SEVERITY_ERROR, "KEP: uECC_make_key failed");
        return false;
    }

    // 2. ECDH: shared_secret = ephemeral_priv * peer_wk_pub
    if (!ecdh_compute_shared(ephemeral_priv, peer_wk_pub, shared_secret)) {
        GCS_SEND_TEXT(MAV_SEVERITY_ERROR, "KEP: ECDH failed");
        secure_zero(ephemeral_priv, 32);
        return false;
    }
    secure_zero(ephemeral_priv, 32);

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
        secure_zero(shared_secret, 32);
        secure_zero(encryption_key, 32);
        return false;
    }

    // 6. Cleanup secrets
    secure_zero(shared_secret, 32);
    secure_zero(encryption_key, 32);

    return true;
}

bool KeyExchangeProtocol::ecies_decrypt_dek(const uint8_t ephemeral_pub[KEP_PUBKEY_SIZE],
                                             const uint8_t encrypted_dek[KEP_KEY_SIZE],
                                             const uint8_t nonce[KEP_NONCE_SIZE],
                                             const uint8_t tag[KEP_TAG_SIZE],
                                             uint8_t dek_out[KEP_KEY_SIZE])
{
    uint8_t shared_secret[32];

    // 1. Get our WK private from KeyOrchestrator
    const uint8_t* my_wk_priv = _key_orch->get_wk_private();
    if (my_wk_priv == nullptr) {
        hal.console->printf("KEP: ERROR - WK private not available\n");
        return false;
    }

    // 2. ECDH: shared_secret = my_wk_priv * ephemeral_pub
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
    // HKDF-SHA256 using AP_Crypto implementation (RFC 5869)
    hkdf_sha256(salt, salt_len, ikm, ikm_len, info, info_len, okm, okm_len);
}

bool KeyExchangeProtocol::chacha_encrypt(const uint8_t* key,
                                          const uint8_t* nonce,
                                          const uint8_t* plaintext, size_t plaintext_len,
                                          uint8_t* ciphertext,
                                          uint8_t* tag)
{
    // XChaCha20-Poly1305 encryption using Monocypher
    // crypto_lock(mac, cipher_text, key, nonce, plain_text, text_size)
    // nonce must be 24 bytes (XChaCha20)
    crypto_lock(tag, ciphertext, key, nonce, plaintext, plaintext_len);
    return true;
}

bool KeyExchangeProtocol::chacha_decrypt(const uint8_t* key,
                                          const uint8_t* nonce,
                                          const uint8_t* ciphertext, size_t ciphertext_len,
                                          const uint8_t* tag,
                                          uint8_t* plaintext)
{
    // XChaCha20-Poly1305 decryption using Monocypher
    // crypto_unlock returns 0 on success, -1 if MAC verification fails
    // crypto_unlock(plain_text, key, nonce, mac, cipher_text, text_size)
    int result = crypto_unlock(plaintext, key, nonce, tag, ciphertext, ciphertext_len);
    if (result != 0) {
        hal.console->printf("KEP: crypto_unlock failed - authentication error\n");
        return false;
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

        uint32_t inactive_time = now - _peers[i].last_activity_ms;

        // Check for peer reset (allows re-exchange after reconnection)
        // Only reset peers that are in COMPLETE, ERROR, or stuck states
        if (_peers[i].state == State::COMPLETE ||
            _peers[i].state == State::ERROR ||
            _peers[i].state == State::DEK_SENT ||
            _peers[i].state == State::DEK_RECEIVED) {

            if (inactive_time > KEP_PEER_RESET_TIMEOUT_MS) {
                hal.console->printf("KEP: Resetting peer sysid=%d (inactive %lums)\n",
                       _peers[i].sysid, (unsigned long)inactive_time);
                GCS_SEND_TEXT(MAV_SEVERITY_INFO, "KEP: Peer %d reset for re-exchange", _peers[i].sysid);

                // Reset peer state for fresh exchange
                _peers[i].state = State::IDLE;
                _peers[i].wk_received = false;
                _peers[i].dek_received = false;
                // Keep wk_public and dek buffers - they'll be overwritten on new exchange
                // Keep active = true so we recognize this peer
            }
        }

        // Check for exchange timeout (error during active exchange)
        if (_peers[i].state != State::IDLE &&
            _peers[i].state != State::COMPLETE &&
            _peers[i].state != State::ERROR) {

            if (inactive_time > KEP_EXCHANGE_TIMEOUT_MS) {
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
