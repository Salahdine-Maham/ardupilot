#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#include <stdint.h>
#include <stdlib.h>

int open_serial(const char *port) {
    int fd = open(port, O_RDWR | O_NOCTTY);
    struct termios tty;

    if (fd < 0) {
        perror("open");
        return -1;
    }

    tcgetattr(fd, &tty);
    cfsetospeed(&tty, B115200);
    cfsetispeed(&tty, B115200);

    tty.c_cflag |= (CLOCAL | CREAD);     // Enable receiver
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;                  // 8-bit chars
    tty.c_cflag &= ~PARENB;              // No parity
    tty.c_cflag &= ~CSTOPB;              // 1 stop bit
    //tty.c_cflag &= ~CRTSCTS;             // No flow control
    tty.c_lflag = 0;                     // Raw input
    tty.c_oflag = 0;                     // Raw output
    tty.c_cc[VMIN] = 1;
    tty.c_cc[VTIME] = 5;

    tcsetattr(fd, TCSANOW, &tty);
    return fd;
}

void send_apdu1(int fd, unsigned char *apdu, size_t len) {
    write(fd, apdu, len);
    printf(">> Envoi APDU :");
    for (size_t i = 0; i < len; i++) {
        printf(" %02X", apdu[i]);
    }
    printf("\n");
}


void  send_apdu(int fd, const char *apdu) {
    char buffer[512];
    snprintf(buffer, sizeof(buffer), "%s\r\n", apdu);
    write(fd, buffer, strlen(buffer));
    printf(">> Envoi : %s", buffer);
    usleep(500000); // Attendre 500ms
    char response[32] = {0};
    int n = read(fd, response, sizeof(response)-1);
    
    if (n > 0) {
        response[n] = '\0';
        printf("Réponse: %s\n", response);
       
    }
}

void get_key(int fd, const char *apdu, char *key, size_t key_size) {
    char buffer[512];
    snprintf(buffer, sizeof(buffer), "%s\r\n", apdu);
    write(fd, buffer, strlen(buffer));
    usleep(500000);

    int n = read(fd, key, key_size - 1);
    if (n > 0) {
        key[n] = '\0';  // null-terminate
    } else {
        key[0] = '\0';
    }
}


void  read_response(int fd) {
    unsigned char buf[256];
    int n = read(fd, buf, sizeof(buf));
    if (n > 0) {
        printf("<< Réponse (%d octets) :", n);
        for (int i = 0; i < n; i++) {
            printf(" %02X", buf[i]);
        }
        printf("\n");
    } else {
        printf("<< Aucune réponse reçue\n");
    }
}


void send_command(int fd, const char *cmd) {
    write(fd, cmd, strlen(cmd));
    printf(">> Envoi : %s", cmd);
    usleep(100000); // 100ms
}


void hexstr_to_bytes(const char* hexstr, uint8_t* out, size_t out_len) {
    for (size_t i = 0; i < out_len; i++) {
        sscanf(hexstr + 2 * i, "%2hhx", &out[i]);
    }
}


int main() {
    const char *portname = "/dev/ttyUSB0";
    // int fd = open_serial(portname);
    // if (fd < 0) return 1;

    // // DTR/RTS init manuelle — nécessite ioctl si vraiment nécessaire
    // // ici, on saute cette étape pour simplifier

    // // Commande texte "on\r\n"
    // send_command(fd, "on\r\n");

    // // Commande APDU sous forme texte (pour test)
    // send_command(fd, "A 00A4040006010203040500 \r\n");

    // // Commande binaire APDU
    // unsigned char apdu[] = {
    //     0x00, 0xA4, 0x04, 0x00,
    //     0x07, 0x06, 0x01, 0x02, 0x03, 0x04, 0x05, 0x00
    // };
    // send_apdu1(fd, apdu, sizeof(apdu));

    // sleep(1);
    // read_response(fd);

    // close(fd);

    
int fd = open_serial("/dev/ttyUSB0");

write(fd, "on\r\n", 4);
usleep(500000);
// send_apdu(fd, "A 00A4040006010203040500");
// send_apdu(fd, "A 00200001083030303030303030");
// send_apdu(fd, "A 0081000000");
// send_apdu(fd, "A 0089010000");
// send_apdu(fd, "A 0082000000");
// send_apdu(fd, "A 0084060043");
// send_apdu(fd, "A 008A010041043288117A7871F1CC92E3204D444BD9E656C2047D4FCE189F2F3F22AF01B07D2665F0C533206333E37454ABD00A2803E07BF7336ED6AE74D94D874334A022AEF");



    // 2. Sélectionner l'app Crypto Currency
    send_apdu(fd, "A 00A4040006010203040500");

    // 3. Authentification administrateur (PIN = 00000000)
    send_apdu(fd, "A 00200001083030303030303030");

    //send_apdu(fd, "A 008700000A");

    // 4. Écrire la clé ChaCha20 (32 octets) à l’adresse 100 (en décimal)
    // Exemple : 32 octets = "00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF"
   // send_apdu(fd, "A 00D001002000112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF");

    // 5. Lire la clé depuis l’adresse 100
   
    size_t key_size = 32;
    char key[32];
    uint8_t hex_key[32];
    get_key(fd, "A 00B0010020", key, key_size);
    hexstr_to_bytes(hex_key, key, 32);

      // Afficher pour vérifier
      printf("uint8_t key[] = {\n");
      for (int i = 0; i < 32; ++i) {
          printf(" 0x%02x%s", key[i], (i < 31) ? "," : "");
          if ((i + 1) % 4 == 0) printf("\n");
      }
      printf("};\n");

    // 6. Éteindre la carte
    send_apdu(fd, "off");



close(fd);
    return 0;
}
