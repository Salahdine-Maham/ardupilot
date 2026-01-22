#pragma once
#include <AP_HAL/AP_HAL.h>   // Assurez-vous que ce fichier est inclus



/// HSM driver main class
class AP_HSM 
{

// This class provides an interface to communicate with the HSM (Hardware Security Module) over UART
// It allows for operations such as selecting the TLS-SE, verifying a PIN, reading a key, and sending APDUs.


public:

    // Initialise la communication UART avec le HSM
    void begin(AP_HAL::UARTDriver* uart_dev);

    // Feature 1: Initialisation fiable et robuste du LeMonolith
    // Active le SE, sélectionne l'applet CC et vérifie le PIN
    bool init_monolith();

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
    // Instance unique
   
    
    static AP_HSM* _singleton;
  //  AP_HAL::UARTDriver*  uart_hsm ;
    
};
