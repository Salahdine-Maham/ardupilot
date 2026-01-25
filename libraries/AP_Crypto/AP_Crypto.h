/*
 * AP_Crypto - Lightweight cryptographic functions for ArduPilot
 *
 * Provides:
 * - SHA-256 hash
 * - HMAC-SHA256
 * - HKDF-SHA256 (Key Derivation Function)
 *
 * Implementation based on public domain code, optimized for embedded systems
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

// SHA-256 context structure
typedef struct {
    uint32_t state[8];      // Hash state
    uint64_t count;         // Number of bits processed
    uint8_t buffer[64];     // Input buffer
} sha256_ctx_t;

/*
 * SHA-256 Functions
 */

// Initialize SHA-256 context
void sha256_init(sha256_ctx_t* ctx);

// Update SHA-256 with new data
void sha256_update(sha256_ctx_t* ctx, const uint8_t* data, size_t len);

// Finalize SHA-256 and produce hash
void sha256_final(sha256_ctx_t* ctx, uint8_t hash[32]);

// Convenience function: hash data in one call
void sha256(const uint8_t* data, size_t len, uint8_t hash[32]);

/*
 * HMAC-SHA256 Functions
 */

// Compute HMAC-SHA256
// key: secret key (any length)
// key_len: length of key in bytes
// data: message to authenticate
// data_len: length of message in bytes
// out: output buffer (32 bytes)
void hmac_sha256(const uint8_t* key, size_t key_len,
                 const uint8_t* data, size_t data_len,
                 uint8_t out[32]);

/*
 * HKDF-SHA256 Functions (RFC 5869)
 */

// HKDF Extract step
// salt: optional salt (can be NULL)
// salt_len: length of salt (0 if NULL)
// ikm: input keying material
// ikm_len: length of ikm
// prk: output pseudorandom key (32 bytes)
void hkdf_sha256_extract(const uint8_t* salt, size_t salt_len,
                         const uint8_t* ikm, size_t ikm_len,
                         uint8_t prk[32]);

// HKDF Expand step
// prk: pseudorandom key from extract (32 bytes)
// info: optional context/application specific info (can be NULL)
// info_len: length of info (0 if NULL)
// okm: output keying material
// okm_len: desired length of okm (max 8160 bytes = 255*32)
void hkdf_sha256_expand(const uint8_t prk[32],
                        const uint8_t* info, size_t info_len,
                        uint8_t* okm, size_t okm_len);

// HKDF full operation (Extract + Expand)
// Convenience function combining extract and expand
void hkdf_sha256(const uint8_t* salt, size_t salt_len,
                 const uint8_t* ikm, size_t ikm_len,
                 const uint8_t* info, size_t info_len,
                 uint8_t* okm, size_t okm_len);
