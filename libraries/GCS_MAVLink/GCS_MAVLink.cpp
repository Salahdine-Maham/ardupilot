/*
   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/// @file	GCS_MAVLink.cpp

/*
This provides some support code and variables for MAVLink enabled sketches

*/

#include "GCS_config.h"

#if HAL_MAVLINK_BINDINGS_ENABLED

#include "GCS.h"
#include "GCS_MAVLink.h"

#include <AP_Common/AP_Common.h>
#include <AP_HAL/AP_HAL.h>

#ifndef AP_HSM_ENABLED
#define AP_HSM_ENABLED 1
#endif

#if AP_HSM_ENABLED
#include <AP_HSM/AP_HSM.h>
#include <AP_HSM/DualDekEngine.h>
#include <AP_HSM/KeyOrchestrator.h>
#include "chacha20.h"
// Session 21: Include MAVLink CRC functions for recalculating CRC on ciphertext
#include "include/mavlink/v2.0/checksum.h"
#include "include/mavlink/v2.0/mavlink_types.h"
#endif

extern const AP_HAL::HAL& hal;

#ifdef MAVLINK_SEPARATE_HELPERS
// Shut up warnings about missing declarations; TODO: should be fixed on
// mavlink/pymavlink project for when MAVLINK_SEPARATE_HELPERS is defined
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wmissing-declarations"
#include "include/mavlink/v2.0/mavlink_helpers.h"
#pragma GCC diagnostic pop
#endif

mavlink_message_t* mavlink_get_channel_buffer(uint8_t chan) {
#if HAL_GCS_ENABLED
    GCS_MAVLINK *link = gcs().chan(chan);
    if (link == nullptr) {
        return nullptr;
    }
    return link->channel_buffer();
#else
    return nullptr;
#endif
}

mavlink_status_t* mavlink_get_channel_status(uint8_t chan) {
#if HAL_GCS_ENABLED
    GCS_MAVLINK *link = gcs().chan(chan);
    if (link == nullptr) {
        return nullptr;
    }
    return link->channel_status();
#else
    return nullptr;
#endif
}

#endif // HAL_MAVLINK_BINDINGS_ENABLED

#if HAL_GCS_ENABLED

AP_HAL::UARTDriver	*mavlink_comm_port[MAVLINK_COMM_NUM_BUFFERS];
bool gcs_alternative_active[MAVLINK_COMM_NUM_BUFFERS];

// per-channel lock
static HAL_Semaphore chan_locks[MAVLINK_COMM_NUM_BUFFERS];
static bool chan_discard[MAVLINK_COMM_NUM_BUFFERS];

#if AP_HSM_ENABLED
// Feature 3: Track buffer index to encrypt only payload (buffer #1)
// Sequence: 0=Header, 1=Payload, 2=Checksum, 3=Signature
static uint8_t send_buffer_index[MAVLINK_COMM_NUM_BUFFERS] = {0};

// Feature 3: Store header fields for deterministic nonce
// MAVLink v2 header: STX(1) + len(1) + incompat(1) + compat(1) + seq(1) + sysid(1) + compid(1) + msgid(3)
struct tx_msg_info {
    uint8_t seq;
    uint8_t sysid;
    uint8_t compid;
    uint32_t msgid;
    bool valid;
};
static tx_msg_info tx_header_info[MAVLINK_COMM_NUM_BUFFERS] = {};

// Session 21 - CRC Fix: Store header and ciphertext for CRC recalculation
// When we encrypt the payload in buffer[1], we need to recalculate CRC in buffer[2]
// because MAVLink calculated CRC on plaintext but we're sending ciphertext
static uint8_t stored_header[MAVLINK_COMM_NUM_BUFFERS][10];      // Full MAVLink v2 header
static uint8_t stored_ciphertext[MAVLINK_COMM_NUM_BUFFERS][256]; // Encrypted payload
static uint8_t stored_ciphertext_len[MAVLINK_COMM_NUM_BUFFERS];  // Length of ciphertext
static bool was_encrypted[MAVLINK_COMM_NUM_BUFFERS] = {false};   // Flag: payload was encrypted
#endif

mavlink_system_t mavlink_system = {7,1};

// routing table
MAVLink_routing GCS_MAVLINK::routing;

GCS_MAVLINK *GCS_MAVLINK::find_by_mavtype_and_compid(uint8_t mav_type, uint8_t compid, uint8_t &sysid) {
    mavlink_channel_t channel;
    if (!routing.find_by_mavtype_and_compid(mav_type, compid, sysid, channel)) {
        return nullptr;
    }
    return gcs().chan(channel);
}

// set a channel as private. Private channels get sent heartbeats, but
// don't get broadcast packets or forwarded packets
void GCS_MAVLINK::set_channel_private(mavlink_channel_t _chan)
{
    const uint8_t mask = (1U<<(unsigned)_chan);
    mavlink_private |= mask;
}

// return a MAVLink parameter type given a AP_Param type
MAV_PARAM_TYPE GCS_MAVLINK::mav_param_type(enum ap_var_type t)
{
    if (t == AP_PARAM_INT8) {
	    return MAV_PARAM_TYPE_INT8;
    }
    if (t == AP_PARAM_INT16) {
	    return MAV_PARAM_TYPE_INT16;
    }
    if (t == AP_PARAM_INT32) {
	    return MAV_PARAM_TYPE_INT32;
    }
    // treat any others as float
    return MAV_PARAM_TYPE_REAL32;
}


/// Check for available transmit space on the nominated MAVLink channel
///
/// @param chan		Channel to check
/// @returns		Number of bytes available
uint16_t comm_get_txspace(mavlink_channel_t chan)
{
    GCS_MAVLINK *link = gcs().chan(chan);
    if (link == nullptr) {
        return 0;
    }
    return link->txspace();
}

/*
  send a buffer out a MAVLink channel
  *** POINT D'ENCRYPTION PRINCIPAL - Intercepte 100% du trafic MAVLink ***
 */
void comm_send_buffer(mavlink_channel_t chan, const uint8_t *buf, uint8_t len)
{
    if (!valid_channel(chan) || mavlink_comm_port[chan] == nullptr || chan_discard[chan]) {
        return;
    }
#if HAL_HIGH_LATENCY2_ENABLED
    // if it's a disabled high latency channel, don't send
    GCS_MAVLINK *link = gcs().chan(chan);
    if (link->is_high_latency_link && !gcs().get_high_latency_status()) {
        return;
    }
#endif
    if (gcs_alternative_active[chan]) {
        // an alternative protocol is active
        return;
    }

#if AP_HSM_ENABLED
    // Feature 3 + Session 21 CRC Fix: DualDekEngine - Encryption PAYLOAD with CRC recalculation
    // MAVLink message structure: Header → PAYLOAD → Checksum → Signature
    // comm_send_buffer() est appelé 3-4 fois: [0]=Header, [1]=PAYLOAD, [2]=Checksum, [3]=Signature
    //
    // Problem: MAVLink calculates CRC on PLAINTEXT, but we encrypt the payload.
    // Solution: Recalculate CRC on CIPHERTEXT in buffer[2].

    const uint8_t current_buffer = send_buffer_index[chan];

    // ═══════════════════════════════════════════════════════════════════════
    // Buffer[0] = Header: Store complete header for CRC recalculation
    // ═══════════════════════════════════════════════════════════════════════
    if (current_buffer == 0 && len >= 10) {
        // MAVLink v2 header: STX(1) + len(1) + incompat(1) + compat(1) + seq(1) + sysid(1) + compid(1) + msgid(3)
        if (buf[0] == 0xFD) {  // MAVLink v2 STX
            // Store header fields for nonce generation
            tx_header_info[chan].seq = buf[4];
            tx_header_info[chan].sysid = buf[5];
            tx_header_info[chan].compid = buf[6];
            tx_header_info[chan].msgid = buf[7] | (buf[8] << 8) | (buf[9] << 16);
            tx_header_info[chan].valid = true;

            // Session 21: Store complete header for CRC recalculation
            memcpy(stored_header[chan], buf, 10);
            was_encrypted[chan] = false;  // Reset flag for this message
        }
    }

    // Messages qui doivent rester en clair (peer discovery + key exchange)
    // HEARTBEAT=0, HSM_WK_EXCHANGE=12000, HSM_DEK_EXCHANGE=12001, HSM_KEY_ACK=12002
    const uint32_t msgid = tx_header_info[chan].msgid;
    const bool is_plaintext_msg = (msgid == 0 || msgid == 12000 || msgid == 12001 || msgid == 12002);
    const bool is_payload = (current_buffer == 1);
    const bool is_checksum = (current_buffer == 2);

    // ═══════════════════════════════════════════════════════════════════════
    // Buffer[1] = Payload: Encrypt and store ciphertext for CRC recalculation
    // ═══════════════════════════════════════════════════════════════════════
    if (gcs().get_mav_encrypt() != 0 && is_payload && tx_header_info[chan].valid && !is_plaintext_msg) {
        KeyOrchestrator& ko = KeyOrchestrator::get_singleton();
        const uint8_t* dek = ko.get_my_dek();

        if (dek != nullptr && len > 0) {
            // Buffer pour payload chiffré
            uint8_t encrypted[256];

            // Nonce déterministe basé sur les champs du header
            uint8_t nonce[12];
            nonce[0] = tx_header_info[chan].seq;
            nonce[1] = tx_header_info[chan].sysid;
            nonce[2] = tx_header_info[chan].compid;
            nonce[3] = (tx_header_info[chan].msgid >> 0) & 0xFF;
            nonce[4] = (tx_header_info[chan].msgid >> 8) & 0xFF;
            nonce[5] = (tx_header_info[chan].msgid >> 16) & 0xFF;
            nonce[6] = chan;
            nonce[7] = 0x00;
            nonce[8] = 0x00;
            nonce[9] = 0x00;
            nonce[10] = 0x00;
            nonce[11] = 0x00;

            // Chiffrer le payload avec ChaCha20-256
            ChaCha20XOR((uint8_t*)dek, 0, nonce, (uint8_t*)buf, encrypted, len);

            // Session 21: Store ciphertext for CRC recalculation in buffer[2]
            memcpy(stored_ciphertext[chan], encrypted, len);
            stored_ciphertext_len[chan] = len;
            was_encrypted[chan] = true;

            // Envoyer payload chiffré
            const size_t written = mavlink_comm_port[chan]->write(encrypted, len);
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
            if (written < len && !mavlink_comm_port[chan]->is_write_locked()) {
                AP_HAL::panic("Short write on UART: %lu < %u", (unsigned long)written, len);
            }
#else
            (void)written;
#endif
            send_buffer_index[chan]++;
            return;
        }
        // else: DEK not available, continue with plaintext
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Buffer[2] = Checksum: Recalculate CRC on ciphertext if payload was encrypted
    // ═══════════════════════════════════════════════════════════════════════
    if (is_checksum && was_encrypted[chan] && len == 2) {
        // Recalculate CRC on: header (bytes 1-9, without STX) + ciphertext + crc_extra
        uint16_t crc;
        crc_init(&crc);

        // CRC over header bytes 1-9 (skip STX at byte 0)
        for (int i = 1; i < 10; i++) {
            crc_accumulate(stored_header[chan][i], &crc);
        }

        // CRC over ciphertext (not plaintext!)
        crc_accumulate_buffer(&crc, (const char*)stored_ciphertext[chan], stored_ciphertext_len[chan]);

        // CRC extra depends on msgid - lookup in MAVLink message table
        const mavlink_msg_entry_t* entry = mavlink_get_msg_entry(tx_header_info[chan].msgid);
        if (entry != nullptr) {
            crc_accumulate(entry->crc_extra, &crc);
        }

        // Build new CRC bytes
        uint8_t new_ck[2];
        new_ck[0] = (uint8_t)(crc & 0xFF);
        new_ck[1] = (uint8_t)(crc >> 8);

        // Send recalculated CRC instead of original
        const size_t written = mavlink_comm_port[chan]->write(new_ck, 2);
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
        if (written < 2 && !mavlink_comm_port[chan]->is_write_locked()) {
            AP_HAL::panic("Short write on UART: %lu < 2", (unsigned long)written);
        }
#else
        (void)written;
#endif
        // Reset encryption flag and increment buffer index
        was_encrypted[chan] = false;
        send_buffer_index[chan]++;
        return;
    }

    // Incrémenter index pour prochain buffer (header/plaintext checksum/signature)
    send_buffer_index[chan]++;
#endif // AP_HSM_ENABLED

    // Envoi normal (pas d'encryption ou encryption désactivée)
    const size_t written = mavlink_comm_port[chan]->write(buf, len);
#if CONFIG_HAL_BOARD == HAL_BOARD_SITL
    if (written < len && !mavlink_comm_port[chan]->is_write_locked()) {
        AP_HAL::panic("Short write on UART: %lu < %u", (unsigned long)written, len);
    }
#else
    (void)written;
#endif
}

/*
  lock a channel for send
  if there is insufficient space to send size bytes then all bytes
  written to the channel by the mavlink library will be discarded
  while the lock is held.
 */
void comm_send_lock(mavlink_channel_t chan_m, uint16_t size)
{
    const uint8_t chan = uint8_t(chan_m);
#if AP_HSM_ENABLED
    // Feature 4: Reset buffer index at start of each message
    send_buffer_index[chan] = 0;
#endif
    chan_locks[chan].take_blocking();
    if (mavlink_comm_port[chan]->txspace() < size) {
        chan_discard[chan] = true;
        gcs_out_of_space_to_send(chan_m);
    }
}

/*
  unlock a channel
 */
void comm_send_unlock(mavlink_channel_t chan_m)
{
    const uint8_t chan = uint8_t(chan_m);
    chan_discard[chan] = false;
    chan_locks[chan].give();
}

/*
  return reference to GCS channel lock, allowing for
  HAVE_PAYLOAD_SPACE() to be run with a locked channel
 */
HAL_Semaphore &comm_chan_lock(mavlink_channel_t chan)
{
    return chan_locks[uint8_t(chan)];
}

#endif  // HAL_GCS_ENABLED
