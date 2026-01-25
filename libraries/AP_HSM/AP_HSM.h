#pragma once
#include <AP_HAL/AP_HAL.h>
#include <stdint.h>

// =============================================================================
// MOCK HSM CONFIGURATION
// =============================================================================
// Set to 1 to enable Mock HSM (simulated in RAM, no real hardware needed)
// Set to 0 to use real HSM hardware via UART
// Use Mock for Pixhawk testing without TELEM2 cable
#ifndef AP_HSM_MOCK_ENABLED
#define AP_HSM_MOCK_ENABLED 1
#endif
// =============================================================================

/// HSM driver main class
class AP_HSM
{

// This class provides an interface to communicate with the HSM (Hardware Security Module) over UART
// It allows for operations such as selecting the TLS-SE, verifying a PIN, reading a key, and sending APDUs.


public:
    // État de l'init async
    enum class InitState : uint8_t {
        NOT_STARTED = 0,
        SENDING_OFF,
        WAIT_OFF_DELAY,
        SENDING_ON,
        WAIT_ON_DELAY,
        READING_ATR,
        FLUSHING,
        SELECT_CC,
        VERIFY_PIN,
        COMPLETE,
        FAILED
    };

    // Initialise la communication UART avec le HSM
    void begin(AP_HAL::UARTDriver* uart_dev);

    // Feature 1: Initialisation fiable et robuste du LeMonolith
    // Active le SE, sélectionne l'applet CC et vérifie le PIN
    bool init_monolith();

    // Feature 1 ASYNC: Init non-bloquante
    // Appeler start_init_async() une fois, puis update_init() régulièrement
    void start_init_async();
    bool update_init();  // Retourne true quand terminé (succès ou échec)
    bool is_init_complete() const { return _init_state == InitState::COMPLETE; }
    bool is_init_failed() const { return _init_state == InitState::FAILED; }
    InitState get_init_state() const { return _init_state; }

    // Feature 2: Génération et récupération sécurisée de la paire asymétrique
    // Génère une paire de clés P-256 en software (micro-ecc)
    bool generate_keypair_p256();

    // Stocke la clé privée dans le HSM via WRITE BINARY
    bool store_private_key_to_hsm(const uint8_t* private_key, size_t key_len);

    // Récupère la clé privée depuis le HSM via READ BINARY
    bool load_private_key_from_hsm();

    // Accesseurs pour les clés (cache RAM volatile)
    const uint8_t* get_private_key() const { return private_key_cache; }
    const uint8_t* get_public_key() const { return public_key_cache; }
    bool has_keypair() const { return keypair_loaded; }

    // Feature 3: Génération DEK ChaCha20-256 et KDF sécurisé

    // Génère une DEK (Data Encryption Key) aléatoire de 32 bytes
    bool generate_dek();

    // Calcule ECDH avec une clé publique distante
    // public_key_remote: clé publique P-256 de 64 bytes (format non compressé)
    // shared_secret: buffer de sortie de 32 bytes pour le secret partagé
    bool compute_ecdh(const uint8_t* public_key_remote, uint8_t shared_secret[32]);

    // Dérive une wrapping key depuis le secret ECDH
    // shared_secret: secret ECDH de 32 bytes
    // wrapping_key: buffer de sortie de 32 bytes
    bool derive_wrapping_key(const uint8_t shared_secret[32], uint8_t wrapping_key[32]);

    // Wrap (chiffre) la DEK avec la wrapping key
    // wrapping_key: clé de chiffrement de 32 bytes
    // wrapped_dek: buffer de sortie de 32 bytes (DEK chiffrée)
    // auth_tag: buffer de sortie de 32 bytes (HMAC pour intégrité)
    bool wrap_dek(const uint8_t wrapping_key[32], uint8_t wrapped_dek[32], uint8_t auth_tag[32]);

    // Unwrap (déchiffre) la DEK avec la wrapping key
    // wrapped_dek: DEK chiffrée de 32 bytes
    // auth_tag: HMAC de 32 bytes pour vérification
    // wrapping_key: clé de déchiffrement de 32 bytes
    bool unwrap_dek(const uint8_t wrapped_dek[32], const uint8_t auth_tag[32],
                    const uint8_t wrapping_key[32]);

    // Stocke la DEK wrappée dans le HSM (offset 0x0120, 64 bytes)
    // wrapped_dek: DEK chiffrée de 32 bytes
    // auth_tag: HMAC de 32 bytes
    bool store_dek_to_hsm(const uint8_t wrapped_dek[32], const uint8_t auth_tag[32]);

    // Récupère la DEK wrappée depuis le HSM
    // wrapped_dek: buffer de sortie de 32 bytes
    // auth_tag: buffer de sortie de 32 bytes
    bool load_dek_from_hsm(uint8_t wrapped_dek[32], uint8_t auth_tag[32]);

    // Accesseur pour la DEK
    const uint8_t* get_dek() const { return dek_cache; }
    bool has_dek() const { return dek_loaded; }

    // Mode simulation pour SITL (tests sans hardware)
    void enable_simulation_mode() { simulation_mode = true; }
    bool is_simulation_mode() const { return simulation_mode; }

    // Envoie une commande APDU et récupère la réponse
    bool send_apdu(const char* apdu, char* response, size_t response_len);


    // Accesseur pour la clé stockée
    uint8_t* get_key_bytes()  { return key_bytes; }
    size_t get_key_bytes_len() const { return sizeof(key_bytes); }

    void flush_input();
 
    bool get_key(const char* apdu, char* key, size_t key_size);
    bool hexstr_to_bytes(const char* hexstr, uint8_t* out, size_t out_len) ;
    
    static AP_HSM& get_singleton();

protected:


private:

    // Constructeur privé
    AP_HSM();
    AP_HAL::UARTDriver* uart_hsm = nullptr;
    uint8_t key_bytes[32];

    // Feature 2: Cache RAM volatile pour keypair P-256
    uint8_t private_key_cache[32];  // Clé privée P-256 (32 bytes)
    uint8_t public_key_cache[64];   // Clé publique P-256 non compressée (64 bytes)
    bool keypair_loaded = false;    // Indique si une keypair est chargée en cache

    // Feature 3: Cache RAM volatile pour DEK ChaCha20-256
    uint8_t dek_cache[32];          // Data Encryption Key (32 bytes)
    bool dek_loaded = false;        // Indique si une DEK est chargée en cache

    // Mode simulation pour tests SITL (sans hardware)
    bool simulation_mode = false;

    // État pour init async
    InitState _init_state = InitState::NOT_STARTED;
    uint32_t _init_step_start_ms = 0;
    uint8_t _flush_count = 0;

#if AP_HSM_MOCK_ENABLED
    // =============================================================================
    // MOCK HSM Storage (simulates HSM EEPROM in RAM)
    // =============================================================================
    // Memory map (same as real HSM):
    //   0x0100 (0x00): Master Key (32 bytes)
    //   0x0120 (0x20): Wrapped WK_private (32 bytes)
    //   0x0140 (0x40): Wrapped DEK (32 bytes)
    //   0x0160 (0x60): HMAC tag WK (32 bytes)
    //   0x0180 (0x80): HMAC tag DEK (32 bytes)
    uint8_t _mock_storage[256];
    bool _mock_initialized = false;
#endif

    // Instance unique
    static AP_HSM* _singleton;

};
