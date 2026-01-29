/*
 * gcs_test_stub.h - Inline GCS stub for HSM unit tests
 *
 * Provides a minimal GCS implementation so that GCS_SEND_TEXT() doesn't crash.
 *
 * How it works:
 * - Creating a GCS_TestStub instance triggers the GCS base constructor
 * - The GCS base constructor sets GCS::_singleton = this
 * - Now gcs() (defined in GCS_Common.cpp) returns our stub
 * - Our stub overrides send_textv() to do nothing (no-op)
 *
 * Usage:
 *   1. Include this header after all other includes
 *   2. Add GCS_TEST_STUB_INSTANCE at file scope to create the stub instance
 */

#pragma once

#include <GCS_MAVLink/GCS.h>
#include <AP_HAL/AP_HAL.h>
#include <stdarg.h>

// Minimal GCS implementation that overrides send_textv to do nothing
class GCS_TestStub : public GCS {
public:
    // GCS base constructor will set _singleton = this automatically
    GCS_TestStub() : _num_gcs(0) {}

    // Override the virtual send_textv to just discard messages (no-op)
    // This is called by GCS::send_text() -> GCS::send_textv(3-arg) -> send_textv(4-arg)
    void send_textv(MAV_SEVERITY severity, const char *fmt, va_list arg_list, uint8_t mask) override {
        (void)severity;
        (void)fmt;
        (void)arg_list;
        (void)mask;
        // Do nothing - just discard the message
    }

    // Pure virtual functions that MUST be overridden
    uint32_t custom_mode() const override { return 0; }
    MAV_TYPE frame_type() const override { return MAV_TYPE_GENERIC; }
    const char* frame_string() const override { return "test"; }

    GCS_MAVLINK *chan(const uint8_t ofs) override {
        (void)ofs;
        return nullptr;  // No channels in test mode
    }

    const GCS_MAVLINK *chan(const uint8_t ofs) const override {
        (void)ofs;
        return nullptr;  // No channels in test mode
    }

protected:
    uint8_t _num_gcs;

    GCS_MAVLINK *new_gcs_mavlink_backend(AP_HAL::UARTDriver &uart) override {
        (void)uart;
        return nullptr;
    }
};

// Create a static instance at file scope - this sets up GCS::_singleton
// The instance is created before main() runs, ensuring gcs() returns our stub
#define GCS_TEST_STUB_INSTANCE \
    static GCS_TestStub _gcs_test_stub_instance;
