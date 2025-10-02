/*
 * udpserver.c - A simple UDP echo server with optional ChaCha20 decryption
 * usage: udpserver <port> [-e]
 * -e: Enable ChaCha20 decryption
 */

#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <netdb.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <stdbool.h>
#include "chacha20.h"
#include "chacha20.c"

#define BUFSIZE 2048 // Adjusted to a power of 2
#define HEADER_SIZE 10 // Assumed header size
#define TRAILER_SIZE 2 // Assumed trailer size

/*
 * error - wrapper for perror
 */
void udpservererror(char *msg) {
  perror(msg);
  exit(1);
}

// Print byte array in hexadecimal
static void hex_print(uint8_t* pv, uint16_t s, uint16_t len) {
  if (pv == NULL) {
    printf("NULL\n");
    return;
  }
  for (unsigned int i = s; i < len; ++i) {
    printf("%02x ", pv[i]);
  }
  printf("\n\n");
}

int udpserver(int argc, char **argv) {
  int sockfd; /* socket */
  int portno; /* port to listen on */
  int clientlen; /* byte size of client's address */
  struct sockaddr_in serveraddr; /* server's addr */
  struct sockaddr_in clientaddr; /* client addr */
  struct hostent *hostp; /* client host info */
  char buf[BUFSIZE]; /* message buf */
  char *hostaddrp; /* dotted decimal host addr string */
  int optval; /* flag value for setsockopt */
  int n; /* message byte size */
  bool encrypt = false; /* encryption flag */

  /* Check command line arguments */
  if (argc < 2 || argc > 3) {
    fprintf(stderr, "usage: %s <port> [-e]\n", argv[0]);
    exit(1);
  }
  portno = atoi(argv[1]);
  if (argc == 3) {
    if (strcmp(argv[2], "-e") == 0) {
      encrypt = true;
      printf("ChaCha20 decryption enabled\n");
    } else {
      fprintf(stderr, "Invalid option: %s\n", argv[2]);
      exit(1);
    }
  } else {
    printf("Running without decryption\n");
  }

  /* Create socket */
  sockfd = socket(AF_INET, SOCK_DGRAM, 0);
  if (sockfd < 0)
    udpservererror("ERROR opening socket");

  /* Set SO_REUSEADDR */
  optval = 1;
  setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR,
             (const void *)&optval, sizeof(int));

  /* Build server's Internet address */
  bzero((char *)&serveraddr, sizeof(serveraddr));
  serveraddr.sin_family = AF_INET;
  serveraddr.sin_addr.s_addr = htonl(INADDR_ANY);
  serveraddr.sin_port = htons((unsigned short)portno);

  /* Bind socket */
  if (bind(sockfd, (struct sockaddr *)&serveraddr,
           sizeof(serveraddr)) < 0)
    udpservererror("ERROR on binding");

  /* Main loop */
  clientlen = sizeof(clientaddr);
  while (1) {
    /* Receive datagram */
    bzero(buf, BUFSIZE);
    n = recvfrom(sockfd, buf, BUFSIZE-1, 0,
                 (struct sockaddr *)&clientaddr, &clientlen);
    if (n < 0)
      udpservererror("ERROR in recvfrom");

    /* Ensure buffer is null-terminated for safety */
    buf[n] = '\0';

    /* Print header and raw data */
    printf("\n--------------------------------------------------------\n");
    printf("Header (%d bytes):\n", HEADER_SIZE);
    hex_print((uint8_t *)buf, 0, HEADER_SIZE > n ? n : HEADER_SIZE);
    printf("Raw data (%d bytes):\n", n - HEADER_SIZE - TRAILER_SIZE);
    hex_print((uint8_t *)buf, HEADER_SIZE, n - TRAILER_SIZE);

    /* Process data */
    uint8_t *data = (uint8_t *)buf + HEADER_SIZE;
    int data_len = n - HEADER_SIZE - TRAILER_SIZE;
    uint8_t processed[data_len];

    if (encrypt && data_len > 0) {
      /* ChaCha20 decryption */
      uint8_t key[] = {
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
        0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
        0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f
      };
      uint8_t nonce[] = {
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x4a,
        0x00, 0x00, 0x00, 0x00
      };
      ChaCha20XOR(key, 1, nonce, data, processed, data_len);
      printf("Decrypted data (%d bytes):\n", data_len);
      hex_print(processed, 0, data_len);
    } else {
      /* No encryption, copy raw data */
      memcpy(processed, data, data_len);
      printf("Processed data (raw, %d bytes):\n", data_len);
      hex_print(processed, 0, data_len);
    }

    /* Get client info */
    hostp = gethostbyaddr((const char *)&clientaddr.sin_addr.s_addr,
                          sizeof(clientaddr.sin_addr.s_addr), AF_INET);
    if (hostp == NULL)
      udpservererror("ERROR on gethostbyaddr");
    hostaddrp = inet_ntoa(clientaddr.sin_addr);
    if (hostaddrp == NULL)
      udpservererror("ERROR on inet_ntoa\n");

    /* Echo original buffer back */
    n = sendto(sockfd, buf, n, 0,
               (struct sockaddr *)&clientaddr, clientlen);
    if (n < 0)
      udpservererror("ERROR in sendto");
  }
}

int main(int argc, char **argv) {
  int status = udpserver(argc, argv);
  return status;
}
