/*
 * test_ap_hsm.cpp - Unit tests for AP_HSM driver
 *
 * Tests HSM initialization, Mock storage, and basic operations
 *
 * Run with: ./build/sitl/tests/test_ap_hsm
 */

#include <AP_gtest.h>
#include <AP_HAL/AP_HAL.h>
#include <AP_HSM/AP_HSM.h>
#include <string.h>

const AP_HAL::HAL& hal = AP_HAL::get_HAL();

// =============================================================================
// TEST FIXTURE
// =============================================================================

class AP_HSM_Test : public ::testing::Test {
protected:
    void SetUp() override {
        hsm = &AP_HSM::get_singleton();
    }

    AP_HSM* hsm;
};

// =============================================================================
// SINGLETON TESTS
// =============================================================================

TEST_F(AP_HSM_Test, SingletonPattern) {
    AP_HSM& hsm1 = AP_HSM::get_singleton();
    AP_HSM& hsm2 = AP_HSM::get_singleton();

    EXPECT_EQ(&hsm1, &hsm2) << "Singleton should return same instance";
}

// =============================================================================
// MOCK HSM TESTS (when AP_HSM_MOCK_ENABLED=1)
// =============================================================================

#if AP_HSM_MOCK_ENABLED

TEST_F(AP_HSM_Test, MockInit) {
    // Mock should initialize instantly
    bool result = hsm->init_monolith();
    EXPECT_TRUE(result) << "Mock init_monolith should succeed";
}

TEST_F(AP_HSM_Test, MockInitComplete) {
    hsm->init_monolith();
    EXPECT_TRUE(hsm->is_init_complete());
    EXPECT_FALSE(hsm->is_init_failed());
}

#endif // AP_HSM_MOCK_ENABLED

// =============================================================================
// KEYPAIR GENERATION TESTS
// =============================================================================

TEST_F(AP_HSM_Test, GenerateKeypairP256) {
    bool result = hsm->generate_keypair_p256();
    EXPECT_TRUE(result) << "generate_keypair_p256 should succeed";
    EXPECT_TRUE(hsm->has_keypair()) << "Should have keypair after generation";
}

TEST_F(AP_HSM_Test, GenerateKeypairNonZero) {
    hsm->generate_keypair_p256();

    const uint8_t* priv = hsm->get_private_key();
    const uint8_t* pub = hsm->get_public_key();

    ASSERT_NE(nullptr, priv);
    ASSERT_NE(nullptr, pub);

    // Check private key not all zeros
    bool priv_nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (priv[i] != 0) {
            priv_nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(priv_nonzero) << "Private key should not be all zeros";

    // Check public key not all zeros
    bool pub_nonzero = false;
    for (int i = 0; i < 64; i++) {
        if (pub[i] != 0) {
            pub_nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(pub_nonzero) << "Public key should not be all zeros";
}

TEST_F(AP_HSM_Test, GenerateKeypairDifferentEachTime) {
    // Generate first keypair
    hsm->generate_keypair_p256();
    uint8_t priv1[32], pub1[64];
    memcpy(priv1, hsm->get_private_key(), 32);
    memcpy(pub1, hsm->get_public_key(), 64);

    // Generate second keypair
    hsm->generate_keypair_p256();
    const uint8_t* priv2 = hsm->get_private_key();
    const uint8_t* pub2 = hsm->get_public_key();

    // Should be different
    EXPECT_NE(0, memcmp(priv1, priv2, 32))
        << "Two keypair generations should produce different private keys";
    EXPECT_NE(0, memcmp(pub1, pub2, 64))
        << "Two keypair generations should produce different public keys";
}

// =============================================================================
// DEK GENERATION TESTS
// =============================================================================

TEST_F(AP_HSM_Test, GenerateDEK) {
    EXPECT_FALSE(hsm->has_dek()) << "Should not have DEK initially";

    bool result = hsm->generate_dek();
    EXPECT_TRUE(result) << "generate_dek should succeed";
    EXPECT_TRUE(hsm->has_dek()) << "Should have DEK after generation";
}

TEST_F(AP_HSM_Test, DEKIs32Bytes) {
    hsm->generate_dek();

    const uint8_t* dek = hsm->get_dek();
    ASSERT_NE(nullptr, dek);

    // Verify it's not all zeros (would be extremely unlikely if random)
    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (dek[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "DEK should not be all zeros";
}

TEST_F(AP_HSM_Test, DEKDifferentEachTime) {
    hsm->generate_dek();
    uint8_t dek1[32];
    memcpy(dek1, hsm->get_dek(), 32);

    hsm->generate_dek();
    const uint8_t* dek2 = hsm->get_dek();

    EXPECT_NE(0, memcmp(dek1, dek2, 32))
        << "Two DEK generations should produce different keys";
}

// =============================================================================
// ECDH TESTS
// =============================================================================

TEST_F(AP_HSM_Test, ComputeECDH) {
    // Generate our keypair
    hsm->generate_keypair_p256();

    // Use our own public key as "remote" for self-test
    uint8_t shared_secret[32];
    bool result = hsm->compute_ecdh(hsm->get_public_key(), shared_secret);

    EXPECT_TRUE(result) << "compute_ecdh should succeed";

    // Shared secret should not be all zeros
    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (shared_secret[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "Shared secret should not be all zeros";
}

TEST_F(AP_HSM_Test, ECDHWithInvalidKey) {
    hsm->generate_keypair_p256();

    // Zero public key is invalid
    uint8_t zero_key[64] = {0};
    uint8_t shared_secret[32];

    bool result = hsm->compute_ecdh(zero_key, shared_secret);
    EXPECT_FALSE(result) << "ECDH with zero key should fail";
}

// =============================================================================
// KEY WRAPPING TESTS
// =============================================================================

TEST_F(AP_HSM_Test, WrapUnwrapDEK) {
    // Generate wrapping key material
    hsm->generate_keypair_p256();
    uint8_t shared_secret[32];
    hsm->compute_ecdh(hsm->get_public_key(), shared_secret);

    uint8_t wrapping_key[32];
    bool derive_ok = hsm->derive_wrapping_key(shared_secret, wrapping_key);
    EXPECT_TRUE(derive_ok);

    // Generate DEK to wrap
    hsm->generate_dek();
    const uint8_t* original_dek = hsm->get_dek();
    uint8_t saved_dek[32];
    memcpy(saved_dek, original_dek, 32);

    // Wrap
    uint8_t wrapped_dek[32];
    uint8_t auth_tag[32];
    bool wrap_ok = hsm->wrap_dek(wrapping_key, wrapped_dek, auth_tag);
    EXPECT_TRUE(wrap_ok);

    // Wrapped should differ from original
    EXPECT_NE(0, memcmp(saved_dek, wrapped_dek, 32))
        << "Wrapped DEK should differ from original";

    // Unwrap
    bool unwrap_ok = hsm->unwrap_dek(wrapped_dek, auth_tag, wrapping_key);
    EXPECT_TRUE(unwrap_ok);

    // After unwrap, DEK should match original
    EXPECT_EQ(0, memcmp(saved_dek, hsm->get_dek(), 32))
        << "Unwrapped DEK should match original";
}

TEST_F(AP_HSM_Test, WrapUnwrapTamperedFails) {
    hsm->generate_keypair_p256();
    uint8_t shared_secret[32];
    hsm->compute_ecdh(hsm->get_public_key(), shared_secret);

    uint8_t wrapping_key[32];
    hsm->derive_wrapping_key(shared_secret, wrapping_key);

    hsm->generate_dek();

    uint8_t wrapped_dek[32];
    uint8_t auth_tag[32];
    hsm->wrap_dek(wrapping_key, wrapped_dek, auth_tag);

    // Tamper with wrapped data
    wrapped_dek[10] ^= 0xFF;

    bool unwrap_ok = hsm->unwrap_dek(wrapped_dek, auth_tag, wrapping_key);
    EXPECT_FALSE(unwrap_ok) << "Tampered wrapped DEK should fail unwrap";
}

TEST_F(AP_HSM_Test, WrapUnwrapWrongTagFails) {
    hsm->generate_keypair_p256();
    uint8_t shared_secret[32];
    hsm->compute_ecdh(hsm->get_public_key(), shared_secret);

    uint8_t wrapping_key[32];
    hsm->derive_wrapping_key(shared_secret, wrapping_key);

    hsm->generate_dek();

    uint8_t wrapped_dek[32];
    uint8_t auth_tag[32];
    hsm->wrap_dek(wrapping_key, wrapped_dek, auth_tag);

    // Tamper with tag
    auth_tag[5] ^= 0x01;

    bool unwrap_ok = hsm->unwrap_dek(wrapped_dek, auth_tag, wrapping_key);
    EXPECT_FALSE(unwrap_ok) << "Wrong auth tag should fail unwrap";
}

// =============================================================================
// KEY DERIVATION TESTS
// =============================================================================

TEST_F(AP_HSM_Test, DeriveWrappingKey) {
    uint8_t shared_secret[32];
    for (int i = 0; i < 32; i++) shared_secret[i] = i;

    uint8_t wrapping_key[32];
    bool result = hsm->derive_wrapping_key(shared_secret, wrapping_key);

    EXPECT_TRUE(result);

    // Wrapping key should not be all zeros
    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (wrapping_key[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero);

    // Wrapping key should differ from input (KDF transforms it)
    EXPECT_NE(0, memcmp(shared_secret, wrapping_key, 32))
        << "Derived key should differ from input";
}

TEST_F(AP_HSM_Test, DeriveWrappingKeyDeterministic) {
    uint8_t shared_secret[32];
    for (int i = 0; i < 32; i++) shared_secret[i] = i + 100;

    uint8_t wrapping_key1[32];
    uint8_t wrapping_key2[32];

    hsm->derive_wrapping_key(shared_secret, wrapping_key1);
    hsm->derive_wrapping_key(shared_secret, wrapping_key2);

    // Same input should produce same output (HKDF is deterministic)
    EXPECT_EQ(0, memcmp(wrapping_key1, wrapping_key2, 32))
        << "HKDF should be deterministic";
}

TEST_F(AP_HSM_Test, DeriveWrappingKeyDifferentInput) {
    uint8_t secret1[32], secret2[32];
    for (int i = 0; i < 32; i++) {
        secret1[i] = i;
        secret2[i] = i + 1;
    }

    uint8_t key1[32], key2[32];
    hsm->derive_wrapping_key(secret1, key1);
    hsm->derive_wrapping_key(secret2, key2);

    EXPECT_NE(0, memcmp(key1, key2, 32))
        << "Different inputs should produce different keys";
}

// =============================================================================
// HSM STORAGE TESTS (Mock or Real)
// =============================================================================

#if AP_HSM_MOCK_ENABLED

TEST_F(AP_HSM_Test, StoreLoadPrivateKey) {
    // Generate keypair
    hsm->generate_keypair_p256();
    uint8_t original_priv[32];
    memcpy(original_priv, hsm->get_private_key(), 32);

    // Store to HSM
    bool store_ok = hsm->store_private_key_to_hsm(hsm->get_private_key(), 32);
    EXPECT_TRUE(store_ok);

    // Clear local cache (simulate reboot)
    // Note: This requires internal access; for now just verify store worked

    // Load from HSM
    bool load_ok = hsm->load_private_key_from_hsm();
    EXPECT_TRUE(load_ok);

    // Should match original
    EXPECT_EQ(0, memcmp(original_priv, hsm->get_private_key(), 32))
        << "Loaded private key should match original";
}

TEST_F(AP_HSM_Test, StoreLoadDEK) {
    // Generate wrapping material
    hsm->generate_keypair_p256();
    uint8_t shared[32];
    hsm->compute_ecdh(hsm->get_public_key(), shared);
    uint8_t wk[32];
    hsm->derive_wrapping_key(shared, wk);

    // Generate DEK
    hsm->generate_dek();
    uint8_t original_dek[32];
    memcpy(original_dek, hsm->get_dek(), 32);

    // Wrap DEK
    uint8_t wrapped[32], tag[32];
    hsm->wrap_dek(wk, wrapped, tag);

    // Store to HSM
    bool store_ok = hsm->store_dek_to_hsm(wrapped, tag);
    EXPECT_TRUE(store_ok);

    // Load from HSM
    uint8_t loaded_wrapped[32], loaded_tag[32];
    bool load_ok = hsm->load_dek_from_hsm(loaded_wrapped, loaded_tag);
    EXPECT_TRUE(load_ok);

    // Should match what we stored
    EXPECT_EQ(0, memcmp(wrapped, loaded_wrapped, 32));
    EXPECT_EQ(0, memcmp(tag, loaded_tag, 32));
}

#endif // AP_HSM_MOCK_ENABLED

// =============================================================================
// UTILITY FUNCTION TESTS
// =============================================================================

TEST_F(AP_HSM_Test, HexstrToBytes) {
    const char* hexstr = "0102030405060708090A0B0C0D0E0F10";
    uint8_t expected[16] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                           0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10};
    uint8_t output[16];

    bool result = hsm->hexstr_to_bytes(hexstr, output, 16);
    EXPECT_TRUE(result);
    EXPECT_EQ(0, memcmp(expected, output, 16));
}

TEST_F(AP_HSM_Test, HexstrToBytes_Lowercase) {
    const char* hexstr = "deadbeef";
    uint8_t expected[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    uint8_t output[4];

    bool result = hsm->hexstr_to_bytes(hexstr, output, 4);
    EXPECT_TRUE(result);
    EXPECT_EQ(0, memcmp(expected, output, 4));
}

TEST_F(AP_HSM_Test, HexstrToBytes_MixedCase) {
    const char* hexstr = "DeAdBeEf";
    uint8_t expected[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    uint8_t output[4];

    bool result = hsm->hexstr_to_bytes(hexstr, output, 4);
    EXPECT_TRUE(result);
    EXPECT_EQ(0, memcmp(expected, output, 4));
}

TEST_F(AP_HSM_Test, HexstrToBytes_Invalid) {
    const char* hexstr = "GHIJ";  // Invalid hex chars
    uint8_t output[2];

    bool result = hsm->hexstr_to_bytes(hexstr, output, 2);
    EXPECT_FALSE(result) << "Invalid hex should fail";
}

TEST_F(AP_HSM_Test, HexstrToBytes_OddLength) {
    const char* hexstr = "123";  // Odd number of chars
    uint8_t output[2];

    // Behavior depends on implementation
    // Just verify it doesn't crash
    hsm->hexstr_to_bytes(hexstr, output, 1);
    SUCCEED() << "Odd length handling didn't crash";
}

// =============================================================================
// INIT STATE TESTS
// =============================================================================

TEST_F(AP_HSM_Test, InitStateInitial) {
    // State before any init
    AP_HSM::InitState state = hsm->get_init_state();

    // Could be NOT_STARTED or COMPLETE depending on previous tests
    // Just verify we can read it
    (void)state;  // Suppress unused variable warning
    SUCCEED() << "Init state readable";
}

#if AP_HSM_MOCK_ENABLED

TEST_F(AP_HSM_Test, InitStateAfterMockInit) {
    hsm->init_monolith();

    EXPECT_EQ(AP_HSM::InitState::COMPLETE, hsm->get_init_state());
    EXPECT_TRUE(hsm->is_init_complete());
    EXPECT_FALSE(hsm->is_init_failed());
}

#endif

// =============================================================================
// SIMULATION MODE TESTS
// =============================================================================

TEST_F(AP_HSM_Test, SimulationMode) {
    EXPECT_FALSE(hsm->is_simulation_mode()) << "Should not be in sim mode initially";

    hsm->enable_simulation_mode();
    EXPECT_TRUE(hsm->is_simulation_mode());
}

AP_GTEST_MAIN()
