// #include "AP_HSM.h"
// extern const AP_HAL::HAL& hal;

// void test_lemonolith() {
//     //AP_HSM hsm(hal.serial(0)); // remplace 0 par SERIALx

//     hsm.begin();
//     if (!hsm.select_tlsse()) {
//         hal.console->println("TLS-SE app not found");
//         return;
//     }

//     if (!hsm.verify_pin("00000000")) {
//         hal.console->println("PIN incorrect");
//         return;
//     }

//     uint8_t key[32];
//     if (hsm.read_key(key, 32)) {
//         hal.console->println("ChaCha20 Key read OK");
//     } else {
//         hal.console->println("Key read failed");
//     }
// }
