/*
 * Test vectors for AP_Crypto
 *
 * Tests SHA-256, HMAC-SHA256, and HKDF-SHA256 with standard test vectors
 */

#include <stdio.h>
#include <string.h>
#include "../libraries/AP_Crypto/AP_Crypto.h"

// Helper to print hex
void print_hex(const char* label, const uint8_t* data, size_t len) {
    printf("%s: ", label);
    for (size_t i = 0; i < len; i++) {
        printf("%02x", data[i]);
    }
    printf("\n");
}

// Test SHA-256
void test_sha256() {
    printf("\n=== Test SHA-256 ===\n");

    // Test vector 1: empty string
    // Expected: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    uint8_t hash[32];
    sha256((const uint8_t*)"", 0, hash);
    print_hex("SHA256(\"\")", hash, 32);

    // Test vector 2: "abc"
    // Expected: ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
    sha256((const uint8_t*)"abc", 3, hash);
    print_hex("SHA256(\"abc\")", hash, 32);

    // Test vector 3: "The quick brown fox jumps over the lazy dog"
    // Expected: d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592
    const char* msg = "The quick brown fox jumps over the lazy dog";
    sha256((const uint8_t*)msg, strlen(msg), hash);
    print_hex("SHA256(fox)", hash, 32);
}

// Test HMAC-SHA256
void test_hmac_sha256() {
    printf("\n=== Test HMAC-SHA256 ===\n");

    // Test vector from RFC 4231
    // Key: "Jefe"
    // Data: "what do ya want for nothing?"
    // Expected: 5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843
    uint8_t hmac[32];
    const char* key = "Jefe";
    const char* data = "what do ya want for nothing?";

    hmac_sha256((const uint8_t*)key, strlen(key),
                (const uint8_t*)data, strlen(data),
                hmac);
    print_hex("HMAC-SHA256", hmac, 32);
}

// Test HKDF-SHA256
void test_hkdf_sha256() {
    printf("\n=== Test HKDF-SHA256 ===\n");

    // Test vector from RFC 5869 (A.1)
    // IKM: 0x0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b (22 octets)
    // Salt: 0x000102030405060708090a0b0c (13 octets)
    // Info: 0xf0f1f2f3f4f5f6f7f8f9 (10 octets)
    // L: 42

    uint8_t ikm[22];
    memset(ikm, 0x0b, sizeof(ikm));

    uint8_t salt[13] = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
                        0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c};

    uint8_t info[10] = {0xf0, 0xf1, 0xf2, 0xf3, 0xf4,
                        0xf5, 0xf6, 0xf7, 0xf8, 0xf9};

    uint8_t okm[42];

    // Expected OKM:
    // 3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf
    // 34007208d5b887185865

    hkdf_sha256(salt, sizeof(salt), ikm, sizeof(ikm),
                info, sizeof(info), okm, sizeof(okm));

    print_hex("HKDF OKM", okm, 42);
}

int main() {
    printf("AP_Crypto Test Vectors\n");
    printf("=====================\n");

    test_sha256();
    test_hmac_sha256();
    test_hkdf_sha256();

    printf("\nTests completed!\n");
    printf("Compare output with expected values from RFCs.\n");

    return 0;
}
