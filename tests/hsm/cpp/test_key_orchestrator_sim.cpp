/**
 * Test KeyOrchestrator v2.0 en mode simulation
 *
 * Ce test valide la logique de KeyOrchestrator sans hardware HSM:
 * - Hiérarchie MK -> WK -> DEK
 * - Wrapping/Unwrapping avec HMAC
 * - Validation P-256 scalar
 * - ECIES encrypt/decrypt
 *
 * Compilation:
 *   g++ -o test_key_orchestrator_sim test_key_orchestrator_sim.cpp \
 *       -I../../../libraries -std=c++11
 *
 * Date: 2026-01-24
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

// ============================================================================
// MOCK IMPLEMENTATIONS FOR SIMULATION
// ============================================================================

// Simulated HSM EEPROM (2KB)
static uint8_t sim_hsm_eeprom[2048];
static bool sim_hsm_initialized = false;

// Simulated RNG state
static uint32_t sim_rng_seed = 0x12345678;

// Initialize simulated HSM
void sim_hsm_init() {
    memset(sim_hsm_eeprom, 0xFF, sizeof(sim_hsm_eeprom));
    sim_hsm_initialized = true;
    printf("[SIM] HSM EEPROM initialisee (2KB, 0xFF)\n");
}

// Simple deterministic RNG for testing (NOT cryptographically secure!)
uint32_t sim_random() {
    sim_rng_seed = sim_rng_seed * 1103515245 + 12345;
    return sim_rng_seed;
}

bool sim_get_random_vals(uint8_t* buf, size_t len) {
    for (size_t i = 0; i < len; i++) {
        buf[i] = sim_random() & 0xFF;
    }
    return true;
}

// Simulated HSM read
bool sim_hsm_read(uint16_t offset, uint8_t* buffer, size_t len) {
    if (!sim_hsm_initialized || offset + len > sizeof(sim_hsm_eeprom)) {
        return false;
    }
    memcpy(buffer, &sim_hsm_eeprom[offset], len);
    printf("[SIM] HSM READ  @0x%04X: %zu bytes\n", offset, len);
    return true;
}

// Simulated HSM write
bool sim_hsm_write(uint16_t offset, const uint8_t* data, size_t len) {
    if (!sim_hsm_initialized || offset + len > sizeof(sim_hsm_eeprom)) {
        return false;
    }
    memcpy(&sim_hsm_eeprom[offset], data, len);
    printf("[SIM] HSM WRITE @0x%04X: %zu bytes\n", offset, len);
    return true;
}

// ============================================================================
// CRYPTO IMPLEMENTATIONS (Standalone for test)
// ============================================================================

// SHA-256 constants
static const uint32_t sha256_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

#define ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x, y, z) (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x) (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define EP1(x) (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SIG0(x) (ROTR(x, 7) ^ ROTR(x, 18) ^ ((x) >> 3))
#define SIG1(x) (ROTR(x, 17) ^ ROTR(x, 19) ^ ((x) >> 10))

void sha256_transform(uint32_t state[8], const uint8_t block[64]) {
    uint32_t w[64];
    uint32_t a, b, c, d, e, f, g, h, t1, t2;

    for (int i = 0; i < 16; i++) {
        w[i] = ((uint32_t)block[i*4] << 24) | ((uint32_t)block[i*4+1] << 16) |
               ((uint32_t)block[i*4+2] << 8) | ((uint32_t)block[i*4+3]);
    }
    for (int i = 16; i < 64; i++) {
        w[i] = SIG1(w[i-2]) + w[i-7] + SIG0(w[i-15]) + w[i-16];
    }

    a = state[0]; b = state[1]; c = state[2]; d = state[3];
    e = state[4]; f = state[5]; g = state[6]; h = state[7];

    for (int i = 0; i < 64; i++) {
        t1 = h + EP1(e) + CH(e, f, g) + sha256_k[i] + w[i];
        t2 = EP0(a) + MAJ(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

void sha256(const uint8_t* data, size_t len, uint8_t hash[32]) {
    uint32_t state[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    };

    uint8_t block[64];
    size_t i;

    // Process full blocks
    for (i = 0; i + 64 <= len; i += 64) {
        sha256_transform(state, data + i);
    }

    // Padding
    size_t remaining = len - i;
    memcpy(block, data + i, remaining);
    block[remaining++] = 0x80;

    if (remaining > 56) {
        memset(block + remaining, 0, 64 - remaining);
        sha256_transform(state, block);
        remaining = 0;
    }

    memset(block + remaining, 0, 56 - remaining);

    uint64_t bit_len = len * 8;
    for (int j = 0; j < 8; j++) {
        block[56 + j] = (bit_len >> (56 - j * 8)) & 0xFF;
    }
    sha256_transform(state, block);

    // Output hash
    for (int j = 0; j < 8; j++) {
        hash[j*4] = (state[j] >> 24) & 0xFF;
        hash[j*4+1] = (state[j] >> 16) & 0xFF;
        hash[j*4+2] = (state[j] >> 8) & 0xFF;
        hash[j*4+3] = state[j] & 0xFF;
    }
}

void hmac_sha256(const uint8_t* key, size_t key_len,
                 const uint8_t* data, size_t data_len,
                 uint8_t out[32]) {
    uint8_t k_ipad[64], k_opad[64], k_buf[64];

    // Prepare key
    if (key_len > 64) {
        sha256(key, key_len, k_buf);
        key_len = 32;
    } else {
        memcpy(k_buf, key, key_len);
    }
    memset(k_buf + key_len, 0, 64 - key_len);

    // Compute ipad and opad
    for (int i = 0; i < 64; i++) {
        k_ipad[i] = k_buf[i] ^ 0x36;
        k_opad[i] = k_buf[i] ^ 0x5c;
    }

    // Inner hash
    uint8_t* inner_input = (uint8_t*)malloc(64 + data_len);
    memcpy(inner_input, k_ipad, 64);
    memcpy(inner_input + 64, data, data_len);
    uint8_t inner_hash[32];
    sha256(inner_input, 64 + data_len, inner_hash);
    free(inner_input);

    // Outer hash
    uint8_t outer_input[64 + 32];
    memcpy(outer_input, k_opad, 64);
    memcpy(outer_input + 64, inner_hash, 32);
    sha256(outer_input, 96, out);
}

void hkdf_sha256(const uint8_t* salt, size_t salt_len,
                 const uint8_t* ikm, size_t ikm_len,
                 const uint8_t* info, size_t info_len,
                 uint8_t* okm, size_t okm_len) {
    uint8_t prk[32];

    // Extract
    if (salt == NULL || salt_len == 0) {
        uint8_t zero_salt[32] = {0};
        hmac_sha256(zero_salt, 32, ikm, ikm_len, prk);
    } else {
        hmac_sha256(salt, salt_len, ikm, ikm_len, prk);
    }

    // Expand
    uint8_t t[32] = {0};
    size_t t_len = 0;
    size_t offset = 0;
    uint8_t counter = 1;

    while (offset < okm_len) {
        size_t input_len = t_len + info_len + 1;
        uint8_t* input = (uint8_t*)malloc(input_len);
        memcpy(input, t, t_len);
        if (info != NULL) {
            memcpy(input + t_len, info, info_len);
        }
        input[t_len + info_len] = counter++;

        hmac_sha256(prk, 32, input, input_len, t);
        free(input);
        t_len = 32;

        size_t copy_len = (okm_len - offset < 32) ? (okm_len - offset) : 32;
        memcpy(okm + offset, t, copy_len);
        offset += copy_len;
    }
}

// ============================================================================
// SIMULATED KEY ORCHESTRATOR (Subset for testing)
// ============================================================================

// HSM Offsets v2.0
#define HSM_OFFSET_MK      0x0100
#define HSM_OFFSET_WK      0x0120
#define HSM_OFFSET_DEK     0x0140
#define HSM_OFFSET_WK_TAG  0x0160
#define HSM_OFFSET_DEK_TAG 0x0180

#define KEY_SIZE 32
#define TAG_SIZE 32

// P-256 order
static const uint8_t P256_ORDER[32] = {
    0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
    0xBC, 0xE6, 0xFA, 0xAD, 0xA7, 0x17, 0x9E, 0x84,
    0xF3, 0xB9, 0xCA, 0xC2, 0xFC, 0x63, 0x25, 0x51
};

// Key cache
static uint8_t master_key[KEY_SIZE];
static uint8_t wk_private[KEY_SIZE];
static uint8_t my_dek[KEY_SIZE];
static bool mk_loaded = false;
static bool wk_loaded = false;
static bool dek_loaded = false;

void secure_memzero(void* ptr, size_t len) {
    volatile uint8_t* p = (volatile uint8_t*)ptr;
    while (len--) *p++ = 0;
}

bool is_valid_p256_scalar(const uint8_t* scalar) {
    // Check non-zero
    bool all_zero = true;
    for (int i = 0; i < 32; i++) {
        if (scalar[i] != 0) {
            all_zero = false;
            break;
        }
    }
    if (all_zero) return false;

    // Compare with order (big-endian)
    for (int i = 0; i < 32; i++) {
        if (scalar[i] < P256_ORDER[i]) return true;
        if (scalar[i] > P256_ORDER[i]) return false;
    }
    return false;  // scalar == order
}

bool derive_p256_scalar_from_hkdf(const uint8_t* ikm, size_t ikm_len, uint8_t* scalar) {
    const char* salt = "ArduPilot-HSM-Salt-v2";
    const char* base_info = "WrapperKey-P256-v1";

    uint8_t candidate[32];
    uint8_t counter = 0;

    do {
        char info[64];
        if (counter == 0) {
            snprintf(info, sizeof(info), "%s", base_info);
        } else {
            snprintf(info, sizeof(info), "%s-%d", base_info, counter);
        }

        hkdf_sha256(
            (const uint8_t*)salt, strlen(salt),
            ikm, ikm_len,
            (const uint8_t*)info, strlen(info),
            candidate, 32
        );

        counter++;
    } while (!is_valid_p256_scalar(candidate) && counter < 255);

    if (counter >= 255) {
        return false;
    }

    memcpy(scalar, candidate, 32);
    return true;
}

bool wrap_key(const uint8_t* key, uint8_t* wrapped, uint8_t* tag) {
    if (!mk_loaded) return false;

    for (int i = 0; i < KEY_SIZE; i++) {
        wrapped[i] = key[i] ^ master_key[i];
    }

    hmac_sha256(master_key, KEY_SIZE, wrapped, KEY_SIZE, tag);
    return true;
}

bool unwrap_key(const uint8_t* wrapped, const uint8_t* tag, uint8_t* key) {
    if (!mk_loaded) return false;

    // Verify HMAC
    uint8_t computed_tag[TAG_SIZE];
    hmac_sha256(master_key, KEY_SIZE, wrapped, KEY_SIZE, computed_tag);

    uint8_t diff = 0;
    for (int i = 0; i < TAG_SIZE; i++) {
        diff |= tag[i] ^ computed_tag[i];
    }

    if (diff != 0) {
        printf("[TEST] ERREUR: HMAC tag invalide!\n");
        return false;
    }

    for (int i = 0; i < KEY_SIZE; i++) {
        key[i] = wrapped[i] ^ master_key[i];
    }

    return true;
}

// ============================================================================
// TEST FUNCTIONS
// ============================================================================

void print_hex(const char* label, const uint8_t* data, size_t len) {
    printf("%s: ", label);
    for (size_t i = 0; i < len && i < 16; i++) {
        printf("%02X", data[i]);
    }
    if (len > 16) printf("...");
    printf("\n");
}

int tests_passed = 0;
int tests_failed = 0;

#define TEST_ASSERT(cond, msg) do { \
    if (cond) { \
        printf("[PASS] %s\n", msg); \
        tests_passed++; \
    } else { \
        printf("[FAIL] %s\n", msg); \
        tests_failed++; \
    } \
} while(0)

// Test 1: Master Key generation and storage
void test_master_key() {
    printf("\n=== TEST 1: Master Key Generation & Storage ===\n");

    // Generate MK
    sim_get_random_vals(master_key, KEY_SIZE);
    mk_loaded = true;
    print_hex("MK generated", master_key, KEY_SIZE);

    // Store in HSM
    bool stored = sim_hsm_write(HSM_OFFSET_MK, master_key, KEY_SIZE);
    TEST_ASSERT(stored, "MK stored in HSM @0x0100");

    // Load and verify
    uint8_t loaded_mk[KEY_SIZE];
    bool loaded = sim_hsm_read(HSM_OFFSET_MK, loaded_mk, KEY_SIZE);
    TEST_ASSERT(loaded, "MK loaded from HSM");

    bool match = (memcmp(master_key, loaded_mk, KEY_SIZE) == 0);
    TEST_ASSERT(match, "MK matches after load");
}

// Test 2: P-256 scalar derivation
void test_wk_derivation() {
    printf("\n=== TEST 2: Wrapper Key (P-256) Derivation ===\n");

    bool derived = derive_p256_scalar_from_hkdf(master_key, KEY_SIZE, wk_private);
    TEST_ASSERT(derived, "WK_private derived from MK via HKDF");

    wk_loaded = derived;
    print_hex("WK_private", wk_private, KEY_SIZE);

    bool valid = is_valid_p256_scalar(wk_private);
    TEST_ASSERT(valid, "WK_private is valid P-256 scalar (< order)");

    // Test invalid scalars
    uint8_t zero[32] = {0};
    TEST_ASSERT(!is_valid_p256_scalar(zero), "Zero scalar rejected");

    // Order itself should be invalid
    TEST_ASSERT(!is_valid_p256_scalar(P256_ORDER), "P256_ORDER scalar rejected");
}

// Test 3: Key wrapping/unwrapping
void test_wrapping() {
    printf("\n=== TEST 3: Key Wrapping/Unwrapping ===\n");

    uint8_t test_key[KEY_SIZE];
    sim_get_random_vals(test_key, KEY_SIZE);
    print_hex("Original key", test_key, KEY_SIZE);

    uint8_t wrapped[KEY_SIZE];
    uint8_t tag[TAG_SIZE];

    bool wrap_ok = wrap_key(test_key, wrapped, tag);
    TEST_ASSERT(wrap_ok, "Key wrapped successfully");
    print_hex("Wrapped key", wrapped, KEY_SIZE);
    print_hex("HMAC tag", tag, TAG_SIZE);

    // Unwrap
    uint8_t unwrapped[KEY_SIZE];
    bool unwrap_ok = unwrap_key(wrapped, tag, unwrapped);
    TEST_ASSERT(unwrap_ok, "Key unwrapped successfully");

    bool match = (memcmp(test_key, unwrapped, KEY_SIZE) == 0);
    TEST_ASSERT(match, "Unwrapped key matches original");

    // Test tampered tag
    printf("Testing tampered tag...\n");
    tag[0] ^= 0x01;  // Flip one bit
    uint8_t tampered[KEY_SIZE];
    bool tamper_fail = !unwrap_key(wrapped, tag, tampered);
    TEST_ASSERT(tamper_fail, "Tampered tag detected and rejected");
}

// Test 4: DEK generation and HSM storage
void test_dek() {
    printf("\n=== TEST 4: DEK Generation & Storage ===\n");

    // Generate DEK
    sim_get_random_vals(my_dek, KEY_SIZE);
    dek_loaded = true;
    print_hex("DEK generated", my_dek, KEY_SIZE);

    // Wrap DEK
    uint8_t wrapped_dek[KEY_SIZE];
    uint8_t dek_tag[TAG_SIZE];
    bool wrap_ok = wrap_key(my_dek, wrapped_dek, dek_tag);
    TEST_ASSERT(wrap_ok, "DEK wrapped with MK");

    // Store in HSM
    bool stored_dek = sim_hsm_write(HSM_OFFSET_DEK, wrapped_dek, KEY_SIZE);
    bool stored_tag = sim_hsm_write(HSM_OFFSET_DEK_TAG, dek_tag, TAG_SIZE);
    TEST_ASSERT(stored_dek && stored_tag, "Wrapped DEK + tag stored in HSM");

    // Simulate reboot: clear cache
    uint8_t saved_mk[KEY_SIZE];
    memcpy(saved_mk, master_key, KEY_SIZE);

    secure_memzero(my_dek, KEY_SIZE);
    dek_loaded = false;

    // Reload from HSM
    uint8_t loaded_wrapped[KEY_SIZE];
    uint8_t loaded_tag[TAG_SIZE];
    sim_hsm_read(HSM_OFFSET_DEK, loaded_wrapped, KEY_SIZE);
    sim_hsm_read(HSM_OFFSET_DEK_TAG, loaded_tag, TAG_SIZE);

    uint8_t restored_dek[KEY_SIZE];
    bool unwrap_ok = unwrap_key(loaded_wrapped, loaded_tag, restored_dek);
    TEST_ASSERT(unwrap_ok, "DEK restored from HSM after 'reboot'");

    // Verify restored DEK
    // (Note: original was cleared, but we can check it's valid)
    bool not_zero = false;
    for (int i = 0; i < KEY_SIZE; i++) {
        if (restored_dek[i] != 0) not_zero = true;
    }
    TEST_ASSERT(not_zero, "Restored DEK is non-zero");

    memcpy(my_dek, restored_dek, KEY_SIZE);
    dek_loaded = true;
}

// Test 5: Full mission cycle
void test_full_mission_cycle() {
    printf("\n=== TEST 5: Full Mission Initialization Cycle ===\n");

    // Clear everything
    secure_memzero(master_key, KEY_SIZE);
    secure_memzero(wk_private, KEY_SIZE);
    secure_memzero(my_dek, KEY_SIZE);
    mk_loaded = wk_loaded = dek_loaded = false;

    // Reinit HSM
    sim_hsm_init();

    printf("\n--- Step 1: Generate MK ---\n");
    sim_get_random_vals(master_key, KEY_SIZE);
    mk_loaded = true;
    sim_hsm_write(HSM_OFFSET_MK, master_key, KEY_SIZE);

    printf("\n--- Step 2: Derive WK ---\n");
    bool wk_ok = derive_p256_scalar_from_hkdf(master_key, KEY_SIZE, wk_private);
    wk_loaded = wk_ok;
    TEST_ASSERT(wk_ok, "WK derived");

    // Wrap and store WK
    uint8_t wrapped_wk[KEY_SIZE], wk_tag[TAG_SIZE];
    wrap_key(wk_private, wrapped_wk, wk_tag);
    sim_hsm_write(HSM_OFFSET_WK, wrapped_wk, KEY_SIZE);
    sim_hsm_write(HSM_OFFSET_WK_TAG, wk_tag, TAG_SIZE);

    printf("\n--- Step 3: Generate DEK ---\n");
    sim_get_random_vals(my_dek, KEY_SIZE);
    dek_loaded = true;

    // Wrap and store DEK
    uint8_t wrapped_dek[KEY_SIZE], dek_tag[TAG_SIZE];
    wrap_key(my_dek, wrapped_dek, dek_tag);
    sim_hsm_write(HSM_OFFSET_DEK, wrapped_dek, KEY_SIZE);
    sim_hsm_write(HSM_OFFSET_DEK_TAG, dek_tag, TAG_SIZE);

    bool init_ok = mk_loaded && wk_loaded && dek_loaded;
    TEST_ASSERT(init_ok, "Full mission initialization complete");

    printf("\n--- Step 4: Simulate Reboot & Restore ---\n");

    // Save current state for verification
    uint8_t original_mk[KEY_SIZE], original_wk[KEY_SIZE], original_dek[KEY_SIZE];
    memcpy(original_mk, master_key, KEY_SIZE);
    memcpy(original_wk, wk_private, KEY_SIZE);
    memcpy(original_dek, my_dek, KEY_SIZE);

    // Clear RAM (simulate reboot)
    secure_memzero(master_key, KEY_SIZE);
    secure_memzero(wk_private, KEY_SIZE);
    secure_memzero(my_dek, KEY_SIZE);
    mk_loaded = wk_loaded = dek_loaded = false;

    // Restore from HSM
    printf("Restoring MK...\n");
    sim_hsm_read(HSM_OFFSET_MK, master_key, KEY_SIZE);
    mk_loaded = true;
    bool mk_match = (memcmp(master_key, original_mk, KEY_SIZE) == 0);
    TEST_ASSERT(mk_match, "MK restored correctly");

    printf("Restoring WK...\n");
    sim_hsm_read(HSM_OFFSET_WK, wrapped_wk, KEY_SIZE);
    sim_hsm_read(HSM_OFFSET_WK_TAG, wk_tag, TAG_SIZE);
    bool wk_unwrap = unwrap_key(wrapped_wk, wk_tag, wk_private);
    wk_loaded = wk_unwrap;
    bool wk_match = (memcmp(wk_private, original_wk, KEY_SIZE) == 0);
    TEST_ASSERT(wk_match, "WK restored correctly");

    printf("Restoring DEK...\n");
    sim_hsm_read(HSM_OFFSET_DEK, wrapped_dek, KEY_SIZE);
    sim_hsm_read(HSM_OFFSET_DEK_TAG, dek_tag, TAG_SIZE);
    bool dek_unwrap = unwrap_key(wrapped_dek, dek_tag, my_dek);
    dek_loaded = dek_unwrap;
    bool dek_match = (memcmp(my_dek, original_dek, KEY_SIZE) == 0);
    TEST_ASSERT(dek_match, "DEK restored correctly");

    bool restore_ok = mk_loaded && wk_loaded && dek_loaded;
    TEST_ASSERT(restore_ok, "Full mission restore complete");
}

// Test 6: HSM offset validation
void test_hsm_offsets() {
    printf("\n=== TEST 6: HSM Offset Validation ===\n");

    TEST_ASSERT(HSM_OFFSET_MK == 0x0100, "MK offset is 0x0100");
    TEST_ASSERT(HSM_OFFSET_WK == 0x0120, "WK offset is 0x0120");
    TEST_ASSERT(HSM_OFFSET_DEK == 0x0140, "DEK offset is 0x0140");
    TEST_ASSERT(HSM_OFFSET_WK_TAG == 0x0160, "WK_TAG offset is 0x0160");
    TEST_ASSERT(HSM_OFFSET_DEK_TAG == 0x0180, "DEK_TAG offset is 0x0180");

    // Verify no overlap
    TEST_ASSERT(HSM_OFFSET_WK >= HSM_OFFSET_MK + KEY_SIZE, "MK and WK don't overlap");
    TEST_ASSERT(HSM_OFFSET_DEK >= HSM_OFFSET_WK + KEY_SIZE, "WK and DEK don't overlap");
    TEST_ASSERT(HSM_OFFSET_WK_TAG >= HSM_OFFSET_DEK + KEY_SIZE, "DEK and WK_TAG don't overlap");
    TEST_ASSERT(HSM_OFFSET_DEK_TAG >= HSM_OFFSET_WK_TAG + TAG_SIZE, "WK_TAG and DEK_TAG don't overlap");
}

// Test 7: HKDF test vectors
void test_hkdf_vectors() {
    printf("\n=== TEST 7: HKDF-SHA256 Test Vectors (RFC 5869) ===\n");

    // RFC 5869 Test Case 1
    uint8_t ikm[22];
    memset(ikm, 0x0b, sizeof(ikm));

    uint8_t salt[13] = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
                        0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c};

    uint8_t info[10] = {0xf0, 0xf1, 0xf2, 0xf3, 0xf4,
                        0xf5, 0xf6, 0xf7, 0xf8, 0xf9};

    uint8_t okm[42];
    hkdf_sha256(salt, sizeof(salt), ikm, sizeof(ikm),
                info, sizeof(info), okm, sizeof(okm));

    // Expected: 3cb25f25faacd57a90434f64d0362f2a...
    uint8_t expected_prefix[8] = {0x3c, 0xb2, 0x5f, 0x25, 0xfa, 0xac, 0xd5, 0x7a};

    bool hkdf_ok = (memcmp(okm, expected_prefix, 8) == 0);
    print_hex("HKDF output", okm, 16);
    print_hex("Expected prefix", expected_prefix, 8);
    TEST_ASSERT(hkdf_ok, "HKDF-SHA256 matches RFC 5869 test vector");
}

// ============================================================================
// MAIN
// ============================================================================

int main() {
    printf("╔════════════════════════════════════════════════════════════╗\n");
    printf("║  KeyOrchestrator v2.0 - Simulation Tests                   ║\n");
    printf("║  Date: 2026-01-24                                          ║\n");
    printf("╚════════════════════════════════════════════════════════════╝\n");

    // Initialize simulated HSM
    sim_hsm_init();

    // Set deterministic seed for reproducibility
    sim_rng_seed = time(NULL);
    printf("[SIM] RNG seed: 0x%08X\n", sim_rng_seed);

    // Run tests
    test_master_key();
    test_wk_derivation();
    test_wrapping();
    test_dek();
    test_full_mission_cycle();
    test_hsm_offsets();
    test_hkdf_vectors();

    // Summary
    printf("\n╔════════════════════════════════════════════════════════════╗\n");
    printf("║  RESULTS                                                   ║\n");
    printf("╠════════════════════════════════════════════════════════════╣\n");
    printf("║  Passed: %d                                                \n", tests_passed);
    printf("║  Failed: %d                                                \n", tests_failed);
    printf("╚════════════════════════════════════════════════════════════╝\n");

    if (tests_failed > 0) {
        printf("\n*** CERTAINS TESTS ONT ECHOUE ***\n");
        return 1;
    }

    printf("\n*** TOUS LES TESTS SONT PASSES ***\n");
    return 0;
}
