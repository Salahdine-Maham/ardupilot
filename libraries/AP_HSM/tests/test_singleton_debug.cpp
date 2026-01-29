/*
 * test_singleton_debug.cpp - Debug test for HSM singletons
 *
 * Purpose: Find exactly where KeyExchangeProtocol and DualDekEngine crash
 *
 * Run with: ./build/sitl/tests/test_singleton_debug
 */

#include <AP_gtest.h>
#include <AP_HAL/AP_HAL.h>
#include <stdio.h>

// Include HSM headers
#include <AP_HSM/AP_HSM.h>
#include <AP_HSM/KeyOrchestrator.h>
#include <AP_HSM/KeyExchangeProtocol.h>
#include <AP_HSM/DualDekEngine.h>
#include <AP_HSM/uECC.h>

// Include GCS stub AFTER GCS_MAVLink headers but BEFORE use
#include "gcs_test_stub.h"
GCS_TEST_STUB_INSTANCE

const AP_HAL::HAL& hal = AP_HAL::get_HAL();

// RNG for uECC
static int debug_rng(uint8_t *dest, unsigned size) {
    for (unsigned i = 0; i < size; i++) {
        dest[i] = (uint8_t)(rand() & 0xFF);
    }
    return 1;
}

// =============================================================================
// STEP-BY-STEP SINGLETON TESTS
// =============================================================================

TEST(SingletonDebug, Step1_AP_HSM_Singleton) {
    printf("DEBUG: About to call AP_HSM::get_singleton()...\n");

    AP_HSM& hsm = AP_HSM::get_singleton();

    printf("DEBUG: AP_HSM singleton OK, address=%p\n", (void*)&hsm);
    EXPECT_NE(nullptr, &hsm);
}

TEST(SingletonDebug, Step2_KeyOrchestrator_Singleton) {
    printf("DEBUG: About to call KeyOrchestrator::get_singleton()...\n");

    KeyOrchestrator& ko = KeyOrchestrator::get_singleton();

    printf("DEBUG: KeyOrchestrator singleton OK, address=%p\n", (void*)&ko);
    EXPECT_NE(nullptr, &ko);
}

TEST(SingletonDebug, Step3_KeyExchangeProtocol_Singleton) {
    printf("DEBUG: About to call KeyExchangeProtocol::get_singleton()...\n");

    KeyExchangeProtocol* kep = KeyExchangeProtocol::get_singleton();

    printf("DEBUG: KeyExchangeProtocol singleton result=%p\n", (void*)kep);
    EXPECT_NE(nullptr, kep);
}

TEST(SingletonDebug, Step4_DualDekEngine_Singleton) {
    printf("DEBUG: About to call DualDekEngine::get_singleton()...\n");

    DualDekEngine* dde = DualDekEngine::get_singleton();

    printf("DEBUG: DualDekEngine singleton result=%p\n", (void*)dde);
    EXPECT_NE(nullptr, dde);
}

// =============================================================================
// INIT TESTS (if singletons work)
// =============================================================================

TEST(SingletonDebug, Step5_KeyOrchestrator_Init) {
    printf("DEBUG: Setting up uECC RNG...\n");
    uECC_set_rng(debug_rng);

    printf("DEBUG: Getting singletons for init...\n");
    AP_HSM& hsm = AP_HSM::get_singleton();
    KeyOrchestrator& ko = KeyOrchestrator::get_singleton();

    printf("DEBUG: Calling ko.init(&hsm)...\n");
    bool init_result = ko.init(&hsm);

    printf("DEBUG: ko.init() returned %d\n", init_result);
    EXPECT_TRUE(init_result);
}

TEST(SingletonDebug, Step6_KeyOrchestrator_InitMissionKeys) {
    uECC_set_rng(debug_rng);

    KeyOrchestrator& ko = KeyOrchestrator::get_singleton();

    printf("DEBUG: Calling ko.init_mission_keys()...\n");
    bool result = ko.init_mission_keys();

    printf("DEBUG: ko.init_mission_keys() returned %d\n", result);
    printf("DEBUG: is_fully_initialized=%d\n", ko.is_fully_initialized());
    EXPECT_TRUE(result);
}

TEST(SingletonDebug, Step7_KeyExchangeProtocol_Init) {
    uECC_set_rng(debug_rng);

    printf("DEBUG: Getting singletons...\n");
    KeyOrchestrator& ko = KeyOrchestrator::get_singleton();
    KeyExchangeProtocol* kep = KeyExchangeProtocol::get_singleton();

    printf("DEBUG: ko=%p, kep=%p\n", (void*)&ko, (void*)kep);

    if (kep == nullptr) {
        printf("DEBUG: KEP is NULL, cannot init!\n");
        FAIL() << "KEP singleton is NULL";
        return;
    }

    printf("DEBUG: Calling kep->init(&ko)...\n");
    bool result = kep->init(&ko);

    printf("DEBUG: kep->init() returned %d\n", result);
    EXPECT_TRUE(result);
}

TEST(SingletonDebug, Step8_DualDekEngine_Init) {
    uECC_set_rng(debug_rng);

    printf("DEBUG: Getting singletons...\n");
    KeyOrchestrator& ko = KeyOrchestrator::get_singleton();
    KeyExchangeProtocol* kep = KeyExchangeProtocol::get_singleton();
    DualDekEngine* dde = DualDekEngine::get_singleton();

    printf("DEBUG: ko=%p, kep=%p, dde=%p\n", (void*)&ko, (void*)kep, (void*)dde);

    if (dde == nullptr) {
        printf("DEBUG: DDE is NULL, cannot init!\n");
        FAIL() << "DDE singleton is NULL";
        return;
    }

    printf("DEBUG: Calling dde->init(&ko, kep)...\n");
    bool result = dde->init(&ko, kep);

    printf("DEBUG: dde->init() returned %d\n", result);
    EXPECT_TRUE(result);
}

AP_GTEST_MAIN()
