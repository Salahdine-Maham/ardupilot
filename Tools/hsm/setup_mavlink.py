#!/usr/bin/env python3
"""
Setup MAVLink dialect with HSM custom messages

This script generates the Python MAVLink module that includes
the custom HSM messages (HSM_WK_EXCHANGE, HSM_DEK_EXCHANGE, HSM_KEY_ACK).

Run this once before using gcs_kep_client.py:
    python3 setup_mavlink.py

Date: 2026-01-25
"""

import os
import sys
import subprocess

# Paths
ARDUPILOT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAVLINK_DIR = os.path.join(ARDUPILOT_ROOT, "modules", "mavlink")
MESSAGE_DEF = os.path.join(MAVLINK_DIR, "message_definitions", "v1.0", "ardupilotmega.xml")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mavlink_hsm")


def generate_mavlink():
    """Generate Python MAVLink dialect"""
    print("=" * 60)
    print("  MAVLink Dialect Generator for HSM")
    print("=" * 60)
    print(f"  ArduPilot root: {ARDUPILOT_ROOT}")
    print(f"  Message def: {MESSAGE_DEF}")
    print(f"  Output dir: {OUTPUT_DIR}")
    print()

    # Check if message definition exists
    if not os.path.exists(MESSAGE_DEF):
        print(f"ERROR: Message definition not found: {MESSAGE_DEF}")
        return False

    # Check for HSM messages in definition
    with open(MESSAGE_DEF, 'r') as f:
        content = f.read()
        if 'HSM_WK_EXCHANGE' not in content:
            print("ERROR: HSM_WK_EXCHANGE not found in ardupilotmega.xml")
            print("Make sure the custom messages have been added.")
            return False

    print("✓ HSM messages found in definition")

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Generate using pymavlink.tools.mavgen
    cmd = [
        sys.executable, "-m", "pymavlink.tools.mavgen",
        "--lang=Python",
        "--wire-protocol=2.0",
        f"--output={OUTPUT_DIR}",
        MESSAGE_DEF
    ]

    print(f"\nRunning: {' '.join(cmd)}")
    print()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: mavgen failed:")
            print(result.stderr)
            return False
        print(result.stdout)
    except Exception as e:
        print(f"ERROR: {e}")
        return False

    # Check output
    output_file = os.path.join(OUTPUT_DIR, "ardupilotmega.py")
    if not os.path.exists(output_file):
        print(f"ERROR: Output file not created: {output_file}")
        return False

    print("=" * 60)
    print("✓ MAVLink dialect generated successfully!")
    print(f"  Output: {OUTPUT_DIR}")
    print()
    print("To use in Python:")
    print(f'  sys.path.insert(0, "{OUTPUT_DIR}")')
    print('  from pymavlink import mavutil')
    print('  mavutil.set_dialect("ardupilotmega")')
    print("=" * 60)

    return True


def verify_messages():
    """Verify HSM messages are available"""
    print("\nVerifying HSM messages...")

    try:
        sys.path.insert(0, OUTPUT_DIR)
        # Force reload
        if 'pymavlink' in sys.modules:
            # Clear pymavlink cache
            for key in list(sys.modules.keys()):
                if 'mavlink' in key.lower():
                    del sys.modules[key]

        from pymavlink import mavutil
        mavutil.set_dialect("ardupilotmega")

        # Try to access HSM message
        from pymavlink.dialects.v20 import ardupilotmega as mavlink2

        msg_ids = {
            'HSM_WK_EXCHANGE': 12000,
            'HSM_DEK_EXCHANGE': 12001,
            'HSM_KEY_ACK': 12002
        }

        for name, expected_id in msg_ids.items():
            msg_id = getattr(mavlink2, f'MAVLINK_MSG_ID_{name}', None)
            if msg_id == expected_id:
                print(f"  ✓ {name} (ID {msg_id})")
            else:
                print(f"  ✗ {name} - Expected {expected_id}, got {msg_id}")
                return False

        print("\n✓ All HSM messages verified!")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


if __name__ == '__main__':
    if generate_mavlink():
        verify_messages()
