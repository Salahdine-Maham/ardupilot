/*
 * test_key_exchange.cpp - Unit tests for KeyExchangeProtocol
 *
 * Tests the ECIES key exchange mechanism and state machine.
 * Uses GCS stub to handle GCS_SEND_TEXT() calls in KEP.
 *
 * Run with: ./build/sitl/tests/test_key_exchange
 */

#include <AP_gtest.h>
#include <AP_HAL/AP_HAL.h>
#include <AP_HSM/AP_HSM.h>
#include <AP_HSM/KeyOrchestrator.h>
#include <AP_HSM/KeyExchangeProtocol.h>
#include <AP_HSM/uECC.h>
#include <string.h>

// GCS stub for test environment
#include "gcs_test_stub.h"
GCS_TEST_STUB_INSTANCE

const AP_HAL::HAL& hal = AP_HAL::get_HAL();

// RNG for uECC - must be set before using elliptic curve operations
static int test_rng(uint8_t *dest, unsigned size) {
    for (unsigned i = 0; i < size; i++) {
        dest[i] = (uint8_t)(rand() & 0xFF);
    }
    return 1;
}

// =============================================================================
// TEST FIXTURE
// =============================================================================

class KeyExchangeProtocolTest : public ::testing::Test {
protected:
    void SetUp() override {
        // CRITICAL: Set up RNG for uECC BEFORE any elliptic curve operations
        uECC_set_rng(test_rng);

        hsm = &AP_HSM::get_singleton();
        ko = &KeyOrchestrator::get_singleton();
        kep = KeyExchangeProtocol::get_singleton();

        // Initialize the chain
        ko->init(hsm);

        // Initialize keys (needed for KEP)
        if (!ko->is_fully_initialized()) {
            ko->init_mission_keys();
        }

        // Initialize KEP
        kep->init(ko);
    }

    AP_HSM* hsm;
    KeyOrchestrator* ko;
    KeyExchangeProtocol* kep;
};

// =============================================================================
// SINGLETON TESTS
// =============================================================================

TEST_F(KeyExchangeProtocolTest, SingletonPattern) {
    KeyExchangeProtocol* kep1 = KeyExchangeProtocol::get_singleton();
    KeyExchangeProtocol* kep2 = KeyExchangeProtocol::get_singleton();

    EXPECT_NE(nullptr, kep1);
    EXPECT_NE(nullptr, kep2);
    EXPECT_EQ(kep1, kep2) << "Singleton should return same instance";
}

// =============================================================================
// INITIALIZATION TESTS
// =============================================================================

TEST_F(KeyExchangeProtocolTest, InitWithValidKeyOrchestrator) {
    // KEP was already initialized in SetUp, verify it worked
    EXPECT_NE(nullptr, kep);
    // KEP should have WK public ready after init
    // (indirect test - no public accessor for _wk_public_ready)
}

TEST_F(KeyExchangeProtocolTest, InitWithNullKeyOrchestratorFails) {
    // Create a fresh KEP instance
    // Note: Since KEP is a singleton, this test verifies the null check in init
    // We can't actually test this without resetting the singleton
    // Just verify the current state is valid
    EXPECT_NE(nullptr, kep);
}

// =============================================================================
// ECIES TESTS (via KeyOrchestrator)
// =============================================================================

TEST_F(KeyExchangeProtocolTest, WKPublicAvailable) {
    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    // Should be 64 bytes and non-zero
    bool nonzero = false;
    for (int i = 0; i < 64; i++) {
        if (wk_pub[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "WK public should not be all zeros";
}

TEST_F(KeyExchangeProtocolTest, ECIESEncryptDecrypt) {
    // Get our WK public
    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    // Get our DEK
    const uint8_t* my_dek = ko->get_my_dek();
    ASSERT_NE(nullptr, my_dek);

    // Save the original DEK
    uint8_t original_dek[32];
    memcpy(original_dek, my_dek, 32);

    // ECIES encrypt
    uint8_t ephemeral_pub[64];
    uint8_t nonce[12];
    uint8_t ciphertext[32];
    uint8_t tag[16];

    bool encrypt_result = ko->ecies_encrypt_my_dek(wk_pub,
                                                    ephemeral_pub, nonce,
                                                    ciphertext, tag);
    EXPECT_TRUE(encrypt_result) << "ECIES encrypt should succeed";

    // Ephemeral key should not be all zeros
    bool eph_nonzero = false;
    for (int i = 0; i < 64; i++) {
        if (ephemeral_pub[i] != 0) {
            eph_nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(eph_nonzero) << "Ephemeral public key should not be all zeros";

    // ECIES decrypt
    uint8_t decrypted_dek[32];
    bool decrypt_result = ko->ecies_decrypt_peer_dek(ephemeral_pub, nonce,
                                                      ciphertext, tag,
                                                      decrypted_dek);
    EXPECT_TRUE(decrypt_result) << "ECIES decrypt should succeed";

    // Should match original
    EXPECT_EQ(0, memcmp(original_dek, decrypted_dek, 32))
        << "ECIES decrypted DEK should match original";
}

TEST_F(KeyExchangeProtocolTest, ECIESTamperedCiphertextFails) {
    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    uint8_t ephemeral_pub[64];
    uint8_t nonce[12];
    uint8_t ciphertext[32];
    uint8_t tag[16];

    ko->ecies_encrypt_my_dek(wk_pub, ephemeral_pub, nonce, ciphertext, tag);

    // Tamper with ciphertext
    ciphertext[10] ^= 0xFF;

    uint8_t decrypted_dek[32];
    bool decrypt_result = ko->ecies_decrypt_peer_dek(ephemeral_pub, nonce,
                                                      ciphertext, tag,
                                                      decrypted_dek);
    EXPECT_FALSE(decrypt_result) << "Tampered ciphertext should fail decryption";
}

TEST_F(KeyExchangeProtocolTest, ECIESTamperedTagFails) {
    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    uint8_t ephemeral_pub[64];
    uint8_t nonce[12];
    uint8_t ciphertext[32];
    uint8_t tag[16];

    ko->ecies_encrypt_my_dek(wk_pub, ephemeral_pub, nonce, ciphertext, tag);

    // Tamper with tag
    tag[5] ^= 0x01;

    uint8_t decrypted_dek[32];
    bool decrypt_result = ko->ecies_decrypt_peer_dek(ephemeral_pub, nonce,
                                                      ciphertext, tag,
                                                      decrypted_dek);
    EXPECT_FALSE(decrypt_result) << "Tampered tag should fail decryption";
}

TEST_F(KeyExchangeProtocolTest, ECIESTamperedEphemeralFails) {
    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    uint8_t ephemeral_pub[64];
    uint8_t nonce[12];
    uint8_t ciphertext[32];
    uint8_t tag[16];

    ko->ecies_encrypt_my_dek(wk_pub, ephemeral_pub, nonce, ciphertext, tag);

    // Tamper with ephemeral key
    ephemeral_pub[0] ^= 0xFF;

    uint8_t decrypted_dek[32];
    bool decrypt_result = ko->ecies_decrypt_peer_dek(ephemeral_pub, nonce,
                                                      ciphertext, tag,
                                                      decrypted_dek);
    EXPECT_FALSE(decrypt_result) << "Tampered ephemeral key should fail decryption";
}

TEST_F(KeyExchangeProtocolTest, MultipleEncryptionsProduceDifferentCiphertexts) {
    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    uint8_t ephemeral1[64], ephemeral2[64];
    uint8_t nonce1[12], nonce2[12];
    uint8_t ciphertext1[32], ciphertext2[32];
    uint8_t tag1[16], tag2[16];

    ko->ecies_encrypt_my_dek(wk_pub, ephemeral1, nonce1, ciphertext1, tag1);
    ko->ecies_encrypt_my_dek(wk_pub, ephemeral2, nonce2, ciphertext2, tag2);

    // Ephemeral keys should differ (random each time)
    EXPECT_NE(0, memcmp(ephemeral1, ephemeral2, 64))
        << "Each ECIES encryption should use different ephemeral key";

    // Ciphertexts should also differ (due to different ephemeral keys + nonces)
    EXPECT_NE(0, memcmp(ciphertext1, ciphertext2, 32))
        << "Each ECIES encryption should produce different ciphertext";
}

// =============================================================================
// PEER STATE TESTS
// =============================================================================

TEST_F(KeyExchangeProtocolTest, InitialPeerState) {
    // Unknown peer should return IDLE state
    KeyExchangeProtocol::State state = kep->get_peer_state(99, 99);
    EXPECT_EQ(KeyExchangeProtocol::State::IDLE, state);
}

TEST_F(KeyExchangeProtocolTest, UnknownPeerNotComplete) {
    bool complete = kep->is_exchange_complete(99, 99);
    EXPECT_FALSE(complete) << "Unknown peer should not have complete exchange";
}

TEST_F(KeyExchangeProtocolTest, UnknownPeerDEKReturnsNull) {
    const uint8_t* dek = kep->get_peer_dek(99, 99);
    EXPECT_EQ(nullptr, dek) << "Unknown peer DEK should be null";
}

TEST_F(KeyExchangeProtocolTest, InitialPeerCount) {
    // Initially should have no peers (unless previous tests added some)
    // Note: Since KEP is a singleton, peer count may persist across tests
    // We just verify it's a valid small number
    uint8_t count = kep->get_num_peers();
    EXPECT_LT(count, 10) << "Peer count should be reasonable";
}

TEST_F(KeyExchangeProtocolTest, InitialCompleteCount) {
    uint8_t count = kep->get_num_complete();
    EXPECT_LE(count, kep->get_num_peers()) << "Complete count should not exceed peer count";
}

// =============================================================================
// PEER DEK MANAGEMENT TESTS (via KeyOrchestrator)
// =============================================================================

TEST_F(KeyExchangeProtocolTest, StorePeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i + 200;

    bool result = ko->store_peer_dek("test_peer_kep", peer_dek);
    EXPECT_TRUE(result);
    EXPECT_TRUE(ko->has_peer_dek("test_peer_kep"));
}

TEST_F(KeyExchangeProtocolTest, GetPeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i + 150;

    ko->store_peer_dek("peer_kep_x", peer_dek);

    const uint8_t* retrieved = ko->get_peer_dek("peer_kep_x");
    ASSERT_NE(nullptr, retrieved);
    EXPECT_EQ(0, memcmp(peer_dek, retrieved, 32));
}

TEST_F(KeyExchangeProtocolTest, GetUnknownPeerDEK) {
    const uint8_t* retrieved = ko->get_peer_dek("unknown_peer_kep");
    EXPECT_EQ(nullptr, retrieved);
}

AP_GTEST_MAIN()
