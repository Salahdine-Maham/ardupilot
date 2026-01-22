#include "AP_HSM.h"
#include <AP_HAL/AP_HAL.h>
#include <cstring>
#include <AP_SerialManager/AP_SerialManager.h>
#include <stdio.h>

#include <cctype>
#include <iostream>





extern const AP_HAL::HAL& hal;

// Initialise le pointeur à null au départ
AP_HSM* AP_HSM::_singleton = nullptr;


// Constructeur privé pour empêcher l'instanciation directe
AP_HSM::AP_HSM() {
    // Initialisation de uart_hsm (optionnel)
    memset(key_bytes, 0, sizeof(key_bytes));
    uart_hsm = nullptr; // Déjà initialisé par défaut, mais explicite ici
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
    if (uart_dev == nullptr) {
        hal.console->printf("Erreur : UART non fourni pour HSM\n");
        return;
    }

    uart_hsm = uart_dev;
    hal.console->printf("Initialisation du HSM...\n");
    uart_hsm->begin(115200);
    uart_hsm->set_flow_control(AP_HAL::UARTDriver::FLOW_CONTROL_DISABLE);
    flush_input();

    hal.console->printf("Initialisation du HSM terminée\n");
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
    if (uart_hsm == nullptr) {
        hal.console->printf("HSM: Erreur - UART non initialisé\n");
        return false;
    }

    hal.console->printf("HSM: Démarrage initialisation LeMonolith...\n");

    // Étape 1: Désactivation du Secure Element
    flush_input();
    uart_hsm->printf("off\r\n");
    hal.scheduler->delay(200);
    flush_input(); // Ignorer réponse "OK"

    hal.console->printf("HSM: SE désactivé\n");

    // Étape 2: Activation du Secure Element
    // Note: Le firmware sélectionne automatiquement l'applet CC lors du "on"
    flush_input();
    uart_hsm->printf("on\r\n");
    hal.scheduler->delay(1500); // Attendre initialisation ATR complète

    // Lire et analyser la réponse (contient ATR, PTS, etc.)
    uint32_t start = AP_HAL::millis();
    bool atr_complete = false;
    while ((AP_HAL::millis() - start) < 2000 && !atr_complete) {
        if (uart_hsm->available() > 0) {
            uart_hsm->read(); // Lire et ignorer les données d'initialisation
            // Détecter fin de l'ATR (chercher "9000" ou "OK")
            // Pour simplifier, on attend juste que le buffer se stabilise
        }
        hal.scheduler->delay(10);
    }

    flush_input(); // Vider buffer restant
    hal.console->printf("HSM: SE activé\n");

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
}



// Envoie une commande APDU et récupère la réponse
bool AP_HSM::send_apdu(const char* apdu, char* response, size_t response_len) {
    if (uart_hsm == nullptr || apdu == nullptr || response == nullptr || response_len == 0) {
        hal.console->printf("Erreur : Paramètres invalides pour send_apdu\n");
        return false;
    }

    flush_input();
    uart_hsm->printf("%s\r\n", apdu);
    printf(">> Envoi APDU : %s\n", apdu);

    uint32_t start = AP_HAL::millis();
    size_t idx = 0;
    bool response_complete = false;

    while ((AP_HAL::millis() - start) < 1000) { // Timeout de 1s
        while (uart_hsm->available() > 0 && idx < response_len - 1) {
            char rep = uart_hsm->read();
            response[idx++] = rep;
            if (rep == '\n') {
                response_complete = true;
                break;
            }
        }
        if (response_complete) {
            break;
        }
        hal.scheduler->delay(10);
    }

    if (idx > 0) {
        response[idx] = '\0';
        printf("<< Réponse APDU : %s\n", response);
        return true;
    } else {
        response[0] = '\0';
        printf("<< Réponse APDU : <vide>\n");
        return false;
    }
}




void AP_HSM::flush_input() {
    while (uart_hsm->available() > 0) {
        uart_hsm->read();
    }

}



// Récupère la clé de cryptage
bool AP_HSM::get_key(const char* apdu, char* key, size_t key_size) {
    if (uart_hsm == nullptr || apdu == nullptr || key == nullptr || key_size == 0) {
        hal.console->printf("Erreur : Paramètres invalides pour get_key\n");
        return false;
    }

    char response[128];
    if (!send_apdu(apdu, response, sizeof(response))) {
        printf("Erreur : Échec de la récupération de la clé\n");
        return false;
    }

    // Convertir la réponse hexadécimale en bytes et stocker dans key_bytes
    if (!hexstr_to_bytes(response, key_bytes, sizeof(key_bytes))) {
        printf("Erreur : Conversion hexadécimale échouée\n");
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
        printf("Erreur : Chaîne hexadécimale trop courte\n");
        return false;
    }

    for (size_t i = 0; i < out_len; ++i) {
        char byte_str[3] = { hexstr[i * 2], hexstr[i * 2 + 1], '\0' };
        if (!isxdigit(byte_str[0]) || !isxdigit(byte_str[1])) {
            printf("Erreur : Caractère non-hexadécimal à la position %zu\n", i * 2);
            return false;
        }
        sscanf(byte_str, "%2hhx", &out[i]);
    }
    return true;
}
