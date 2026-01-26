/* Configuration for micro-ecc in ArduPilot
 * Auto-detects platform: SITL (x86_64) vs Pixhawk (ARM Cortex-M7)
 */
#pragma once

/* ========================================================================
 * PLATFORM DETECTION
 * ======================================================================== */

#if defined(__x86_64__) || defined(__amd64__) || defined(_M_X64)
    /* SITL: x86-64 Linux */
    #define uECC_PLATFORM uECC_x86_64
    #define uECC_WORD_SIZE 8
    #define uECC_ASM uECC_asm_none  /* Pure C, no ASM */

#elif defined(__arm__) || defined(__ARM_ARCH) || defined(__thumb__)
    /* Pixhawk: ARM Cortex-M7 (Thumb-2) */
    #define uECC_PLATFORM uECC_arm_thumb2
    #define uECC_WORD_SIZE 4
    #define uECC_ASM uECC_asm_none  /* Pure C, no ASM - safer for embedded */
    #define uECC_ARM_USE_UMAAL 0    /* Disable UMAAL instruction usage */

    /* Define ARM arch macros to avoid -Werror=undef */
    #ifndef __ARM_ARCH_7M__
    #define __ARM_ARCH_7M__ 0
    #endif
    #ifndef __ARM_ARCH_7EM__
    #define __ARM_ARCH_7EM__ 0
    #endif

#else
    /* Fallback: Generic */
    #define uECC_PLATFORM uECC_arch_other
    #define uECC_WORD_SIZE 4
    #define uECC_ASM uECC_asm_none
#endif

/* ========================================================================
 * CURVE CONFIGURATION
 * ======================================================================== */

/* Only enable secp256r1 (P-256) - required for HSM WK exchange */
#define uECC_SUPPORTS_secp160r1 0
#define uECC_SUPPORTS_secp192r1 0
#define uECC_SUPPORTS_secp224r1 0
#define uECC_SUPPORTS_secp256r1 1
#define uECC_SUPPORTS_secp256k1 0

/* ========================================================================
 * OPTIMIZATION SETTINGS
 * ======================================================================== */

/* Optimization level: 0 = smallest/slowest, 4 = fastest/largest
 * Level 0-1 recommended for embedded to reduce stack usage */
#define uECC_OPTIMIZATION_LEVEL 1

/* Disable square function optimization to reduce code size */
#define uECC_SQUARE_FUNC 0

/* Keep standard big-endian format for interoperability */
#define uECC_VLI_NATIVE_LITTLE_ENDIAN 0

/* Enable compressed point support (needed for some operations) */
#define uECC_SUPPORT_COMPRESSED_POINT 1

/* ========================================================================
 * WORKAROUNDS FOR COMPILER WARNINGS
 * ======================================================================== */

/* Define macros to avoid -Werror=undef on unused platforms */
#ifndef __AVR__
#define __AVR__ 0
#endif

/* ASM function flags - all disabled since we use pure C */
#ifndef asm_clear
#define asm_clear 0
#endif
#ifndef asm_set
#define asm_set 0
#endif
#ifndef asm_rshift1
#define asm_rshift1 0
#endif
#ifndef asm_add
#define asm_add 0
#endif
#ifndef asm_sub
#define asm_sub 0
#endif
#ifndef asm_mult
#define asm_mult 0
#endif
#ifndef asm_square
#define asm_square 0
#endif
#ifndef asm_mmod_fast_secp160r1
#define asm_mmod_fast_secp160r1 0
#endif
#ifndef asm_mmod_fast_secp256r1
#define asm_mmod_fast_secp256r1 0
#endif
#ifndef asm_mmod_fast_secp256k1
#define asm_mmod_fast_secp256k1 0
#endif
