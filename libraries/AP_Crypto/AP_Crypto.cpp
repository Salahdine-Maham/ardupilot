/*
 * AP_Crypto - Cryptographic primitives implementation
 *
 * SHA-256 implementation based on FIPS 180-4
 * Public domain code, adapted for ArduPilot
 */

#include "AP_Crypto.h"
#include <string.h>

// SHA-256 constants (first 32 bits of fractional parts of cube roots of first 64 primes)
static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

// SHA-256 initial hash values (first 32 bits of fractional parts of square roots of first 8 primes)
static const uint32_t H0[8] = {
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
};

// Rotate right macro
#define ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

// SHA-256 logical functions
#define CH(x, y, z)  (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x) (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define EP1(x) (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SIG0(x) (ROTR(x, 7) ^ ROTR(x, 18) ^ ((x) >> 3))
#define SIG1(x) (ROTR(x, 17) ^ ROTR(x, 19) ^ ((x) >> 10))

// Transform one 512-bit block
static void sha256_transform(sha256_ctx_t* ctx, const uint8_t data[64]) {
    uint32_t a, b, c, d, e, f, g, h, t1, t2, m[64];
    uint32_t i;

    // Prepare message schedule
    for (i = 0; i < 16; i++) {
        m[i] = ((uint32_t)data[i * 4] << 24) |
               ((uint32_t)data[i * 4 + 1] << 16) |
               ((uint32_t)data[i * 4 + 2] << 8) |
               ((uint32_t)data[i * 4 + 3]);
    }
    for (i = 16; i < 64; i++) {
        m[i] = SIG1(m[i - 2]) + m[i - 7] + SIG0(m[i - 15]) + m[i - 16];
    }

    // Initialize working variables
    a = ctx->state[0];
    b = ctx->state[1];
    c = ctx->state[2];
    d = ctx->state[3];
    e = ctx->state[4];
    f = ctx->state[5];
    g = ctx->state[6];
    h = ctx->state[7];

    // Main loop
    for (i = 0; i < 64; i++) {
        t1 = h + EP1(e) + CH(e, f, g) + K[i] + m[i];
        t2 = EP0(a) + MAJ(a, b, c);
        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }

    // Update hash state
    ctx->state[0] += a;
    ctx->state[1] += b;
    ctx->state[2] += c;
    ctx->state[3] += d;
    ctx->state[4] += e;
    ctx->state[5] += f;
    ctx->state[6] += g;
    ctx->state[7] += h;
}

// Initialize SHA-256 context
void sha256_init(sha256_ctx_t* ctx) {
    ctx->count = 0;
    memcpy(ctx->state, H0, sizeof(H0));
}

// Update SHA-256 with new data
void sha256_update(sha256_ctx_t* ctx, const uint8_t* data, size_t len) {
    size_t i;
    size_t index = (ctx->count / 8) % 64;

    ctx->count += len * 8;

    // Fill buffer and process complete blocks
    for (i = 0; i < len; i++) {
        ctx->buffer[index++] = data[i];
        if (index == 64) {
            sha256_transform(ctx, ctx->buffer);
            index = 0;
        }
    }
}

// Finalize SHA-256 and produce hash
void sha256_final(sha256_ctx_t* ctx, uint8_t hash[32]) {
    size_t i;
    size_t index = (ctx->count / 8) % 64;

    // Padding
    ctx->buffer[index++] = 0x80;

    if (index > 56) {
        // Need extra block
        while (index < 64) {
            ctx->buffer[index++] = 0x00;
        }
        sha256_transform(ctx, ctx->buffer);
        index = 0;
    }

    // Pad with zeros
    while (index < 56) {
        ctx->buffer[index++] = 0x00;
    }

    // Append length (big-endian 64-bit)
    for (i = 0; i < 8; i++) {
        ctx->buffer[56 + i] = (ctx->count >> (56 - i * 8)) & 0xff;
    }

    sha256_transform(ctx, ctx->buffer);

    // Produce final hash (big-endian)
    for (i = 0; i < 8; i++) {
        hash[i * 4] = (ctx->state[i] >> 24) & 0xff;
        hash[i * 4 + 1] = (ctx->state[i] >> 16) & 0xff;
        hash[i * 4 + 2] = (ctx->state[i] >> 8) & 0xff;
        hash[i * 4 + 3] = ctx->state[i] & 0xff;
    }
}

// Convenience function: hash data in one call
void sha256(const uint8_t* data, size_t len, uint8_t hash[32]) {
    sha256_ctx_t ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, data, len);
    sha256_final(&ctx, hash);
}

// HMAC-SHA256 implementation (RFC 2104)
void hmac_sha256(const uint8_t* key, size_t key_len,
                 const uint8_t* data, size_t data_len,
                 uint8_t out[32]) {
    sha256_ctx_t ctx;
    uint8_t k_pad[64];
    uint8_t tk[32];
    size_t i;

    // If key is longer than 64 bytes, hash it first
    if (key_len > 64) {
        sha256(key, key_len, tk);
        key = tk;
        key_len = 32;
    }

    // Prepare key with padding
    memset(k_pad, 0, sizeof(k_pad));
    memcpy(k_pad, key, key_len);

    // Compute inner hash: H((K ^ ipad) || data)
    for (i = 0; i < 64; i++) {
        k_pad[i] ^= 0x36;
    }

    sha256_init(&ctx);
    sha256_update(&ctx, k_pad, 64);
    sha256_update(&ctx, data, data_len);
    sha256_final(&ctx, out);

    // Prepare key for outer hash
    memset(k_pad, 0, sizeof(k_pad));
    memcpy(k_pad, key, key_len);
    for (i = 0; i < 64; i++) {
        k_pad[i] ^= 0x5c;
    }

    // Compute outer hash: H((K ^ opad) || inner_hash)
    sha256_init(&ctx);
    sha256_update(&ctx, k_pad, 64);
    sha256_update(&ctx, out, 32);
    sha256_final(&ctx, out);

    // Clear sensitive data
    memset(k_pad, 0, sizeof(k_pad));
    memset(tk, 0, sizeof(tk));
}

// HKDF-SHA256 Extract (RFC 5869)
void hkdf_sha256_extract(const uint8_t* salt, size_t salt_len,
                         const uint8_t* ikm, size_t ikm_len,
                         uint8_t prk[32]) {
    // If salt is not provided, use zero-filled salt of HashLen (32 bytes)
    uint8_t zero_salt[32] = {0};

    if (salt == NULL || salt_len == 0) {
        hmac_sha256(zero_salt, 32, ikm, ikm_len, prk);
    } else {
        hmac_sha256(salt, salt_len, ikm, ikm_len, prk);
    }
}

// HKDF-SHA256 Expand (RFC 5869)
void hkdf_sha256_expand(const uint8_t prk[32],
                        const uint8_t* info, size_t info_len,
                        uint8_t* okm, size_t okm_len) {
    uint8_t t[32] = {0};
    uint8_t counter = 1;
    size_t generated = 0;
    uint8_t temp[32 + 256 + 1]; // T(i-1) || info || counter
    size_t temp_len;

    // Maximum output length is 255 * 32 = 8160 bytes
    if (okm_len > 255 * 32) {
        return; // Error: okm_len too large
    }

    while (generated < okm_len) {
        // Build input: T(i-1) || info || counter
        temp_len = 0;

        if (counter > 1) {
            memcpy(temp, t, 32);
            temp_len = 32;
        }

        if (info != NULL && info_len > 0) {
            memcpy(temp + temp_len, info, info_len);
            temp_len += info_len;
        }

        temp[temp_len++] = counter;

        // T(i) = HMAC-Hash(PRK, T(i-1) || info || counter)
        hmac_sha256(prk, 32, temp, temp_len, t);

        // Copy to output
        size_t to_copy = (okm_len - generated < 32) ? (okm_len - generated) : 32;
        memcpy(okm + generated, t, to_copy);
        generated += to_copy;

        counter++;
    }

    // Clear sensitive data
    memset(t, 0, sizeof(t));
    memset(temp, 0, sizeof(temp));
}

// HKDF-SHA256 full operation (Extract + Expand)
void hkdf_sha256(const uint8_t* salt, size_t salt_len,
                 const uint8_t* ikm, size_t ikm_len,
                 const uint8_t* info, size_t info_len,
                 uint8_t* okm, size_t okm_len) {
    uint8_t prk[32];

    // Extract
    hkdf_sha256_extract(salt, salt_len, ikm, ikm_len, prk);

    // Expand
    hkdf_sha256_expand(prk, info, info_len, okm, okm_len);

    // Clear PRK
    memset(prk, 0, sizeof(prk));
}
