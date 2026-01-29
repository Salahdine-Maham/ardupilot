/*
 * test_key_orchestrator.cpp - Unit tests for KeyOrchestrator
 *
 * Tests the 3-level key hierarchy: MK → WK → DEK
 *
 * Run with: ./build/sitl/tests/test_key_orchestrator
 */

#include <AP_gtest.h>
#include <AP_HAL/AP_HAL.h>
#include <AP_HSM/AP_HSM.h>
#include <AP_HSM/KeyOrchestrator.h>
#include <AP_HSM/uECC.h>
#include <string.h>

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

class KeyOrchestratorTest : public ::testing::Test {
protected:
    void SetUp() override {
        // CRITICAL: Set up RNG for uECC BEFORE any elliptic curve operations
        uECC_set_rng(test_rng);

        // Get singletons
        hsm = &AP_HSM::get_singleton();
        ko = &KeyOrchestrator::get_singleton();

        // Initialize HSM in mock mode (no real hardware needed)
        ko->init(hsm);
    }

    AP_HSM* hsm;
    KeyOrchestrator* ko;
};

// =============================================================================
// SINGLETON TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, SingletonPattern) {
    KeyOrchestrator& ko1 = KeyOrchestrator::get_singleton();
    KeyOrchestrator& ko2 = KeyOrchestrator::get_singleton();
    KeyOrchestrator& ko3 = KeyOrchestrator::get_instance();  // Alias

    EXPECT_EQ(&ko1, &ko2) << "Singleton should return same instance";
    EXPECT_EQ(&ko1, &ko3) << "get_instance() should be alias for get_singleton()";
}

// =============================================================================
// MASTER KEY (MK) TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, GenerateMasterKey) {
    bool result = ko->generate_master_key();
    EXPECT_TRUE(result) << "generate_master_key should succeed";
    EXPECT_TRUE(ko->has_master_key()) << "Should have MK after generation";
}

TEST_F(KeyOrchestratorTest, StoreMKToHSM) {
    ko->generate_master_key();

    bool result = ko->store_mk_to_hsm();
    EXPECT_TRUE(result) << "store_mk_to_hsm should succeed";
}

// =============================================================================
// WRAPPER KEY (WK) TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, DeriveWrapperKey) {
    // Need MK first
    ko->generate_master_key();

    bool result = ko->derive_wrapper_key();
    EXPECT_TRUE(result) << "derive_wrapper_key should succeed";
    EXPECT_TRUE(ko->has_wrapper_key()) << "Should have WK after derivation";
}

TEST_F(KeyOrchestratorTest, DeriveWrapperKeyWithoutMK_Fails) {
    // Clear any existing state
    ko->secure_erase_all();
    EXPECT_FALSE(ko->has_master_key());

    bool result = ko->derive_wrapper_key();
    EXPECT_FALSE(result) << "derive_wrapper_key should fail without MK";
}

TEST_F(KeyOrchestratorTest, ComputeWKPublic) {
    ko->generate_master_key();
    ko->derive_wrapper_key();

    bool result = ko->compute_wk_public();
    EXPECT_TRUE(result) << "compute_wk_public should succeed";

    const uint8_t* wk_pub = ko->get_wk_public();
    EXPECT_NE(nullptr, wk_pub) << "WK public should not be null";

    // Check it's not all zeros
    bool nonzero = false;
    for (int i = 0; i < 64; i++) {
        if (wk_pub[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "WK public should not be all zeros";
}

TEST_F(KeyOrchestratorTest, WKPublicIs64Bytes) {
    ko->generate_master_key();
    ko->derive_wrapper_key();
    ko->compute_wk_public();

    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    // Verify it's a valid P-256 public key format (64 bytes X||Y)
    bool x_nonzero = false, y_nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (wk_pub[i] != 0) x_nonzero = true;
        if (wk_pub[32 + i] != 0) y_nonzero = true;
    }
    EXPECT_TRUE(x_nonzero) << "X coordinate should not be zero";
    EXPECT_TRUE(y_nonzero) << "Y coordinate should not be zero";
}

TEST_F(KeyOrchestratorTest, DeterministicWKDerivation) {
    // Same MK should derive same WK (HKDF is deterministic)
    ko->generate_master_key();
    ko->derive_wrapper_key();
    ko->compute_wk_public();

    const uint8_t* wk_pub = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub);

    uint8_t wk_pub1[64];
    memcpy(wk_pub1, wk_pub, 64);

    // Re-derive without changing MK
    ko->derive_wrapper_key();
    ko->compute_wk_public();

    const uint8_t* wk_pub2 = ko->get_wk_public();
    ASSERT_NE(nullptr, wk_pub2);

    EXPECT_EQ(0, memcmp(wk_pub1, wk_pub2, 64))
        << "Same MK should derive same WK (HKDF is deterministic)";
}

// =============================================================================
// DATA ENCRYPTION KEY (DEK) TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, GenerateDEK) {
    bool result = ko->generate_dek();
    EXPECT_TRUE(result) << "generate_dek should succeed";
    EXPECT_TRUE(ko->has_dek()) << "Should have DEK after generation";
}

TEST_F(KeyOrchestratorTest, DEKIsRandom) {
    // Generate two DEKs and verify they're different
    ko->generate_dek();
    const uint8_t* dek1 = ko->get_my_dek();
    ASSERT_NE(nullptr, dek1);

    uint8_t saved_dek1[32];
    memcpy(saved_dek1, dek1, 32);

    ko->generate_dek();  // Generate new one
    const uint8_t* dek2 = ko->get_my_dek();
    ASSERT_NE(nullptr, dek2);

    EXPECT_NE(0, memcmp(saved_dek1, dek2, 32))
        << "Two DEK generations should produce different keys";
}

TEST_F(KeyOrchestratorTest, DEKNonZero) {
    ko->generate_dek();
    const uint8_t* dek = ko->get_my_dek();
    ASSERT_NE(nullptr, dek);

    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (dek[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "DEK should not be all zeros";
}

// =============================================================================
// WRAPPING / UNWRAPPING TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, WrapUnwrapKey) {
    // Need MK for wrapping
    ko->generate_master_key();

    // Test key to wrap
    uint8_t test_key[32];
    for (int i = 0; i < 32; i++) test_key[i] = i;

    uint8_t wrapped[32];
    uint8_t tag[32];
    uint8_t unwrapped[32];

    // Wrap
    bool wrap_result = ko->wrap_key(test_key, wrapped, tag);
    EXPECT_TRUE(wrap_result);

    // Wrapped should be different from original
    EXPECT_NE(0, memcmp(test_key, wrapped, 32))
        << "Wrapped key should differ from original";

    // Unwrap
    bool unwrap_result = ko->unwrap_key(wrapped, tag, unwrapped);
    EXPECT_TRUE(unwrap_result);

    // Should match original
    EXPECT_EQ(0, memcmp(test_key, unwrapped, 32))
        << "Unwrapped key should match original";
}

TEST_F(KeyOrchestratorTest, WrapUnwrap_TamperedDataFails) {
    ko->generate_master_key();

    uint8_t test_key[32];
    for (int i = 0; i < 32; i++) test_key[i] = i;

    uint8_t wrapped[32];
    uint8_t tag[32];
    uint8_t unwrapped[32];

    ko->wrap_key(test_key, wrapped, tag);

    // Tamper with wrapped data
    wrapped[10] ^= 0xFF;

    // Unwrap should fail (HMAC verification)
    bool unwrap_result = ko->unwrap_key(wrapped, tag, unwrapped);
    EXPECT_FALSE(unwrap_result) << "Tampered data should fail unwrap";
}

TEST_F(KeyOrchestratorTest, WrapUnwrap_TamperedTagFails) {
    ko->generate_master_key();

    uint8_t test_key[32];
    for (int i = 0; i < 32; i++) test_key[i] = i;

    uint8_t wrapped[32];
    uint8_t tag[32];
    uint8_t unwrapped[32];

    ko->wrap_key(test_key, wrapped, tag);

    // Tamper with tag
    tag[5] ^= 0x01;

    // Unwrap should fail
    bool unwrap_result = ko->unwrap_key(wrapped, tag, unwrapped);
    EXPECT_FALSE(unwrap_result) << "Tampered tag should fail unwrap";
}

// =============================================================================
// PEER DEK MANAGEMENT TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, StorePeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i + 100;

    bool result = ko->store_peer_dek("peer1", peer_dek);
    EXPECT_TRUE(result);
    EXPECT_TRUE(ko->has_peer_dek("peer1"));
}

TEST_F(KeyOrchestratorTest, GetPeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i + 100;

    ko->store_peer_dek("peer1", peer_dek);

    const uint8_t* retrieved = ko->get_peer_dek("peer1");
    ASSERT_NE(nullptr, retrieved);
    EXPECT_EQ(0, memcmp(peer_dek, retrieved, 32));
}

TEST_F(KeyOrchestratorTest, GetPeerDEK_NotFound) {
    const uint8_t* retrieved = ko->get_peer_dek("nonexistent");
    EXPECT_EQ(nullptr, retrieved);
}

TEST_F(KeyOrchestratorTest, RemovePeerDEK) {
    uint8_t peer_dek[32];
    for (int i = 0; i < 32; i++) peer_dek[i] = i;

    ko->store_peer_dek("peer1", peer_dek);
    EXPECT_TRUE(ko->has_peer_dek("peer1"));

    bool result = ko->remove_peer_dek("peer1");
    EXPECT_TRUE(result);
    EXPECT_FALSE(ko->has_peer_dek("peer1"));
}

TEST_F(KeyOrchestratorTest, MultiplePeers) {
    uint8_t dek1[32], dek2[32], dek3[32];
    for (int i = 0; i < 32; i++) {
        dek1[i] = i;
        dek2[i] = i + 50;
        dek3[i] = i + 100;
    }

    ko->store_peer_dek("peer1", dek1);
    ko->store_peer_dek("peer2", dek2);
    ko->store_peer_dek("peer3", dek3);

    EXPECT_TRUE(ko->has_peer_dek("peer1"));
    EXPECT_TRUE(ko->has_peer_dek("peer2"));
    EXPECT_TRUE(ko->has_peer_dek("peer3"));

    // Verify each has correct DEK
    EXPECT_EQ(0, memcmp(dek1, ko->get_peer_dek("peer1"), 32));
    EXPECT_EQ(0, memcmp(dek2, ko->get_peer_dek("peer2"), 32));
    EXPECT_EQ(0, memcmp(dek3, ko->get_peer_dek("peer3"), 32));
}

// =============================================================================
// MISSION LIFECYCLE TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, InitMissionKeys) {
    bool result = ko->init_mission_keys();
    EXPECT_TRUE(result) << "init_mission_keys should succeed";

    EXPECT_TRUE(ko->is_fully_initialized());
    EXPECT_TRUE(ko->has_master_key());
    EXPECT_TRUE(ko->has_wrapper_key());
    EXPECT_TRUE(ko->has_dek());
    EXPECT_NE(nullptr, ko->get_wk_public());
    EXPECT_NE(nullptr, ko->get_my_dek());
}

// =============================================================================
// SECURITY TESTS
// =============================================================================

TEST_F(KeyOrchestratorTest, SecureEraseAll) {
    // Initialize everything
    ko->init_mission_keys();
    ko->store_peer_dek("peer1", ko->get_my_dek());

    EXPECT_TRUE(ko->is_fully_initialized());

    // Erase
    ko->secure_erase_all();

    // Everything should be gone
    EXPECT_FALSE(ko->has_master_key());
    EXPECT_FALSE(ko->has_wrapper_key());
    EXPECT_FALSE(ko->has_dek());
    EXPECT_EQ(nullptr, ko->get_wk_public());
    EXPECT_EQ(nullptr, ko->get_my_dek());
    EXPECT_EQ(0, ko->get_peer_count());
}

TEST_F(KeyOrchestratorTest, Stats) {
    ko->init_mission_keys();

    KeyOrchestrator::Stats stats = ko->get_stats();

    EXPECT_TRUE(stats.mk_loaded);
    EXPECT_TRUE(stats.wk_loaded);
    EXPECT_TRUE(stats.dek_loaded);
}

AP_GTEST_MAIN()
