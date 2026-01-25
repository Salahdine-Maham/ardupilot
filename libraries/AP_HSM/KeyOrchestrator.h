#pragma once

#include <AP_HAL/AP_HAL.h>
#include <stdint.h>
#include <stddef.h>

// Forward declaration
class AP_HSM;

/**
 * @class KeyOrchestrator
 * @brief Gestionnaire centralisé de la hiérarchie de clés cryptographiques v2.0
 *
 * Implémente une hiérarchie à 3 niveaux:
 *   - Niveau 1: Master Key (MK) - ChaCha20-256, stockée HSM @0x0100
 *   - Niveau 2: Wrapper Key (WK) - P-256, dérivée MK via HKDF, wrappée @0x0120
 *   - Niveau 3: Data Encryption Key (DEK) - ChaCha20-256, wrappée @0x0140
 *
 * Architecture v2.0:
 *   MK (HSM @0x0100) ──HKDF-SHA256──> WK_priv (wrappée @0x0120)
 *                                            │
 *                                     micro-ecc──> WK_pub (cache RAM)
 *                                            │
 *                                     Random──> DEK (wrappée @0x0140)
 *
 * Wrapping: XOR avec MK + HMAC-SHA256 pour intégrité
 */
class KeyOrchestrator
{
public:
    // Singleton pattern
    static KeyOrchestrator& get_singleton();
    static KeyOrchestrator& get_instance() { return get_singleton(); }  // Alias

    // Initialisation avec AP_HSM
    bool init(AP_HSM* hsm);

    // ═══════════════════════════════════════════════════════════════════════
    // CYCLE DE VIE MISSION (v2.0)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Initialise toute la hiérarchie de clés pour une nouvelle mission
     *
     * Séquence:
     * 1. Génère Master Key (32 bytes random) → HSM @0x0100
     * 2. Dérive Wrapper Key via HKDF-SHA256 → P-256 scalar
     * 3. Calcule WK_public depuis WK_private
     * 4. Génère DEK (32 bytes random)
     * 5. Wrappe et stocke WK + DEK dans HSM
     *
     * @return true si succès
     */
    bool init_mission_keys();

    /**
     * @brief Restaure les clés depuis le HSM après un reboot
     *
     * Séquence:
     * 1. Charge MK depuis HSM @0x0100
     * 2. Charge et unwrap WK depuis HSM @0x0120
     * 3. Recalcule WK_public
     * 4. Charge et unwrap DEK depuis HSM @0x0140
     *
     * @return true si succès, false si pas de clés ou corruption
     */
    bool restore_mission_keys();

    /**
     * @brief Vérifie si toutes les clés sont initialisées
     * @return true si MK + WK + DEK sont toutes chargées
     */
    bool is_fully_initialized() const;

    // ═══════════════════════════════════════════════════════════════════════
    // NIVEAU 1: MASTER KEY (MK)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Génère une nouvelle Master Key (32 bytes random)
     * @return true si génération réussie
     */
    bool generate_master_key();

    /**
     * @brief Stocke la MK dans le HSM @0x0100
     * @return true si écriture réussie
     */
    bool store_mk_to_hsm();

    /**
     * @brief Charge la MK depuis le HSM @0x0100
     * @return true si lecture réussie et MK valide
     */
    bool load_mk_from_hsm();

    /**
     * @brief Vérifie si une Master Key est chargée en mémoire
     * @return true si MK disponible
     */
    bool has_master_key() const { return _mk_loaded; }

    // ═══════════════════════════════════════════════════════════════════════
    // NIVEAU 2: WRAPPER KEY (WK)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Dérive la Wrapper Key depuis la Master Key via HKDF-SHA256
     *
     * Utilise derive_p256_scalar_from_hkdf() pour assurer un scalar valide
     *
     * @return true si dérivation réussie
     */
    bool derive_wrapper_key();

    /**
     * @brief Calcule WK_public depuis WK_private avec micro-ecc
     * @return true si calcul réussi
     */
    bool compute_wk_public();

    /**
     * @brief Wrappe et stocke WK_private dans HSM @0x0120, tag @0x0160
     * @return true si stockage réussi
     */
    bool store_wk_to_hsm();

    /**
     * @brief Charge et unwrappe WK_private depuis HSM
     * @return true si chargement et vérification HMAC réussis
     */
    bool load_wk_from_hsm();

    /**
     * @brief Retourne la clé publique WK (64 bytes, format X||Y)
     * @return Pointeur vers WK_PUBLIC ou nullptr si non chargée
     */
    const uint8_t* get_wk_public() const;

    /**
     * @brief Retourne la clé privée WK (32 bytes) - ATTENTION usage interne
     * @return Pointeur vers WK_PRIVATE ou nullptr si non chargée
     */
    const uint8_t* get_wk_private() const;

    /**
     * @brief Vérifie si la Wrapper Key est chargée
     * @return true si WK disponible
     */
    bool has_wrapper_key() const { return _wk_loaded; }

    // ═══════════════════════════════════════════════════════════════════════
    // NIVEAU 3: DATA ENCRYPTION KEY (DEK)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Génère une nouvelle DEK (32 bytes random)
     * @return true si génération réussie
     */
    bool generate_dek();

    /**
     * @brief Wrappe et stocke la DEK dans HSM @0x0140, tag @0x0180
     * @return true si stockage réussi
     */
    bool store_dek_to_hsm();

    /**
     * @brief Charge et unwrappe la DEK depuis HSM
     * @return true si chargement et vérification HMAC réussis
     */
    bool load_dek_from_hsm();

    /**
     * @brief Retourne la DEK courante (32 bytes)
     * @return Pointeur vers MY_DEK ou nullptr si non générée
     */
    const uint8_t* get_my_dek() const;

    /**
     * @brief Vérifie si une DEK est disponible
     * @return true si DEK générée
     */
    bool has_dek() const { return _dek_loaded; }

    // ═══════════════════════════════════════════════════════════════════════
    // WRAPPING / UNWRAPPING (XOR + HMAC-SHA256)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Wrappe une clé avec la Master Key (XOR + HMAC)
     *
     * @param key Clé à wrapper (32 bytes)
     * @param wrapped Buffer sortie clé wrappée (32 bytes)
     * @param tag Buffer sortie tag HMAC (32 bytes)
     * @return true si wrapping réussi
     */
    bool wrap_key(const uint8_t* key, uint8_t* wrapped, uint8_t* tag);

    /**
     * @brief Unwrappe une clé avec la Master Key (vérifie HMAC puis XOR)
     *
     * @param wrapped Clé wrappée (32 bytes)
     * @param tag Tag HMAC attendu (32 bytes)
     * @param key Buffer sortie clé déwrappée (32 bytes)
     * @return true si unwrapping et vérification HMAC réussis
     */
    bool unwrap_key(const uint8_t* wrapped, const uint8_t* tag, uint8_t* key);

    // ═══════════════════════════════════════════════════════════════════════
    // GESTION DES DEK PEERS (pour Feature 2)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Stocke la DEK d'un peer après Key Exchange
     */
    bool store_peer_dek(const char* peer_id, const uint8_t peer_dek[32]);

    /**
     * @brief Récupère la DEK d'un peer
     */
    const uint8_t* get_peer_dek(const char* peer_id) const;

    /**
     * @brief Vérifie si on a la DEK d'un peer
     */
    bool has_peer_dek(const char* peer_id) const;

    /**
     * @brief Supprime la DEK d'un peer
     */
    bool remove_peer_dek(const char* peer_id);

    /**
     * @brief Retourne le nombre de peers enregistrés
     */
    uint8_t get_peer_count() const { return _peer_count; }

    // ═══════════════════════════════════════════════════════════════════════
    // OPÉRATIONS ECIES (pour Feature 2)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Chiffre ma DEK avec ECIES pour un peer
     */
    bool ecies_encrypt_my_dek(const uint8_t peer_wk_pub[64],
                               uint8_t out_ephemeral_pub[64],
                               uint8_t out_nonce[12],
                               uint8_t out_ciphertext[32],
                               uint8_t out_tag[16]);

    /**
     * @brief Déchiffre la DEK d'un peer avec ECIES
     */
    bool ecies_decrypt_peer_dek(const uint8_t ephemeral_pub[64],
                                 const uint8_t nonce[12],
                                 const uint8_t ciphertext[32],
                                 const uint8_t tag[16],
                                 uint8_t out_peer_dek[32]);

    // ═══════════════════════════════════════════════════════════════════════
    // UTILITAIRES
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @brief Efface toutes les clés de la mémoire (sécurité)
     */
    void secure_erase_all();

    /**
     * @brief Retourne les statistiques du Key Orchestrator
     */
    struct Stats {
        bool mk_loaded;
        bool wk_loaded;
        bool dek_loaded;
        uint8_t peer_count;
        uint32_t init_time_ms;
    };
    Stats get_stats() const;

    /**
     * @brief Affiche l'état dans les logs (debug)
     */
    void print_status() const;

private:
    // Constructeur privé (singleton)
    KeyOrchestrator();

    // Référence vers AP_HSM
    AP_HSM* _hsm;
    bool _initialized;

    // ═══════════════════════════════════════════════════════════════════════
    // CACHE SÉCURISÉ EN RAM
    // ═══════════════════════════════════════════════════════════════════════

    // Niveau 1: Master Key (nécessaire pour wrap/unwrap)
    uint8_t _master_key[32];
    bool _mk_loaded;

    // Niveau 2: Wrapper Key (P-256)
    uint8_t _wk_private[32];      // Clé privée WK (P-256 scalaire)
    uint8_t _wk_public[64];       // Clé publique WK (P-256 point X||Y)
    bool _wk_loaded;

    // Niveau 3: Ma DEK
    uint8_t _my_dek[32];
    bool _dek_loaded;

    // Timestamp initialisation
    uint32_t _init_time_ms;

    // DEKs des peers (pour Feature 2)
    static const uint8_t MAX_PEERS = 8;
    struct PeerDekEntry {
        char peer_id[32];
        uint8_t dek[32];
        bool active;
    };
    PeerDekEntry _peer_deks[MAX_PEERS];
    uint8_t _peer_count;

    // ═══════════════════════════════════════════════════════════════════════
    // CONSTANTES HSM v2.0
    // ═══════════════════════════════════════════════════════════════════════

    // Offsets EEPROM dans le HSM (v2.0)
    static const uint16_t HSM_OFFSET_MK      = 0x0100;  // Master Key: 32 bytes
    static const uint16_t HSM_OFFSET_WK      = 0x0120;  // Wrapped WK_private: 32 bytes
    static const uint16_t HSM_OFFSET_DEK     = 0x0140;  // Wrapped DEK: 32 bytes
    static const uint16_t HSM_OFFSET_WK_TAG  = 0x0160;  // HMAC tag WK: 32 bytes
    static const uint16_t HSM_OFFSET_DEK_TAG = 0x0180;  // HMAC tag DEK: 32 bytes

    // Taille des clés
    static const uint8_t KEY_SIZE = 32;
    static const uint8_t TAG_SIZE = 32;
    static const uint8_t WK_PUBLIC_SIZE = 64;

    // ═══════════════════════════════════════════════════════════════════════
    // HELPERS PRIVÉS
    // ═══════════════════════════════════════════════════════════════════════

    // Lecture/écriture HSM
    bool read_from_hsm(uint16_t offset, uint8_t* buffer, size_t len);
    bool write_to_hsm(uint16_t offset, const uint8_t* data, size_t len);

    // Dérivation HKDF avec validation P-256 scalar
    bool derive_p256_scalar_from_hkdf(const uint8_t* ikm, size_t ikm_len, uint8_t* scalar);

    // Validation scalar P-256 (doit être < ordre de la courbe)
    bool is_valid_p256_scalar(const uint8_t* scalar);

    // Effacement sécurisé de mémoire
    void secure_memzero(void* ptr, size_t len);

    // Recherche de peer
    int find_peer_index(const char* peer_id) const;

    // Vérifier si HSM contient une MK valide
    bool check_hsm_has_valid_mk();

    // Singleton
    static KeyOrchestrator* _singleton;
};
