#include "AP_HSM.h"
#include <AP_HAL/AP_HAL.h>
#include <cstring>
#include <AP_SerialManager/AP_SerialManager.h>
#include <stdio.h>

#include <cctype>

// Session 21: Mock debug output macro
// In SITL, hal.console writes to MAVLink TCP port, corrupting the stream
// Use printf() in SITL (goes to stdout) and hal.console on Pixhawk
#if AP_HSM_MOCK_ENABLED
  #if CONFIG_HAL_BOARD == HAL_BOARD_SITL
    // Disable verbose Mock output in SITL to avoid MAVLink corruption
    #define MOCK_DEBUG(fmt, ...) do { /* disabled */ } while(0)
  #else
    #define MOCK_DEBUG(fmt, ...) hal.console->printf(fmt, ##__VA_ARGS__)
  #endif
#else
  #define MOCK_DEBUG(fmt, ...) do { /* not mock mode */ } while(0)
#endif

// Feature 2: micro-ecc pour génération keypair P-256
#include "uECC.h"

// Feature 3: AP_Crypto pour HKDF-SHA256 et wrap/unwrap DEK
#include <AP_Crypto/AP_Crypto.h>





extern const AP_HAL::HAL& hal;

// Initialise le pointeur à null au départ
AP_HSM* AP_HSM::_singleton = nullptr;


// Constructeur privé pour empêcher l'instanciation directe
AP_HSM::AP_HSM() {
    // Initialisation de uart_hsm (optionnel)
    memset(key_bytes, 0, sizeof(key_bytes));
    memset(private_key_cache, 0, sizeof(private_key_cache));
    memset(public_key_cache, 0, sizeof(public_key_cache));
    keypair_loaded = false;
    memset(dek_cache, 0, sizeof(dek_cache));
    dek_loaded = false;
    uart_hsm = nullptr; // Déjà initialisé par défaut, mais explicite ici

#if AP_HSM_MOCK_ENABLED
    // Initialize mock storage
    memset(_mock_storage, 0, sizeof(_mock_storage));
    _mock_initialized = false;
    // Note: Don't print here - console might not be ready yet
#endif
}

// Méthode pour obtenir l'instance unique de la classe
AP_HSM& AP_HSM::get_singleton() {
    if (_singleton == nullptr) {
        _singleton = new AP_HSM();
    }
    return *_singleton;
}




// Initialisation de la communication UART
void AP_HSM::begin(AP_HAL::UARTDriver* uart_dev) {
#if AP_HSM_MOCK_ENABLED
    // Mock mode: no UART needed
    (void)uart_dev;  // Suppress unused parameter warning
    // Note: Use printf() in SITL to avoid corrupting MAVLink stream (hal.console = SERIAL0 = TCP 5760)
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
    printf("HSM: [MOCK MODE] Skipping UART initialization\n");
#endif
    return;
#else
    if (uart_dev == nullptr) {
        hal.console->printf("Erreur : UART non fourni pour HSM\n");
        return;
    }

    uart_hsm = uart_dev;
    uart_hsm->begin(115200);
    uart_hsm->set_flow_control(AP_HAL::UARTDriver::FLOW_CONTROL_DISABLE);
    flush_input();
#endif
}

/**
 * Feature 1: Initialisation fiable et robuste du LeMonolith
 *
 * Cette fonction effectue une séquence d'initialisation complète :
 * 1. Désactivation puis activation du Secure Element
 * 2. Sélection de l'applet CC (Crypto Currency) - AID: 010203040601
 * 3. Vérification du PIN User (par défaut: "00000000")
 *
 * @return true si l'initialisation réussit, false en cas d'erreur
 *
 * IMPORTANT: Les APDU doivent être préfixées avec "A " pour le firmware ESP32
 */
bool AP_HSM::init_monolith() {
#if AP_HSM_MOCK_ENABLED
    // Mock mode: simulate successful HSM initialization
    // Note: Use printf() in SITL to avoid corrupting MAVLink stream
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
    printf("HSM: [MOCK] Init complete\n");
#endif
    _mock_initialized = true;
    _init_state = InitState::COMPLETE;
    return true;
#else
    if (uart_hsm == nullptr) {
        hal.console->printf("HSM: Erreur - UART non initialisé\n");
        return false;
    }

    hal.console->printf("HSM: Démarrage initialisation LeMonolith...\n");
    

    // Étape 1: Désactivation du Secure Element
    hal.console->printf("HSM: [STEP1] flush_input pre-OFF...\n");
    flush_input();
    hal.console->printf("HSM: [STEP1] sending OFF...\n");
    uart_hsm->printf("off\r\n");
    hal.console->printf("HSM: [STEP1] delay 200ms...\n");
    hal.scheduler->delay(200);
    hal.console->printf("HSM: [STEP1] flush_input post-OFF...\n");
    flush_input(); // Ignorer réponse "OK"

    hal.console->printf("HSM: SE désactivé\n");
    

    // Étape 2: Activation du Secure Element
    // Note: Le firmware sélectionne automatiquement l'applet CC lors du "on"
    // Le HSM envoie: ATR + PTS + SELECT auto + réponse = ~6-8 secondes
    hal.console->printf("HSM: [DEBUG] flush_input...\n");
    flush_input();
    hal.console->printf("HSM: [DEBUG] sending ON...\n");
    uart_hsm->printf("on\r\n");
    hal.console->printf("HSM: [DEBUG] delay 4s...\n");
    hal.scheduler->delay(4000);  // Augmenté à 4s pour init complète
    hal.console->printf("HSM: [DEBUG] delay done\n");

    // Lire et analyser la réponse (contient ATR, PTS, SELECT auto, etc.)
    uint32_t start = AP_HAL::millis();
    bool atr_complete = false;
    while ((AP_HAL::millis() - start) < 5000 && !atr_complete) {  // Augmenté à 5s
        if (uart_hsm->available() > 0) {
            uart_hsm->read(); // Lire et ignorer les données d'initialisation
            // Détecter fin de l'ATR (chercher "9000" ou "OK")
            // Pour simplifier, on attend juste que le buffer se stabilise
        }
        hal.scheduler->delay(10);
    }

    // Flush multiple agressif pour être sûr que le buffer est vide
    flush_input();
    hal.scheduler->delay(200);
    flush_input();
    hal.scheduler->delay(200);
    flush_input();

    hal.console->printf("HSM: SE activé\n");
    hal.scheduler->delay(1000);  // Augmenté à 1s avant SELECT

    // Étape 3: SELECT Application CC (Crypto Currency)
    // AID: 010203040601
    // L'applet est normalement auto-sélectionné par le firmware, mais on le fait explicitement
    char response[128];
    const char* apdu_select_cc = "A 00A4040006010203040601";

    if (!send_apdu(apdu_select_cc, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout SELECT applet CC\n");
        return false;
    }

    // Vérifier SW 9000 (succès)
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - SELECT CC échoué. Réponse: %s\n", response);
        return false;
    }

    hal.console->printf("HSM: Application CC sélectionnée (AID: 010203040601)\n");

    // Étape 4: VERIFY PIN User
    // PIN par défaut: "00000000" (8 caractères ASCII)
    // En hex: 3030303030303030
    const char* apdu_verify_pin = "A 00200001083030303030303030";

    if (!send_apdu(apdu_verify_pin, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout VERIFY PIN\n");
        return false;
    }

    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - VERIFY PIN échoué. Réponse: %s\n", response);
        hal.console->printf("HSM: Vérifiez que le PIN est bien \"00000000\"\n");
        return false;
    }

    hal.console->printf("HSM: PIN User vérifié avec succès\n");

    // Succès complet
    hal.console->printf("HSM: ✓ Initialisation LeMonolith terminée avec succès\n");
    hal.console->printf("HSM: Prêt pour opérations READ/WRITE de clés\n");

    return true;
#endif  // !AP_HSM_MOCK_ENABLED
}


// =============================================================================
// ASYNC INIT - Non-blocking initialization
// =============================================================================

void AP_HSM::start_init_async()
{
    if (uart_hsm == nullptr) {
        hal.console->printf("HSM: Erreur - UART non initialisé\n");
        _init_state = InitState::FAILED;
        return;
    }

    hal.console->printf("HSM: [ASYNC] Démarrage initialisation...\n");
    _init_state = InitState::SENDING_OFF;
    _init_step_start_ms = AP_HAL::millis();
    _flush_count = 0;

    // Envoyer OFF immédiatement
    flush_input();
    const char* cmd = "off\r\n";
    uart_hsm->write((const uint8_t*)cmd, strlen(cmd));
}

bool AP_HSM::update_init()
{
    if (_init_state == InitState::COMPLETE || _init_state == InitState::FAILED) {
        return true;  // Terminé
    }

#if AP_HSM_MOCK_ENABLED
    // Mock mode: simulate instant completion
    if (_init_state == InitState::NOT_STARTED) {
        hal.console->printf("HSM: [MOCK] update_init() - simulating instant completion\n");
        _mock_initialized = true;
        _init_state = InitState::COMPLETE;
        return true;
    }
#endif

    if (_init_state == InitState::NOT_STARTED) {
        return true;  // Pas démarré (real HSM)
    }

    uint32_t elapsed = AP_HAL::millis() - _init_step_start_ms;

    switch (_init_state) {

    case InitState::SENDING_OFF:
        // Attendre 200ms après OFF - on ignore l'erreur "unknown command"
        if (elapsed >= 200) {
            flush_input();
            hal.console->printf("HSM: [ASYNC] SE désactivé (off envoyé)\n");
            
            _init_state = InitState::SENDING_ON;
            _init_step_start_ms = AP_HAL::millis();
            flush_input();
            hal.console->printf("HSM: [ASYNC] Envoi 'on'...\n");
            
            const char* cmd = "on\r\n";
            uart_hsm->write((const uint8_t*)cmd, strlen(cmd));
        }
        break;

    case InitState::SENDING_ON:
        // Attendre 4s pour ATR
        if (elapsed >= 4000) {
            uint32_t avail = uart_hsm->available();
            hal.console->printf("HSM: [ASYNC] Après ON: %lu bytes disponibles\n", (unsigned long)avail);
            
            _init_state = InitState::READING_ATR;
            _init_step_start_ms = AP_HAL::millis();
        }
        break;

    case InitState::READING_ATR:
        // Lire ATR pendant 5s max
        {
            uint32_t count = 0;
            while (uart_hsm->available() > 0 && count < 1000) {
                uart_hsm->read();
                count++;
            }
            if (elapsed >= 5000) {
                hal.console->printf("HSM: [ASYNC] ATR lu (5s écoulées)\n");
                
                _init_state = InitState::FLUSHING;
                _init_step_start_ms = AP_HAL::millis();
                _flush_count = 0;
            }
        }
        break;

    case InitState::FLUSHING:
        // 3 flush avec 200ms entre chaque
        if (elapsed >= 200) {
            flush_input();
            _flush_count++;
            _init_step_start_ms = AP_HAL::millis();
            hal.console->printf("HSM: [ASYNC] Flush %d/3\n", _flush_count);
            
            if (_flush_count >= 3) {
                hal.console->printf("HSM: [ASYNC] SE activé, prêt pour APDU\n");
                
                _init_state = InitState::SELECT_CC;
                _init_step_start_ms = AP_HAL::millis();
            }
        }
        break;

    case InitState::SELECT_CC:
        // Attendre 2s puis SELECT CC via send_apdu (comme init_monolith)
        if (elapsed >= 2000) {
            hal.console->printf("HSM: [ASYNC] Envoi SELECT CC via send_apdu...\n");
            

            // Debug: vérifier UART
            hal.console->printf("HSM: [ASYNC] uart_hsm=%p\n", (void*)uart_hsm);
            

            char response[128] = {0};
            if (!send_apdu("A 00A4040006010203040601", response, sizeof(response))) {
                hal.console->printf("HSM: [ASYNC] send_apdu retourné false, response='%s'\n", response);
                _init_state = InitState::FAILED;
                return true;
            }

            hal.console->printf("HSM: [ASYNC] SELECT CC réponse: %s\n", response);
            

            if (strstr(response, "9000") == nullptr) {
                hal.console->printf("HSM: [ASYNC] SELECT CC échoué (pas de 9000)\n");
                _init_state = InitState::FAILED;
                return true;
            }
            hal.console->printf("HSM: [ASYNC] Application CC sélectionnée\n");
            _init_state = InitState::VERIFY_PIN;
            _init_step_start_ms = AP_HAL::millis();
        }
        break;

    case InitState::VERIFY_PIN:
        // VERIFY PIN via send_apdu
        {
            hal.console->printf("HSM: [ASYNC] Envoi VERIFY PIN via send_apdu...\n");
            

            char response[128] = {0};
            if (!send_apdu("A 00200001083030303030303030", response, sizeof(response))) {
                hal.console->printf("HSM: [ASYNC] send_apdu retourné false, response='%s'\n", response);
                _init_state = InitState::FAILED;
                return true;
            }

            hal.console->printf("HSM: [ASYNC] VERIFY PIN réponse: %s\n", response);
            

            if (strstr(response, "9000") == nullptr) {
                hal.console->printf("HSM: [ASYNC] VERIFY PIN échoué (pas de 9000)\n");
                _init_state = InitState::FAILED;
                return true;
            }
            hal.console->printf("HSM: [ASYNC] PIN vérifié\n");
            hal.console->printf("HSM: ✓ [ASYNC] Initialisation terminée avec succès!\n");
            _init_state = InitState::COMPLETE;
            return true;
        }

    default:
        break;
    }

    return false;  // Pas encore terminé
}


// Envoie une commande APDU et récupère la réponse
bool AP_HSM::send_apdu(const char* apdu, char* response, size_t response_len) {
    if (apdu == nullptr || response == nullptr || response_len == 0) {
        hal.console->printf("Erreur : Paramètres invalides pour send_apdu\n");
        return false;
    }

#if AP_HSM_MOCK_ENABLED
    // =========================================================================
    // MOCK MODE: Simulate APDU responses
    // =========================================================================
    // Parse APDU format: "A 00<INS><P1><P2><Lc/Le>[data]"
    // Examples:
    //   READ:  "A 00B0010020" -> Read 32 bytes from offset 0x0100
    //   WRITE: "A 00D0010020<64hex>" -> Write 32 bytes to offset 0x0100

    // Skip "A " prefix
    const char* cmd = apdu;
    if (cmd[0] == 'A' && cmd[1] == ' ') {
        cmd += 2;
    }

    // Parse INS byte (position 2-3 in "00XXPPPP...")
    char ins_str[3] = {cmd[2], cmd[3], '\0'};
    uint8_t ins = (uint8_t)strtol(ins_str, nullptr, 16);

    // Parse P1P2 (offset) - positions 4-7
    char p1p2_str[5] = {cmd[4], cmd[5], cmd[6], cmd[7], '\0'};
    uint16_t offset = (uint16_t)strtol(p1p2_str, nullptr, 16);

    // Parse Lc/Le (length) - positions 8-9
    char len_str[3] = {cmd[8], cmd[9], '\0'};
    uint8_t data_len = (uint8_t)strtol(len_str, nullptr, 16);

    // Convert HSM offset to mock storage offset
    // HSM uses 0x0100, 0x0120, etc. - we map to 0x00, 0x20, etc.
    uint8_t mock_offset = offset & 0xFF;

    if (ins == 0xB0) {
        // READ BINARY
        hal.console->printf("HSM: [MOCK] READ %d bytes @0x%04X (mock @0x%02X)\n",
                           data_len, offset, mock_offset);

        // Build response: "Rx: <hex data> 9000"
        strcpy(response, "Rx: ");
        char* hex_ptr = response + 4;
        for (uint8_t i = 0; i < data_len && (mock_offset + i) < sizeof(_mock_storage); i++) {
            snprintf(hex_ptr, 3, "%02X", _mock_storage[mock_offset + i]);
            hex_ptr += 2;
        }
        strcat(response, " 9000");
        return true;

    } else if (ins == 0xD0) {
        // WRITE BINARY (LeMonolith uses D0, not D6)
        hal.console->printf("HSM: [MOCK] WRITE %d bytes @0x%04X (mock @0x%02X)\n",
                           data_len, offset, mock_offset);

        // Parse hex data from APDU (starts at position 10)
        const char* hex_data = cmd + 10;
        for (uint8_t i = 0; i < data_len && (mock_offset + i) < sizeof(_mock_storage); i++) {
            char byte_str[3] = {hex_data[i*2], hex_data[i*2 + 1], '\0'};
            _mock_storage[mock_offset + i] = (uint8_t)strtol(byte_str, nullptr, 16);
        }

        strcpy(response, "Rx: 9000");
        return true;

    } else if (ins == 0xA4) {
        // SELECT - always succeed
        hal.console->printf("HSM: [MOCK] SELECT - simulated OK\n");
        strcpy(response, "Rx: 9000");
        return true;

    } else if (ins == 0x20) {
        // VERIFY PIN - always succeed
        hal.console->printf("HSM: [MOCK] VERIFY PIN - simulated OK\n");
        strcpy(response, "Rx: 9000");
        return true;

    } else {
        hal.console->printf("HSM: [MOCK] Unknown INS 0x%02X - simulated OK\n", ins);
        strcpy(response, "Rx: 9000");
        return true;
    }
#else
    if (uart_hsm == nullptr) {
        hal.console->printf("Erreur : UART non initialisé pour send_apdu\n");
        return false;
    }

    hal.console->printf("HSM: [APDU] Envoi: %s\n", apdu);


    flush_input();
    uart_hsm->printf("%s\r\n", apdu);

    // Force le scheduler à tourner pour vider le buffer UART
    for (int i = 0; i < 10; i++) {
        hal.scheduler->delay(10);
    }
    hal.console->printf("HSM: [APDU] Commande envoyée, attente réponse...\n");
    

    // Détecter commandes WRITE BINARY (00D0) qui nécessitent plus de temps pour EEPROM
    bool is_write_command = (strstr(apdu, "00D0") != nullptr);
    if (is_write_command) {
        hal.console->printf("HSM: Délai EEPROM write (3s)...\n");
        hal.scheduler->delay(3000);  // Écriture EEPROM: augmenté à 3s
    } else {
        hal.scheduler->delay(500);  // Augmenté à 500ms pour laisser le HSM répondre
    }

    hal.console->printf("HSM: [APDU] Bytes disponibles: %u\n", (unsigned)uart_hsm->available());
    

    uint32_t start = AP_HAL::millis();

    // Le HSM émet plusieurs lignes:
    // 1. Echo de la commande: "Tx: <commande>\r\n"
    // 2. Status transmission: "TxT1: <val>\r\n"
    // 3-6. Diverses lignes de status
    // N. Une ligne contenant "9000" (status word succès) OU "Rx: <data>" avec données

    char line_buffer[256];
    size_t idx = 0;

    // Fonction helper pour lire une ligne complète
    // Timeout plus long pour WRITE BINARY (EEPROM peut prendre 3-5s)
    uint32_t line_timeout = is_write_command ? 5000 : 3000;
    auto read_line = [&]() -> bool {
        idx = 0;
        start = AP_HAL::millis();
        while ((AP_HAL::millis() - start) < line_timeout && idx < sizeof(line_buffer) - 1) {
            if (uart_hsm->available() > 0) {
                char c = uart_hsm->read();
                line_buffer[idx++] = c;
                if (c == '\n') {
                    line_buffer[idx] = '\0';
                    return true;
                }
            }
            hal.scheduler->delay(5);
        }
        return false;
    };

    // Lire toutes les lignes et collecter les données
    char data_buffer[512] = {0};  // Buffer pour accumuler les données hex
    bool found_9000 = false;

    for (int line_num = 1; line_num <= 20; line_num++) {
        hal.scheduler->delay(50);
        if (uart_hsm->available() > 0 || line_num <= 3) {  // Attendre au moins 3 lignes
            if (read_line()) {
                // Chercher "9000" dans la ligne
                if (strstr(line_buffer, "9000") != nullptr) {
                    found_9000 = true;
                    break;
                }

                // Si la ligne commence par des espaces, c'est une ligne de données hex
                if (line_buffer[0] == ' ' && strlen(line_buffer) > 5) {
                    // Extraire les caractères hex (sauter les espaces initiaux)
                    const char* hex_start = line_buffer;
                    while (*hex_start == ' ') hex_start++;

                    // Copier les caractères hex dans data_buffer
                    size_t current_len = strlen(data_buffer);
                    size_t remaining = sizeof(data_buffer) - current_len - 1;

                    // Copier chaque caractère hex (ignorer les espaces dans la ligne)
                    for (const char* p = hex_start; *p != '\0' && *p != '\r' && *p != '\n' && remaining > 0; p++) {
                        if ((*p >= '0' && *p <= '9') || (*p >= 'A' && *p <= 'F') || (*p >= 'a' && *p <= 'f')) {
                            data_buffer[current_len++] = *p;
                            remaining--;
                        }
                    }
                    data_buffer[current_len] = '\0';
                }
            }
        } else if (line_num > 3) {
            // Plus de données disponibles
            break;
        }
    }

    // Construire la réponse
    if (found_9000) {
        if (strlen(data_buffer) > 0) {
            // Il y a des données: format "Rx: <data> 9000"
            snprintf(response, response_len, "Rx: %s 9000", data_buffer);
        } else {
            // Pas de données, juste le status: "Rx: 9000"
            strcpy(response, "Rx: 9000");
        }
        return true;
    }

    // Échec: pas trouvé de réponse valide
    response[0] = '\0';
    return false;
#endif  // !AP_HSM_MOCK_ENABLED
}




void AP_HSM::flush_input() {
#if AP_HSM_MOCK_ENABLED
    // Mock mode: nothing to flush
    return;
#else
    if (uart_hsm == nullptr) {
        return;
    }
    while (uart_hsm->available() > 0) {
        uart_hsm->read();
    }
#endif
}



// Récupère la clé de cryptage
bool AP_HSM::get_key(const char* apdu, char* key, size_t key_size) {
    if (uart_hsm == nullptr || apdu == nullptr || key == nullptr || key_size == 0) {
        hal.console->printf("Erreur : Paramètres invalides pour get_key\n");
        return false;
    }

    char response[128];
    if (!send_apdu(apdu, response, sizeof(response))) {
        hal.console->printf("Erreur : Échec de la récupération de la clé\n");
        return false;
    }

    // Convertir la réponse hexadécimale en bytes et stocker dans key_bytes
    if (!hexstr_to_bytes(response, key_bytes, sizeof(key_bytes))) {
        hal.console->printf("Erreur : Conversion hexadécimale échouée\n");
        return false;
    }

    // Copier la réponse brute dans le buffer fourni
    strncpy(key, response, key_size);
    key[key_size - 1] = '\0';
    return true;
}




    // Convertit une chaîne hexadécimale en bytes
bool AP_HSM::hexstr_to_bytes(const char* hexstr, uint8_t* out, size_t out_len) {
    if (hexstr == nullptr || out == nullptr || out_len == 0) {
        return false;
    }

    size_t len = strlen(hexstr);
    if (len < out_len * 2) {
        hal.console->printf("Erreur : Chaîne hexadécimale trop courte\n");
        return false;
    }

    for (size_t i = 0; i < out_len; ++i) {
        char c1 = hexstr[i * 2];
        char c2 = hexstr[i * 2 + 1];
        if (!isxdigit(c1) || !isxdigit(c2)) {
            hal.console->printf("Erreur : Caractère non-hexadécimal à la position %zu\n", i * 2);
            return false;
        }
        // Manual hex to byte conversion (avoids sscanf)
        uint8_t high = (c1 >= 'a') ? (c1 - 'a' + 10) : (c1 >= 'A') ? (c1 - 'A' + 10) : (c1 - '0');
        uint8_t low  = (c2 >= 'a') ? (c2 - 'a' + 10) : (c2 >= 'A') ? (c2 - 'A' + 10) : (c2 - '0');
        out[i] = (high << 4) | low;
    }
    return true;
}

// ============================================================================
// Feature 2: Génération et récupération sécurisée de la paire asymétrique
// ============================================================================

// Fonction RNG pour micro-ecc utilisant get_random_vals() d'ArduPilot
static int rng_function(uint8_t *dest, unsigned int size) {
    // Utiliser la fonction ArduPilot get_random_vals qui lit /dev/urandom
    if (hal.util->get_random_vals(dest, size)) {
        return 1; // Succès
    }
    return 0; // Échec
}

// Génère une paire de clés P-256 en software avec micro-ecc
bool AP_HSM::generate_keypair_p256() {
    hal.console->printf("HSM: Génération keypair P-256 (micro-ecc)...\n");

    // Configurer la fonction RNG pour micro-ecc
    uECC_set_rng(&rng_function);

    // Obtenir la courbe secp256r1
    uECC_Curve curve = uECC_secp256r1();

    // Générer la paire de clés
    // public_key: 64 bytes (non compressée, X||Y)
    // private_key: 32 bytes
    int result = uECC_make_key(public_key_cache, private_key_cache, curve);

    if (result != 1) {
        hal.console->printf("HSM: Erreur - Échec génération keypair P-256\n");
        keypair_loaded = false;
        return false;
    }

    keypair_loaded = true;
    hal.console->printf("HSM: ✓ Keypair P-256 générée avec succès\n");

    // Afficher la clé publique en hex (pour debug)
    hal.console->printf("HSM: Public key (64 bytes): ");
    for (int i = 0; i < 64; i++) {
        hal.console->printf("%02X", public_key_cache[i]);
    }
    hal.console->printf("\n");

    return true;
}

// Stocke la clé privée dans le HSM via WRITE BINARY
bool AP_HSM::store_private_key_to_hsm(const uint8_t* private_key, size_t key_len) {
    if (private_key == nullptr || key_len != 32) {
        hal.console->printf("HSM: Erreur - Clé privée invalide (doit être 32 bytes)\n");
        return false;
    }

#if AP_HSM_MOCK_ENABLED
    // Mock mode: store in RAM at offset 0x00 (simulating 0x0100)
    hal.console->printf("HSM: [MOCK] Stockage clé privée dans mock storage @0x0100...\n");
    memcpy(&_mock_storage[0x00], private_key, 32);
    hal.console->printf("HSM: [MOCK] ✓ Clé privée stockée (32 bytes)\n");
    return true;
#else
    hal.console->printf("HSM: Stockage clé privée dans HSM...\n");

    // Construction APDU WRITE BINARY
    // CLA INS P1 P2 Lc Data
    // A 00 D6 01 00 20 <32 bytes de la clé privée>
    char apdu[128];
    snprintf(apdu, sizeof(apdu), "A 00D0010020");

    // Ajouter les 32 bytes de la clé privée en hex
    for (size_t i = 0; i < key_len; i++) {
        char byte_hex[3];
        snprintf(byte_hex, sizeof(byte_hex), "%02X", private_key[i]);
        strncat(apdu, byte_hex, sizeof(apdu) - strlen(apdu) - 1);
    }

    // Envoyer l'APDU
    char response[128];
    if (!send_apdu(apdu, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout WRITE BINARY\n");
        return false;
    }

    // Vérifier le status word 9000
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - WRITE BINARY échoué. Réponse: %s\n", response);
        return false;
    }

    hal.console->printf("HSM: ✓ Clé privée stockée avec succès dans HSM\n");
    return true;
#endif
}

// Récupère la clé privée depuis le HSM via READ BINARY
bool AP_HSM::load_private_key_from_hsm() {
#if AP_HSM_MOCK_ENABLED
    // Mock mode: read from RAM at offset 0x00 (simulating 0x0100)
    hal.console->printf("HSM: [MOCK] Récupération clé privée depuis mock storage @0x0100...\n");
    memcpy(private_key_cache, &_mock_storage[0x00], 32);
    hal.console->printf("HSM: [MOCK] ✓ Clé privée récupérée (32 bytes)\n");

    // Recalculer la clé publique
    hal.console->printf("HSM: [MOCK] Recalcul de la clé publique...\n");
    uECC_Curve curve = uECC_secp256r1();
    int result = uECC_compute_public_key(private_key_cache, public_key_cache, curve);
    if (result != 1) {
        hal.console->printf("HSM: [MOCK] Erreur - Échec recalcul clé publique\n");
        keypair_loaded = false;
        return false;
    }
    keypair_loaded = true;
    hal.console->printf("HSM: [MOCK] ✓ Clé publique recalculée\n");
    return true;
#else
    hal.console->printf("HSM: Récupération clé privée depuis HSM...\n");

    // APDU READ BINARY
    // CLA INS P1 P2 Le
    // A 00 B0 01 00 20 (lire 32 bytes à l'offset 0x0100)
    const char* apdu = "A 00B0010020";

    char response[256];
    if (!send_apdu(apdu, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout READ BINARY\n");
        return false;
    }

    // Vérifier le status word 9000
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - READ BINARY échoué. Réponse: %s\n", response);
        return false;
    }

    // Extraire les 32 bytes de la clé privée de la réponse
    // Format attendu: "Rx: <64 caractères hex> 9000"
    const char* rx_marker = strstr(response, "Rx: ");
    if (rx_marker == nullptr) {
        hal.console->printf("HSM: Erreur - Format réponse invalide\n");
        return false;
    }

    // Avancer après "Rx: "
    rx_marker += 4;

    // Convertir les 64 caractères hex en 32 bytes
    if (!hexstr_to_bytes(rx_marker, private_key_cache, 32)) {
        hal.console->printf("HSM: Erreur - Conversion hex->bytes échouée\n");
        return false;
    }

    hal.console->printf("HSM: ✓ Clé privée récupérée depuis HSM (32 bytes)\n");

    // Recalculer la clé publique à partir de la clé privée
    hal.console->printf("HSM: Recalcul de la clé publique...\n");

    uECC_Curve curve = uECC_secp256r1();
    int result = uECC_compute_public_key(private_key_cache, public_key_cache, curve);

    if (result != 1) {
        hal.console->printf("HSM: Erreur - Échec recalcul clé publique\n");
        keypair_loaded = false;
        return false;
    }

    keypair_loaded = true;
    hal.console->printf("HSM: ✓ Clé publique recalculée avec succès\n");

    // Afficher la clé publique
    hal.console->printf("HSM: Public key (64 bytes): ");
    for (int i = 0; i < 64; i++) {
        hal.console->printf("%02X", public_key_cache[i]);
    }
    hal.console->printf("\n");

    return true;
#endif
}

//==============================================================================
// Feature 3: Génération DEK ChaCha20-256 et KDF Sécurisé
//==============================================================================

// Génère une DEK aléatoire de 32 bytes
bool AP_HSM::generate_dek() {
    hal.console->printf("HSM: Génération DEK (32 bytes)...\n");

    // Utiliser le RNG sécurisé d'ArduPilot
    if (!hal.util->get_random_vals(dek_cache, 32)) {
        hal.console->printf("HSM: Erreur - Échec génération DEK (RNG)\n");
        dek_loaded = false;
        return false;
    }

    dek_loaded = true;
    hal.console->printf("HSM: ✓ DEK générée avec succès\n");

    // Afficher DEK en hex (ATTENTION: en production, NE JAMAIS logger la DEK!)
    hal.console->printf("HSM: DEK (32 bytes): ");
    for (int i = 0; i < 32; i++) {
        hal.console->printf("%02X", dek_cache[i]);
    }
    hal.console->printf("\n");

    return true;
}

// Calcule ECDH avec une clé publique distante
bool AP_HSM::compute_ecdh(const uint8_t* public_key_remote, uint8_t shared_secret[32]) {
    if (public_key_remote == nullptr || shared_secret == nullptr) {
        hal.console->printf("HSM: Erreur - Paramètres invalides pour ECDH\n");
        return false;
    }

    if (!keypair_loaded) {
        hal.console->printf("HSM: Erreur - Keypair locale non chargée\n");
        return false;
    }

    hal.console->printf("HSM: Calcul ECDH...\n");

    // Utiliser micro-ecc pour calculer le secret partagé
    uECC_Curve curve = uECC_secp256r1();
    int result = uECC_shared_secret(public_key_remote, private_key_cache, shared_secret, curve);

    if (result != 1) {
        hal.console->printf("HSM: Erreur - Échec calcul ECDH\n");
        return false;
    }

    hal.console->printf("HSM: ✓ Secret ECDH calculé avec succès\n");

    // Afficher secret (ATTENTION: en production, NE JAMAIS logger le secret!)
    hal.console->printf("HSM: ECDH shared secret (32 bytes): ");
    for (int i = 0; i < 32; i++) {
        hal.console->printf("%02X", shared_secret[i]);
    }
    hal.console->printf("\n");

    return true;
}

// Dérive une wrapping key depuis le secret ECDH
bool AP_HSM::derive_wrapping_key(const uint8_t shared_secret[32], uint8_t wrapping_key[32]) {
    if (shared_secret == nullptr || wrapping_key == nullptr) {
        hal.console->printf("HSM: Erreur - Paramètres invalides pour KDF\n");
        return false;
    }

    hal.console->printf("HSM: Dérivation wrapping key (HKDF-SHA256)...\n");

    // HKDF avec salt et info
    const uint8_t salt[] = "ArduPilot-HSM-Salt-2026";
    const uint8_t info[] = "DEK-Wrapping-Key-v1";

    // Appeler HKDF-SHA256
    hkdf_sha256(salt, sizeof(salt) - 1,  // -1 pour exclure null terminator
                shared_secret, 32,
                info, sizeof(info) - 1,
                wrapping_key, 32);

    hal.console->printf("HSM: ✓ Wrapping key dérivée avec succès\n");

    // Afficher wrapping key (ATTENTION: en production, NE JAMAIS logger la clé!)
    hal.console->printf("HSM: Wrapping key (32 bytes): ");
    for (int i = 0; i < 32; i++) {
        hal.console->printf("%02X", wrapping_key[i]);
    }
    hal.console->printf("\n");

    return true;
}

// Wrap (chiffre) la DEK avec la wrapping key
// Utilise un simple XOR + HMAC pour l'intégrité (pour prototype)
// En production, utiliser AES-GCM ou ChaCha20-Poly1305
bool AP_HSM::wrap_dek(const uint8_t wrapping_key[32], uint8_t wrapped_dek[32], uint8_t auth_tag[32]) {
    if (wrapping_key == nullptr || wrapped_dek == nullptr || auth_tag == nullptr) {
        hal.console->printf("HSM: Erreur - Paramètres invalides pour wrap_dek\n");
        return false;
    }

    if (!dek_loaded) {
        hal.console->printf("HSM: Erreur - DEK non chargée\n");
        return false;
    }

    hal.console->printf("HSM: Wrap DEK...\n");

    // XOR simple pour chiffrement (prototype)
    // En production: utiliser AES-256-GCM
    for (int i = 0; i < 32; i++) {
        wrapped_dek[i] = dek_cache[i] ^ wrapping_key[i];
    }

    // Calculer HMAC-SHA256 pour l'intégrité
    hmac_sha256(wrapping_key, 32, wrapped_dek, 32, auth_tag);

    hal.console->printf("HSM: ✓ DEK wrappée avec succès\n");

    return true;
}

// Unwrap (déchiffre) la DEK avec la wrapping key
bool AP_HSM::unwrap_dek(const uint8_t wrapped_dek[32], const uint8_t auth_tag[32],
                        const uint8_t wrapping_key[32]) {
    if (wrapped_dek == nullptr || auth_tag == nullptr || wrapping_key == nullptr) {
        hal.console->printf("HSM: Erreur - Paramètres invalides pour unwrap_dek\n");
        return false;
    }

    hal.console->printf("HSM: Unwrap DEK...\n");

    // Vérifier HMAC
    uint8_t computed_tag[32];
    hmac_sha256(wrapping_key, 32, wrapped_dek, 32, computed_tag);

    // Comparer les tags
    bool tag_valid = true;
    for (int i = 0; i < 32; i++) {
        if (computed_tag[i] != auth_tag[i]) {
            tag_valid = false;
            break;
        }
    }

    if (!tag_valid) {
        hal.console->printf("HSM: Erreur - Tag HMAC invalide (corruption ou mauvaise clé)\n");
        dek_loaded = false;
        return false;
    }

    hal.console->printf("HSM: ✓ Tag HMAC vérifié\n");

    // Déchiffrer (XOR inverse)
    for (int i = 0; i < 32; i++) {
        dek_cache[i] = wrapped_dek[i] ^ wrapping_key[i];
    }

    dek_loaded = true;
    hal.console->printf("HSM: ✓ DEK unwrappée avec succès\n");

    // Afficher DEK (ATTENTION: en production, NE JAMAIS logger!)
    hal.console->printf("HSM: DEK (32 bytes): ");
    for (int i = 0; i < 32; i++) {
        hal.console->printf("%02X", dek_cache[i]);
    }
    hal.console->printf("\n");

    return true;
}

// Stocke la DEK wrappée dans le HSM (offset 0x0120, 64 bytes)
bool AP_HSM::store_dek_to_hsm(const uint8_t wrapped_dek[32], const uint8_t auth_tag[32]) {
    if (wrapped_dek == nullptr || auth_tag == nullptr) {
        hal.console->printf("HSM: Erreur - Paramètres invalides pour store_dek_to_hsm\n");
        return false;
    }

#if AP_HSM_MOCK_ENABLED
    // Mock mode: store in RAM
    // wrapped_dek @0x0120 -> offset 0x20 in mock storage
    // auth_tag @0x0140 -> offset 0x40 in mock storage
    hal.console->printf("HSM: [MOCK] Stockage DEK wrappée dans mock storage...\n");
    memcpy(&_mock_storage[0x20], wrapped_dek, 32);  // @0x0120
    memcpy(&_mock_storage[0x40], auth_tag, 32);     // @0x0140
    hal.console->printf("HSM: [MOCK] ✓ Wrapped DEK @0x0120 (32 bytes)\n");
    hal.console->printf("HSM: [MOCK] ✓ Auth tag @0x0140 (32 bytes)\n");
    return true;
#else
    hal.console->printf("HSM: Stockage DEK wrappée dans HSM (offset 0x0120)...\n");

    // Délai de récupération avant écriture (le HSM a peut-être des écritures EEPROM en arrière-plan)
    hal.console->printf("HSM: Délai de récupération EEPROM (1s)...\n");
    hal.scheduler->delay(1000);
    flush_input();

    // Écriture 1: wrapped_dek (32 bytes) à l'offset 0x0120
    // A 00 D6 01 20 20 <32 bytes wrapped_dek>
    char apdu1[128];
    snprintf(apdu1, sizeof(apdu1), "A 00D0012020");
    for (int i = 0; i < 32; i++) {
        char byte_hex[3];
        snprintf(byte_hex, sizeof(byte_hex), "%02X", wrapped_dek[i]);
        strncat(apdu1, byte_hex, sizeof(apdu1) - strlen(apdu1) - 1);
    }

    // Utiliser send_apdu() qui gère correctement les réponses multi-lignes
    char response[256];
    hal.console->printf("HSM: Envoi WRITE wrapped_dek...\n");
    if (!send_apdu(apdu1, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout WRITE wrapped_dek\n");
        return false;
    }
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - WRITE wrapped_dek échoué. Réponse: %s\n", response);
        return false;
    }
    hal.console->printf("HSM: ✓ Wrapped DEK écrite (32 bytes)\n");

    // Délai entre les deux écritures EEPROM
    hal.scheduler->delay(500);

    // Écriture 2: auth_tag (32 bytes) à l'offset 0x0140
    // A 00 D6 01 40 20 <32 bytes auth_tag>
    char apdu2[128];
    snprintf(apdu2, sizeof(apdu2), "A 00D0014020");
    for (int i = 0; i < 32; i++) {
        char byte_hex[3];
        snprintf(byte_hex, sizeof(byte_hex), "%02X", auth_tag[i]);
        strncat(apdu2, byte_hex, sizeof(apdu2) - strlen(apdu2) - 1);
    }

    hal.console->printf("HSM: Envoi WRITE auth_tag...\n");
    if (!send_apdu(apdu2, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout WRITE auth_tag\n");
        return false;
    }
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - WRITE auth_tag échoué. Réponse: %s\n", response);
        return false;
    }
    hal.console->printf("HSM: ✓ Auth tag écrit (32 bytes)\n");

    hal.console->printf("HSM: ✓ DEK wrappée stockée avec succès dans HSM (64 bytes total)\n");
    return true;
#endif
}

// Récupère la DEK wrappée depuis le HSM
bool AP_HSM::load_dek_from_hsm(uint8_t wrapped_dek[32], uint8_t auth_tag[32]) {
    if (wrapped_dek == nullptr || auth_tag == nullptr) {
        hal.console->printf("HSM: Erreur - Paramètres invalides pour load_dek_from_hsm\n");
        return false;
    }

#if AP_HSM_MOCK_ENABLED
    // Mock mode: read from RAM
    hal.console->printf("HSM: [MOCK] Récupération DEK wrappée depuis mock storage...\n");
    memcpy(wrapped_dek, &_mock_storage[0x20], 32);  // @0x0120
    memcpy(auth_tag, &_mock_storage[0x40], 32);     // @0x0140
    hal.console->printf("HSM: [MOCK] ✓ Wrapped DEK lue @0x0120 (32 bytes)\n");
    hal.console->printf("HSM: [MOCK] ✓ Auth tag lu @0x0140 (32 bytes)\n");
    return true;
#else
    hal.console->printf("HSM: Récupération DEK wrappée depuis HSM (offset 0x0120)...\n");

    // Lecture 1: wrapped_dek (32 bytes) depuis offset 0x0120
    // A 00 B0 01 20 20
    const char* apdu1 = "A 00B0012020";
    char response[256];

    if (!send_apdu(apdu1, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout READ wrapped_dek\n");
        return false;
    }
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - READ wrapped_dek échoué. Réponse: %s\n", response);
        return false;
    }

    // Extraire wrapped_dek
    const char* rx_marker = strstr(response, "Rx: ");
    if (rx_marker == nullptr) {
        hal.console->printf("HSM: Erreur - Format réponse wrapped_dek invalide\n");
        return false;
    }
    rx_marker += 4;
    if (!hexstr_to_bytes(rx_marker, wrapped_dek, 32)) {
        hal.console->printf("HSM: Erreur - Conversion hex->bytes wrapped_dek échouée\n");
        return false;
    }
    hal.console->printf("HSM: Wrapped DEK lue (32 bytes)\n");

    // Lecture 2: auth_tag (32 bytes) depuis offset 0x0140
    // A 00 B0 01 40 20
    const char* apdu2 = "A 00B0014020";

    if (!send_apdu(apdu2, response, sizeof(response))) {
        hal.console->printf("HSM: Erreur - Timeout READ auth_tag\n");
        return false;
    }
    if (strstr(response, "9000") == nullptr) {
        hal.console->printf("HSM: Erreur - READ auth_tag échoué. Réponse: %s\n", response);
        return false;
    }

    // Extraire auth_tag
    rx_marker = strstr(response, "Rx: ");
    if (rx_marker == nullptr) {
        hal.console->printf("HSM: Erreur - Format réponse auth_tag invalide\n");
        return false;
    }
    rx_marker += 4;
    if (!hexstr_to_bytes(rx_marker, auth_tag, 32)) {
        hal.console->printf("HSM: Erreur - Conversion hex->bytes auth_tag échouée\n");
        return false;
    }
    hal.console->printf("HSM: Auth tag lu (32 bytes)\n");

    hal.console->printf("HSM: ✓ DEK wrappée récupérée depuis HSM (64 bytes total)\n");
    return true;
#endif
}
