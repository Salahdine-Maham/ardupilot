#include <iostream>
#include <libserial/SerialStream.h>
#include <libserial/SerialPort.h>
#include <libserial/SerialStreamBuf.h>
#include <libserialport.h>
#include <thread>
#include <chrono>

void send_command(serial::Serial &port, const std::string &cmd) {
    std::string full = cmd + "\r\n";
    port.write(full);
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    std::string resp = port.readline(128, "\n");
    std::cout << "[HSM] " << resp;
}

int main() {
    serial::Serial hsm("/dev/ttyUSB0", 115200, serial::Timeout::simpleTimeout(1000));

    if (!hsm.isOpen()) {
        std::cerr << "HSM not connected.\n";
        return 1;
    }

    std::cout << "HSM connected.\n";

    send_command(hsm, "on");
    send_command(hsm, "A 00A4040006010203040500"); // Select TLS-SE
    send_command(hsm, "A 002000010800000000");     // Verify PIN (8 zéros)
    send_command(hsm, "A 00B0100020");             // Read 32 bytes (ChaCha20 key)
    send_command(hsm, "off");

    return 0;
}
