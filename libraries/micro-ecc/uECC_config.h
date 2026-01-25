/* Configuration for micro-ecc in ArduPilot */
#pragma once

/* Force x86_64 platform, disable ARM completely */
#undef __arm__
#undef __ARM__
#undef __ARM_ARCH
#undef __ARM_FEATURE_UNALIGNED

#define uECC_ARM 0
#define uECC_ARM_THUMB 0
#define uECC_ARM_THUMB2 0
#define uECC_X86_64 1
#define uECC_ASM uECC_asm_none

/* Platform configuration */
#define uECC_PLATFORM 2  /* uECC_x86_64 */
#define uECC_SUPPORTS_secp256r1 1
#define uECC_OPTIMIZATION_LEVEL 0  /* Pas d'optimisation asm */

/* Define all macros to avoid -Werror=undef */
#ifndef __AVR__
#define __AVR__ 0
#endif

#ifndef __ARM_ARCH
#define __ARM_ARCH 0
#endif

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
