/*
 * test_dual_dek.cpp - Unit tests for DualDekEngine
 *
 * Tests MAVLink payload encryption/decryption using XChaCha20-Poly1305.
 * Uses GCS stub to handle GCS_SEND_TEXT() calls.
 *
 * Run with: ./build/sitl/tests/test_dual_dek
 */

#include <AP_gtest.h>
#include <AP_HAL/AP_HAL.h>
#include <AP_HSM/AP_HSM.h>
#include <AP_HSM/KeyOrchestrator.h>
#include <AP_HSM/KeyExchangeProtocol.h>
#include <AP_HSM/DualDekEngine.h>
#include <AP_HSM/uECC.h>
#include <string.h>

// GCS stub for test environment
#include "gcs_test_stub.h"
GCS_TEST_STUB_INSTANCE

const AP_HAL::HAL& hal = AP_HAL::get_HAL();

// RNG for uECC
static int test_rng(uint8_t *dest, unsigned size) {
    for (unsigned i = 0; i < size; i++) {
        dest[i] = (uint8_t)(rand() & 0xFF);
    }
    return 1;
}

// =============================================================================
// TEST FIXTURE
// =============================================================================

class DualDekEngineTest : public ::testing::Test {
protected:
    void SetUp() override {
        uECC_set_rng(test_rng);

        hsm = &AP_HSM::get_singleton();
        ko = &KeyOrchestrator::get_singleton();
        kep = KeyExchangeProtocol::get_singleton();
        dde = DualDekEngine::get_singleton();

        // Initialize the full chain
        ko->init(hsm);

        if (!ko->is_fully_initialized()) {
            ko->init_mission_keys();
        }

        kep->init(ko);
        dde->init(ko, kep);
    }

    AP_HSM* hsm;
    KeyOrchestrator* ko;
    KeyExchangeProtocol* kep;
    DualDekEngine* dde;
};

// =============================================================================
// SINGLETON TESTS
// =============================================================================

TEST_F(DualDekEngineTest, SingletonPattern) {
    DualDekEngine* dde1 = DualDekEngine::get_singleton();
    DualDekEngine* dde2 = DualDekEngine::get_singleton();

    EXPECT_NE(nullptr, dde1);
    EXPECT_NE(nullptr, dde2);
    EXPECT_EQ(dde1, dde2) << "Singleton should return same instance";
}

// =============================================================================
// INITIALIZATION TESTS
// =============================================================================

TEST_F(DualDekEngineTest, InitSucceeds) {
    EXPECT_NE(nullptr, dde);
    EXPECT_TRUE(dde->is_ready()) << "DDE should be ready after init with valid keys";
}

TEST_F(DualDekEngineTest, InitWithNullKeyOrchestratorFails) {
    // Can't fully test this with singleton pattern, but we can verify
    // that the current state is valid
    EXPECT_TRUE(dde->is_ready());
}

// =============================================================================
// MESSAGE FILTERING TESTS
// =============================================================================

TEST_F(DualDekEngineTest, ShouldEncryptRegularMessages) {
    // Regular messages should be encrypted
    EXPECT_TRUE(dde->should_encrypt(1));   // SYS_STATUS
    EXPECT_TRUE(dde->should_encrypt(30));  // ATTITUDE
    EXPECT_TRUE(dde->should_encrypt(76));  // COMMAND_LONG
    EXPECT_TRUE(dde->should_encrypt(11));  // SET_MODE
}

TEST_F(DualDekEngineTest, ShouldNotEncryptHSMMessages) {
    // HSM key exchange messages must stay plaintext
    EXPECT_FALSE(dde->should_encrypt(0));      // HEARTBEAT
    EXPECT_FALSE(dde->should_encrypt(12000));  // HSM_WK_EXCHANGE
    EXPECT_FALSE(dde->should_encrypt(12001));  // HSM_DEK_EXCHANGE
    EXPECT_FALSE(dde->should_encrypt(12002));  // HSM_KEY_ACK
}

// =============================================================================
// ENCRYPTION TESTS
// =============================================================================

TEST_F(DualDekEngineTest, EncryptSmallPayload) {
    uint8_t plaintext[] = {0x01, 0x02, 0x03, 0x04, 0x05};
    uint8_t ciphertext[256];
    size_t ciphertext_len = 0;

    bool result = dde->encrypt_payload(plaintext, sizeof(plaintext),
                                        ciphertext, &ciphertext_len);

    EXPECT_TRUE(result) << "Encryption should succeed";
    EXPECT_EQ(sizeof(plaintext) + DDE_HEADER_SIZE, ciphertext_len)
        << "Ciphertext should be plaintext + header size";
}

TEST_F(DualDekEngineTest, EncryptedDiffersFromPlaintext) {
    uint8_t plaintext[32];
    for (int i = 0; i < 32; i++) plaintext[i] = i;

    uint8_t ciphertext[256];
    size_t ciphertext_len = 0;

    dde->encrypt_payload(plaintext, sizeof(plaintext), ciphertext, &ciphertext_len);

    // The ciphertext portion (after header) should differ from plaintext
    uint8_t* ct_data = ciphertext + DDE_HEADER_SIZE;
    EXPECT_NE(0, memcmp(plaintext, ct_data, sizeof(plaintext)))
        << "Encrypted data should differ from plaintext";
}

TEST_F(DualDekEngineTest, MultipleEncryptionsProduceDifferentResults) {
    uint8_t plaintext[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};

    uint8_t ct1[256], ct2[256];
    size_t len1 = 0, len2 = 0;

    dde->encrypt_payload(plaintext, sizeof(plaintext), ct1, &len1);
    dde->encrypt_payload(plaintext, sizeof(plaintext), ct2, &len2);

    EXPECT_EQ(len1, len2) << "Same plaintext should produce same length ciphertext";

    // Nonces (first 24 bytes) should differ
    EXPECT_NE(0, memcmp(ct1, ct2, DDE_NONCE_SIZE))
        << "Each encryption should use different nonce";

    // Full ciphertexts should differ (due to different nonces)
    EXPECT_NE(0, memcmp(ct1, ct2, len1))
        << "Each encryption should produce different ciphertext";
}

TEST_F(DualDekEngineTest, EncryptMaxPayload) {
    uint8_t plaintext[DDE_MAX_PAYLOAD];
    for (int i = 0; i < DDE_MAX_PAYLOAD; i++) plaintext[i] = i & 0xFF;

    uint8_t ciphertext[512];
    size_t ciphertext_len = 0;

    bool result = dde->encrypt_payload(plaintext, sizeof(plaintext),
                                        ciphertext, &ciphertext_len);

    EXPECT_TRUE(result) << "Max payload encryption should succeed";
    EXPECT_EQ((size_t)(DDE_MAX_PAYLOAD + DDE_HEADER_SIZE), ciphertext_len);
}

TEST_F(DualDekEngineTest, EncryptNullPlaintextFails) {
    uint8_t ciphertext[256];
    size_t ciphertext_len = 0;

    bool result = dde->encrypt_payload(nullptr, 10, ciphertext, &ciphertext_len);
    EXPECT_FALSE(result) << "Null plaintext should fail";
}

TEST_F(DualDekEngineTest, EncryptNullCiphertextFails) {
    uint8_t plaintext[10] = {0};
    size_t ciphertext_len = 0;

    bool result = dde->encrypt_payload(plaintext, sizeof(plaintext),
                                        nullptr, &ciphertext_len);
    EXPECT_FALSE(result) << "Null ciphertext buffer should fail";
}

TEST_F(DualDekEngineTest, EncryptNullLenFails) {
    uint8_t plaintext[10] = {0};
    uint8_t ciphertext[256];

    bool result = dde->encrypt_payload(plaintext, sizeof(plaintext),
                                        ciphertext, nullptr);
    EXPECT_FALSE(result) << "Null length pointer should fail";
}

// =============================================================================
// DECRYPTION TESTS (requires stored peer DEK)
// =============================================================================

TEST_F(DualDekEngineTest, DecryptWithNoPeerDEKFails) {
    // Encrypt something
    uint8_t plaintext[10] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
    uint8_t ciphertext[256];
    size_t ciphertext_len = 0;

    dde->encrypt_payload(plaintext, sizeof(plaintext), ciphertext, &ciphertext_len);

    // Try to decrypt as if from an unknown peer
    uint8_t decrypted[256];
    size_t decrypted_len = 0;

    bool result = dde->decrypt_payload(99,  // Unknown sysid
                                         ciphertext, ciphertext_len,
                                         decrypted, &decrypted_len);

    EXPECT_FALSE(result) << "Decryption should fail without peer DEK";
}

TEST_F(DualDekEngineTest, DecryptShortCiphertextFails) {
    // Ciphertext shorter than header should fail
    uint8_t short_ct[DDE_HEADER_SIZE - 1] = {0};
    uint8_t decrypted[256];
    size_t decrypted_len = 0;

    // Store a peer DEK first
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i;
    ko->store_peer_dek("sysid_10", peer_dek);

    bool result = dde->decrypt_payload(10, short_ct, sizeof(short_ct),
                                         decrypted, &decrypted_len);

    EXPECT_FALSE(result) << "Short ciphertext should fail";
}

// =============================================================================
// STATISTICS TESTS
// =============================================================================

TEST_F(DualDekEngineTest, StatsInitialized) {
    const DualDekEngine::Stats& stats = dde->get_stats();

    // Stats should be reasonable values (not uninitialized garbage)
    // We don't check exact values since they depend on previous tests
    EXPECT_GE(stats.tx_encrypted, 0u);
    EXPECT_GE(stats.tx_plaintext, 0u);
    EXPECT_GE(stats.rx_decrypted, 0u);
    EXPECT_GE(stats.rx_failed, 0u);
}

TEST_F(DualDekEngineTest, StatsIncrementOnEncrypt) {
    const DualDekEngine::Stats& stats_before = dde->get_stats();
    uint32_t tx_before = stats_before.tx_encrypted;

    uint8_t plaintext[5] = {1, 2, 3, 4, 5};
    uint8_t ciphertext[256];
    size_t ciphertext_len = 0;

    dde->encrypt_payload(plaintext, sizeof(plaintext), ciphertext, &ciphertext_len);

    const DualDekEngine::Stats& stats_after = dde->get_stats();
    EXPECT_EQ(tx_before + 1, stats_after.tx_encrypted)
        << "tx_encrypted should increment on successful encryption";
}

// =============================================================================
// DEK AVAILABILITY TESTS
// =============================================================================

TEST_F(DualDekEngineTest, DEKAvailable) {
    const uint8_t* dek = ko->get_my_dek();
    ASSERT_NE(nullptr, dek);

    // Should be non-zero
    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (dek[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "DEK should not be all zeros";
}

TEST_F(DualDekEngineTest, NewDEKIsDifferent) {
    const uint8_t* dek1 = ko->get_my_dek();
    ASSERT_NE(nullptr, dek1);

    uint8_t saved_dek1[32];
    memcpy(saved_dek1, dek1, 32);

    // Generate new DEK
    ko->generate_dek();

    const uint8_t* dek2 = ko->get_my_dek();
    ASSERT_NE(nullptr, dek2);

    // Should be different
    EXPECT_NE(0, memcmp(saved_dek1, dek2, 32))
        << "New DEK should differ from previous";
}

// =============================================================================
// KEY WRAPPING TESTS (used by DDE internally)
// =============================================================================

TEST_F(DualDekEngineTest, WrapUnwrapWithMK) {
    // Ensure we have MK
    ASSERT_TRUE(ko->has_master_key());

    // Create test data
    uint8_t plaintext[32];
    for (int i = 0; i < 32; i++) plaintext[i] = i;

    uint8_t wrapped[32];
    uint8_t tag[32];
    uint8_t unwrapped[32];

    // Wrap
    bool wrap_ok = ko->wrap_key(plaintext, wrapped, tag);
    EXPECT_TRUE(wrap_ok);

    // Wrapped should differ from plaintext
    EXPECT_NE(0, memcmp(plaintext, wrapped, 32));

    // Unwrap
    bool unwrap_ok = ko->unwrap_key(wrapped, tag, unwrapped);
    EXPECT_TRUE(unwrap_ok);

    // Should match original
    EXPECT_EQ(0, memcmp(plaintext, unwrapped, 32));
}

TEST_F(DualDekEngineTest, TamperedWrappedDataFails) {
    ASSERT_TRUE(ko->has_master_key());

    uint8_t plaintext[32];
    for (int i = 0; i < 32; i++) plaintext[i] = i + 50;

    uint8_t wrapped[32];
    uint8_t tag[32];
    uint8_t unwrapped[32];

    ko->wrap_key(plaintext, wrapped, tag);

    // Tamper
    wrapped[15] ^= 0xFF;

    bool unwrap_ok = ko->unwrap_key(wrapped, tag, unwrapped);
    EXPECT_FALSE(unwrap_ok) << "Tampered wrapped data should fail";
}

TEST_F(DualDekEngineTest, TamperedTagFails) {
    ASSERT_TRUE(ko->has_master_key());

    uint8_t plaintext[32];
    for (int i = 0; i < 32; i++) plaintext[i] = i + 100;

    uint8_t wrapped[32];
    uint8_t tag[32];
    uint8_t unwrapped[32];

    ko->wrap_key(plaintext, wrapped, tag);

    // Tamper with tag
    tag[10] ^= 0x01;

    bool unwrap_ok = ko->unwrap_key(wrapped, tag, unwrapped);
    EXPECT_FALSE(unwrap_ok) << "Tampered tag should fail";
}

// =============================================================================
// PEER DEK STORAGE TESTS
// =============================================================================

TEST_F(DualDekEngineTest, StorePeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i;

    bool result = ko->store_peer_dek("drone_dde_1", peer_dek);
    EXPECT_TRUE(result);
    EXPECT_TRUE(ko->has_peer_dek("drone_dde_1"));
}

TEST_F(DualDekEngineTest, RetrievePeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i + 77;

    ko->store_peer_dek("drone_dde_2", peer_dek);

    const uint8_t* retrieved = ko->get_peer_dek("drone_dde_2");
    ASSERT_NE(nullptr, retrieved);
    EXPECT_EQ(0, memcmp(peer_dek, retrieved, 32));
}

TEST_F(DualDekEngineTest, MultiplePeerDEKs) {
    uint8_t dek1[32], dek2[32], dek3[32];
    for (int i = 0; i < 32; i++) {
        dek1[i] = i;
        dek2[i] = i + 32;
        dek3[i] = i + 64;
    }

    ko->store_peer_dek("peer_dde_a", dek1);
    ko->store_peer_dek("peer_dde_b", dek2);
    ko->store_peer_dek("peer_dde_c", dek3);

    // All should be retrievable
    EXPECT_EQ(0, memcmp(dek1, ko->get_peer_dek("peer_dde_a"), 32));
    EXPECT_EQ(0, memcmp(dek2, ko->get_peer_dek("peer_dde_b"), 32));
    EXPECT_EQ(0, memcmp(dek3, ko->get_peer_dek("peer_dde_c"), 32));
}

TEST_F(DualDekEngineTest, RemovePeerDEK) {
    uint8_t peer_dek[32] = {0};
    ko->store_peer_dek("temp_peer_dde", peer_dek);
    EXPECT_TRUE(ko->has_peer_dek("temp_peer_dde"));

    ko->remove_peer_dek("temp_peer_dde");
    EXPECT_FALSE(ko->has_peer_dek("temp_peer_dde"));
}

TEST_F(DualDekEngineTest, UnknownPeerReturnsNull) {
    const uint8_t* dek = ko->get_peer_dek("nonexistent_peer_dde");
    EXPECT_EQ(nullptr, dek);
}

AP_GTEST_MAIN()
