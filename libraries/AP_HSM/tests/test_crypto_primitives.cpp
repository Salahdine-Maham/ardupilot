/*
 * test_crypto_primitives.cpp - Unit tests for HSM crypto primitives
 *
 * Tests micro-ecc (P-256) elliptic curve operations
 * Note: Monocypher tests are done through DualDekEngine integration tests
 *
 * Run with: ./build/sitl/tests/test_crypto_primitives
 */

#include <AP_gtest.h>
#include <AP_HAL/AP_HAL.h>
#include <string.h>

// Include crypto libraries
#include <AP_HSM/uECC.h>

const AP_HAL::HAL& hal = AP_HAL::get_HAL();

// =============================================================================
// MICRO-ECC (P-256) TESTS
// =============================================================================

class uECC_Test : public ::testing::Test {
protected:
    void SetUp() override {
        // Set up RNG for micro-ecc
        uECC_set_rng([](uint8_t *dest, unsigned size) -> int {
            for (unsigned i = 0; i < size; i++) {
                dest[i] = (uint8_t)(rand() & 0xFF);
            }
            return 1;
        });
        curve = uECC_secp256r1();
    }

    uECC_Curve curve;
    uint8_t private_key[32];
    uint8_t public_key[64];
};

TEST_F(uECC_Test, MakeKey) {
    // Generate a keypair
    int result = uECC_make_key(public_key, private_key, curve);
    EXPECT_EQ(1, result) << "uECC_make_key should return 1 on success";
}

TEST_F(uECC_Test, MakeKeyNonZero) {
    // Generate keypair and verify it's not all zeros
    uECC_make_key(public_key, private_key, curve);

    // Check private key is not all zeros
    bool private_nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (private_key[i] != 0) {
            private_nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(private_nonzero) << "Private key should not be all zeros";

    // Check public key is not all zeros
    bool public_nonzero = false;
    for (int i = 0; i < 64; i++) {
        if (public_key[i] != 0) {
            public_nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(public_nonzero) << "Public key should not be all zeros";
}

TEST_F(uECC_Test, ComputePublicKey) {
    // Generate keypair
    uECC_make_key(public_key, private_key, curve);

    // Compute public key from private key
    uint8_t computed_public[64];
    int result = uECC_compute_public_key(private_key, computed_public, curve);
    EXPECT_EQ(1, result) << "uECC_compute_public_key should return 1";

    // Verify computed public key matches original
    EXPECT_EQ(0, memcmp(public_key, computed_public, 64))
        << "Computed public key should match original";
}

TEST_F(uECC_Test, SharedSecretSymmetric) {
    // Generate two keypairs (Alice and Bob)
    uint8_t alice_private[32], alice_public[64];
    uint8_t bob_private[32], bob_public[64];

    uECC_make_key(alice_public, alice_private, curve);
    uECC_make_key(bob_public, bob_private, curve);

    // Compute shared secrets
    uint8_t shared_alice[32], shared_bob[32];

    // Alice computes shared secret with Bob's public key
    int result1 = uECC_shared_secret(bob_public, alice_private, shared_alice, curve);
    EXPECT_EQ(1, result1);

    // Bob computes shared secret with Alice's public key
    int result2 = uECC_shared_secret(alice_public, bob_private, shared_bob, curve);
    EXPECT_EQ(1, result2);

    // Both shared secrets should be identical (ECDH property)
    EXPECT_EQ(0, memcmp(shared_alice, shared_bob, 32))
        << "ECDH shared secrets should be symmetric";
}

TEST_F(uECC_Test, DifferentKeypairsDifferentSharedSecret) {
    // Generate three keypairs
    uint8_t a_priv[32], a_pub[64];
    uint8_t b_priv[32], b_pub[64];
    uint8_t c_priv[32], c_pub[64];

    uECC_make_key(a_pub, a_priv, curve);
    uECC_make_key(b_pub, b_priv, curve);
    uECC_make_key(c_pub, c_priv, curve);

    // Compute A-B and A-C shared secrets
    uint8_t shared_ab[32], shared_ac[32];
    uECC_shared_secret(b_pub, a_priv, shared_ab, curve);
    uECC_shared_secret(c_pub, a_priv, shared_ac, curve);

    // They should be different
    EXPECT_NE(0, memcmp(shared_ab, shared_ac, 32))
        << "Different keypairs should produce different shared secrets";
}

TEST_F(uECC_Test, ValidPrivateKeyCanComputePublic) {
    uECC_make_key(public_key, private_key, curve);

    // Verify private key is valid by checking we can compute public key from it
    uint8_t computed_pub[64];
    int result = uECC_compute_public_key(private_key, computed_pub, curve);
    EXPECT_EQ(1, result) << "Generated private key should be usable";
}

TEST_F(uECC_Test, InvalidPrivateKeyZero) {
    // Zero is not a valid private key - compute_public_key should fail
    memset(private_key, 0, 32);
    uint8_t computed_pub[64];
    int result = uECC_compute_public_key(private_key, computed_pub, curve);
    EXPECT_EQ(0, result) << "Zero private key should fail to compute public key";
}

TEST_F(uECC_Test, ValidPublicKey) {
    uECC_make_key(public_key, private_key, curve);

    // Verify public key is on the curve
    int valid = uECC_valid_public_key(public_key, curve);
    EXPECT_EQ(1, valid) << "Generated public key should be valid";
}

TEST_F(uECC_Test, InvalidPublicKeyZero) {
    // Zero point is not valid
    memset(public_key, 0, 64);
    int valid = uECC_valid_public_key(public_key, curve);
    EXPECT_EQ(0, valid) << "Zero point should not be a valid public key";
}

TEST_F(uECC_Test, MultipleKeyPairsUnique) {
    // Generate multiple keypairs and verify they're all unique
    const int NUM_KEYS = 5;
    uint8_t priv_keys[NUM_KEYS][32];
    uint8_t pub_keys[NUM_KEYS][64];

    for (int i = 0; i < NUM_KEYS; i++) {
        int result = uECC_make_key(pub_keys[i], priv_keys[i], curve);
        EXPECT_EQ(1, result);
    }

    // Verify all private keys are different
    for (int i = 0; i < NUM_KEYS; i++) {
        for (int j = i + 1; j < NUM_KEYS; j++) {
            EXPECT_NE(0, memcmp(priv_keys[i], priv_keys[j], 32))
                << "Private keys " << i << " and " << j << " should differ";
        }
    }

    // Verify all public keys are different
    for (int i = 0; i < NUM_KEYS; i++) {
        for (int j = i + 1; j < NUM_KEYS; j++) {
            EXPECT_NE(0, memcmp(pub_keys[i], pub_keys[j], 64))
                << "Public keys " << i << " and " << j << " should differ";
        }
    }
}

TEST_F(uECC_Test, SharedSecretConsistent) {
    // Same keypairs should always produce same shared secret
    uint8_t alice_priv[32], alice_pub[64];
    uint8_t bob_priv[32], bob_pub[64];

    uECC_make_key(alice_pub, alice_priv, curve);
    uECC_make_key(bob_pub, bob_priv, curve);

    uint8_t shared1[32], shared2[32];

    // Compute shared secret twice
    uECC_shared_secret(bob_pub, alice_priv, shared1, curve);
    uECC_shared_secret(bob_pub, alice_priv, shared2, curve);

    // Should be identical
    EXPECT_EQ(0, memcmp(shared1, shared2, 32))
        << "Same inputs should produce same shared secret";
}

TEST_F(uECC_Test, SharedSecretNonZero) {
    uint8_t alice_priv[32], alice_pub[64];
    uint8_t bob_priv[32], bob_pub[64];

    uECC_make_key(alice_pub, alice_priv, curve);
    uECC_make_key(bob_pub, bob_priv, curve);

    uint8_t shared[32];
    uECC_shared_secret(bob_pub, alice_priv, shared, curve);

    // Shared secret should not be all zeros
    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (shared[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "Shared secret should not be all zeros";
}

// =============================================================================
// RNG TESTS
// =============================================================================

TEST(RNG_Test, RandomnessBasic) {
    // Generate two random buffers
    uint8_t buf1[32], buf2[32];

    for (int i = 0; i < 32; i++) buf1[i] = rand() & 0xFF;
    for (int i = 0; i < 32; i++) buf2[i] = rand() & 0xFF;

    // They should be different (with very high probability)
    EXPECT_NE(0, memcmp(buf1, buf2, 32))
        << "Two random buffers should be different";
}

TEST(RNG_Test, NonZero) {
    // Random buffer should not be all zeros
    uint8_t buf[32];
    for (int i = 0; i < 32; i++) buf[i] = rand() & 0xFF;

    bool nonzero = false;
    for (int i = 0; i < 32; i++) {
        if (buf[i] != 0) {
            nonzero = true;
            break;
        }
    }
    EXPECT_TRUE(nonzero) << "Random buffer should not be all zeros";
}

AP_GTEST_MAIN()
