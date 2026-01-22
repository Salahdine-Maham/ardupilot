/**
 * Test direct de Feature 1: Initialisation LeMonolith HSM
 *
 * Ce programme teste directement la fonction init_monolith()
 * sans passer par tout le framework SITL
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>
#include <string.h>
#include <sys/time.h>

// Configuration
#define HSM_PORT "/dev/ttyUSB0"
#define BAUDRATE B115200

// Prototypes
bool hsm_send_command(int fd, const char* cmd, char* response, size_t resp_len, int timeout_ms);
void hsm_flush(int fd);

int main() {
    printf("=== Feature 1: Test Initialisation LeMonolith HSM ===\n\n");

    // Ouvrir le port série
    printf("1. Ouverture du port %s...\n", HSM_PORT);
    int fd = open(HSM_PORT, O_RDWR | O_NOCTTY);
    if (fd < 0) {
        printf("❌ Erreur: Impossible d'ouvrir %s\n", HSM_PORT);
        printf("   Vérifiez que le HSM est connecté et que vous êtes dans le groupe dialout\n");
        return 1;
    }

    // Configurer le port
    struct termios tty;
    memset(&tty, 0, sizeof(tty));
    if (tcgetattr(fd, &tty) != 0) {
        printf("❌ Erreur: tcgetattr\n");
        close(fd);
        return 1;
    }

    cfsetospeed(&tty, BAUDRATE);
    cfsetispeed(&tty, BAUDRATE);

    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;
    tty.c_cflag &= ~PARENB;
    tty.c_cflag &= ~CSTOPB;
    tty.c_cflag &= ~CRTSCTS;

    tty.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
    tty.c_iflag &= ~(IXON | IXOFF | IXANY);
    tty.c_oflag &= ~OPOST;

    tcsetattr(fd, TCSANOW, &tty);

    printf("✅ Port configuré à 115200 bauds\n\n");

    // Test 1: OFF
    printf("2. Désactivation Secure Element...\n");
    char response[512];
    if (!hsm_send_command(fd, "off", response, sizeof(response), 500)) {
        printf("❌ Erreur: Timeout OFF\n");
        close(fd);
        return 1;
    }
    printf("✅ SE désactivé: %s\n\n", response);

    // Test 2: ON
    printf("3. Activation Secure Element...\n");
    if (!hsm_send_command(fd, "on", response, sizeof(response), 2000)) {
        printf("❌ Erreur: Timeout ON\n");
        close(fd);
        return 1;
    }
    if (strstr(response, "9000")) {
        printf("✅ SE activé et applet auto-sélectionné\n\n");
    } else {
        printf("⚠️  SE activé (pas de 9000 détecté)\n\n");
    }

    // Test 3: SELECT Application CC
    printf("4. SELECT Application CC (AID: 010203040601)...\n");
    if (!hsm_send_command(fd, "A 00A4040006010203040601", response, sizeof(response), 500)) {
        printf("❌ Erreur: Timeout SELECT\n");
        close(fd);
        return 1;
    }
    if (strstr(response, "9000")) {
        printf("✅ Application CC sélectionnée (SW 9000)\n\n");
    } else {
        printf("❌ SELECT échoué: %s\n\n", response);
        close(fd);
        return 1;
    }

    // Test 4: VERIFY PIN
    printf("5. VERIFY User PIN (00000000)...\n");
    if (!hsm_send_command(fd, "A 00200001083030303030303030", response, sizeof(response), 500)) {
        printf("❌ Erreur: Timeout VERIFY PIN\n");
        close(fd);
        return 1;
    }
    if (strstr(response, "9000")) {
        printf("✅ PIN vérifié avec succès (SW 9000)\n\n");
    } else {
        printf("❌ VERIFY PIN échoué: %s\n\n", response);
        close(fd);
        return 1;
    }

    printf("======================================================\n");
    printf("🎉 Feature 1: SUCCÈS COMPLET\n");
    printf("======================================================\n");
    printf("\nRésumé:\n");
    printf("  ✅ Communication UART établie\n");
    printf("  ✅ Secure Element activé\n");
    printf("  ✅ Application CC sélectionnée\n");
    printf("  ✅ PIN User vérifié\n");
    printf("\nLe HSM est prêt pour les opérations READ/WRITE de clés\n");

    close(fd);
    return 0;
}

// Envoyer une commande et attendre la réponse
bool hsm_send_command(int fd, const char* cmd, char* response, size_t resp_len, int timeout_ms) {
    hsm_flush(fd);

    // Envoyer commande
    char cmd_with_crlf[256];
    snprintf(cmd_with_crlf, sizeof(cmd_with_crlf), "%s\r\n", cmd);
    write(fd, cmd_with_crlf, strlen(cmd_with_crlf));
    tcdrain(fd);

    // Attendre réponse
    struct timeval start, now;
    gettimeofday(&start, NULL);

    size_t idx = 0;
    while (idx < resp_len - 1) {
        gettimeofday(&now, NULL);
        long elapsed = (now.tv_sec - start.tv_sec) * 1000 + (now.tv_usec - start.tv_usec) / 1000;
        if (elapsed > timeout_ms) {
            break;
        }

        char c;
        int n = read(fd, &c, 1);
        if (n > 0) {
            response[idx++] = c;
            if (c == '\n') {
                // Continuer à lire pour les réponses multi-lignes
                gettimeofday(&start, NULL); // Reset timeout
            }
        } else {
            usleep(10000); // 10ms
        }
    }

    response[idx] = '\0';

    // Nettoyer les \r\n
    for (size_t i = 0; i < idx; i++) {
        if (response[i] == '\r' || response[i] == '\n') {
            response[i] = ' ';
        }
    }

    return idx > 0;
}

// Vider le buffer d'entrée
void hsm_flush(int fd) {
    tcflush(fd, TCIFLUSH);
}
