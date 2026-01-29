# Plan de Tests HSM ArduPilot - Version Complète

## Vue d'Ensemble du Code HSM Implémenté

### Architecture des Composants

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ARDUPILOT HSM IMPLEMENTATION                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    libraries/AP_HSM/ (C++)                          │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐   │   │
│  │  │   AP_HSM     │  │  KeyOrchestrator │  │ KeyExchangeProtocol│   │   │
│  │  │  (Driver)    │  │  (Key Hierarchy) │  │ (MAVLink KEP)      │   │   │
│  │  └──────┬───────┘  └────────┬─────────┘  └──────────┬─────────┘   │   │
│  │         │                   │                       │             │   │
│  │         │                   │                       │             │   │
│  │  ┌──────▼───────────────────▼───────────────────────▼─────────┐   │   │
│  │  │                    DualDekEngine                           │   │   │
│  │  │              (TX/RX Payload Encryption)                    │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                     │   │
│  │  Crypto libs: micro-ecc (P-256), Monocypher (XChaCha20-Poly1305)   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   libraries/GCS_MAVLink/ (Modifié)                  │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  GCS_MAVLink.cpp: TX encryption (comm_send_buffer)                  │   │
│  │  GCS_Common.cpp:  RX decryption (update_receive)                    │   │
│  │                   HSM message handlers (12000, 12001, 12002)        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Tools/hsm/ (Python GCS)                        │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  gcs_hsm.py        - HSM hardware driver                            │   │
│  │  ecies.py          - ECIES encryption (P-256 + XChaCha20)           │   │
│  │  dual_dek_engine.py - Payload encryption/decryption                 │   │
│  │  gcs_kep_client.py - Key exchange client                            │   │
│  │  mavproxy_hsm.py   - MAVProxy module                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. INVENTAIRE DES CLASSES ET MÉTHODES À TESTER

### 1.1 AP_HSM (Driver HSM)

**Fichiers:** `libraries/AP_HSM/AP_HSM.h`, `AP_HSM.cpp`

| Méthode | Description | Type Test |
|---------|-------------|-----------|
| `begin(uart)` | Initialise UART | Unit |
| `init_monolith()` | Init HSM (OFF→ON→SELECT→PIN) | Unit + Integration |
| `start_init_async()` | Init async start | Unit |
| `update_init()` | Init async step | Unit |
| `is_init_complete()` | Check init done | Unit |
| `generate_keypair_p256()` | Génère keypair micro-ecc | Unit |
| `store_private_key_to_hsm()` | Écrit clé privée HSM | Integration |
| `load_private_key_from_hsm()` | Lit clé privée HSM | Integration |
| `generate_dek()` | Génère DEK aléatoire | Unit |
| `compute_ecdh()` | Calcul ECDH | Unit |
| `derive_wrapping_key()` | HKDF dérivation | Unit |
| `wrap_dek()` | Chiffre DEK | Unit |
| `unwrap_dek()` | Déchiffre DEK | Unit |
| `store_dek_to_hsm()` | Stocke DEK wrappée | Integration |
| `load_dek_from_hsm()` | Charge DEK wrappée | Integration |
| `send_apdu()` | Envoi commande APDU | Integration |
| `hexstr_to_bytes()` | Conversion hex | Unit |

**Mock HSM Storage (quand AP_HSM_MOCK_ENABLED=1):**
- `_mock_storage[256]` - Simule EEPROM HSM
- Offsets: MK@0x0100, WK@0x0120, DEK@0x0140, tags@0x0160/0x0180

---

### 1.2 KeyOrchestrator (Hiérarchie de Clés)

**Fichiers:** `libraries/AP_HSM/KeyOrchestrator.h`, `KeyOrchestrator.cpp`

| Méthode | Description | Type Test |
|---------|-------------|-----------|
| `init(hsm)` | Initialise avec AP_HSM | Unit |
| `init_mission_keys()` | Génère MK→WK→DEK complet | Integration |
| `restore_mission_keys()` | Restaure depuis HSM | Integration |
| `is_fully_initialized()` | Check toutes clés OK | Unit |
| **Niveau 1: Master Key** | | |
| `generate_master_key()` | Random 32 bytes | Unit |
| `store_mk_to_hsm()` | Écrit @0x0100 | Integration |
| `load_mk_from_hsm()` | Lit @0x0100 | Integration |
| `has_master_key()` | Check MK loaded | Unit |
| **Niveau 2: Wrapper Key** | | |
| `derive_wrapper_key()` | HKDF MK→WK_priv | Unit |
| `compute_wk_public()` | micro-ecc WK_priv→WK_pub | Unit |
| `store_wk_to_hsm()` | Wrappe+stocke @0x0120 | Integration |
| `load_wk_from_hsm()` | Charge+unwrap @0x0120 | Integration |
| `get_wk_public()` | Retourne WK_pub 64 bytes | Unit |
| `get_wk_private()` | Retourne WK_priv 32 bytes | Unit |
| **Niveau 3: Data Encryption Key** | | |
| `generate_dek()` | Random 32 bytes | Unit |
| `store_dek_to_hsm()` | Wrappe+stocke @0x0140 | Integration |
| `load_dek_from_hsm()` | Charge+unwrap @0x0140 | Integration |
| `get_my_dek()` | Retourne MY_DEK | Unit |
| **Wrapping** | | |
| `wrap_key(key, wrapped, tag)` | XOR MK + HMAC-SHA256 | Unit |
| `unwrap_key(wrapped, tag, key)` | Verify HMAC + XOR | Unit |
| **Peers** | | |
| `store_peer_dek(peer_id, dek)` | Stocke DEK peer | Unit |
| `get_peer_dek(peer_id)` | Récupère DEK peer | Unit |
| `has_peer_dek(peer_id)` | Check peer existe | Unit |
| **ECIES** | | |
| `ecies_encrypt_my_dek()` | Chiffre DEK pour peer | Unit |
| `ecies_decrypt_peer_dek()` | Déchiffre DEK de peer | Unit |
| **Utils** | | |
| `secure_erase_all()` | Efface toutes clés | Unit |
| `derive_p256_scalar_from_hkdf()` | HKDF avec validation P-256 | Unit |
| `is_valid_p256_scalar()` | Vérifie scalar < ordre | Unit |

---

### 1.3 KeyExchangeProtocol (Échange MAVLink)

**Fichiers:** `libraries/AP_HSM/KeyExchangeProtocol.h`, `KeyExchangeProtocol.cpp`

| Méthode | Description | Type Test |
|---------|-------------|-----------|
| `init(key_orch)` | Initialise avec KeyOrchestrator | Unit |
| **Discovery** | | |
| `on_heartbeat_received(sysid, compid)` | Enregistre peer | Unit |
| `is_known_peer(sysid, compid)` | Check peer connu | Unit |
| **Exchange** | | |
| `initiate_exchange(sysid, compid)` | Démarre échange | Integration |
| `initiate_exchange_all_peers()` | Échange avec tous | Integration |
| **Handlers MAVLink** | | |
| `handle_wk_exchange()` | Reçoit WK_pub peer | Integration |
| `handle_dek_exchange()` | Reçoit DEK chiffrée ECIES | Integration |
| `handle_key_ack()` | Reçoit ACK | Integration |
| **ECIES** | | |
| `ecies_encrypt_dek()` | Chiffre DEK pour envoi | Unit |
| `ecies_decrypt_dek()` | Déchiffre DEK reçue | Unit |
| **State** | | |
| `get_peer_state(sysid, compid)` | État échange | Unit |
| `is_exchange_complete(sysid, compid)` | Check terminé | Unit |
| `get_peer_dek(sysid, compid)` | DEK du peer | Unit |
| **Helpers** | | |
| `ecdh_compute_shared()` | ECDH micro-ecc | Unit |
| `hkdf_derive()` | HKDF-SHA256 | Unit |
| `chacha_encrypt()` | XChaCha20-Poly1305 | Unit |
| `chacha_decrypt()` | XChaCha20-Poly1305 | Unit |

**State Machine:**
```
IDLE → WK_SENT → WK_RECEIVED → DEK_SENT → DEK_RECEIVED → COMPLETE
                                                            │
                                                         ERROR
```

---

### 1.4 DualDekEngine (Chiffrement Payload)

**Fichiers:** `libraries/AP_HSM/DualDekEngine.h`, `DualDekEngine.cpp`

| Méthode | Description | Type Test |
|---------|-------------|-----------|
| `init(ko, kep)` | Initialise avec KO+KEP | Unit |
| `is_ready()` | Check encryption possible | Unit |
| `should_encrypt(msgid)` | Vérifie si msg à chiffrer | Unit |
| `encrypt_payload()` | Chiffre TX payload | Unit |
| `decrypt_payload()` | Déchiffre RX payload | Unit |
| `generate_nonce()` | Génère nonce 24 bytes | Unit |

**Messages Plaintext (jamais chiffrés):**
- HEARTBEAT (0)
- HSM_WK_EXCHANGE (12000)
- HSM_DEK_EXCHANGE (12001)
- HSM_KEY_ACK (12002)

---

### 1.5 GCS_MAVLink Modifications

**Fichiers:** `libraries/GCS_MAVLink/GCS_MAVLink.cpp`, `GCS_Common.cpp`

| Modification | Description | Type Test |
|--------------|-------------|-----------|
| `comm_send_buffer()` | TX: chiffre payload avant envoi | Integration |
| `update_receive()` | RX: déchiffre payload après réception | Integration |
| CRC collision handling | Déchiffre même si CRC OK | Integration |
| HSM message handlers | 12000/12001/12002 | Integration |

---

### 1.6 Python GCS Tools

**Fichiers:** `Tools/hsm/*.py`

| Module | Classe/Fonction | Type Test |
|--------|-----------------|-----------|
| **gcs_hsm.py** | `GCS_HSM` | Unit + Integration |
| | `power_on()`, `power_off()` | Unit |
| | `select_applet()`, `verify_pin()` | Unit |
| | `read_binary()`, `write_binary()` | Unit |
| | `init_mission_keys()` | Integration |
| **ecies.py** | `ECIES` | Unit |
| | `generate_keypair()` | Unit |
| | `derive_public_key()` | Unit |
| | `ecdh()` | Unit |
| | `hkdf_derive()` | Unit |
| | `xchacha20_poly1305_encrypt()` | Unit |
| | `xchacha20_poly1305_decrypt()` | Unit |
| | `encrypt_dek()`, `decrypt_dek()` | Unit |
| **dual_dek_engine.py** | `DualDekEngine` | Unit |
| | `encrypt()`, `decrypt()` | Unit |
| | `should_encrypt()` | Unit |
| **gcs_kep_client.py** | `GCSKeyExchangeClient` | Integration |
| | `send_wk_exchange()` | Integration |
| | `send_dek_exchange()` | Integration |
| | `handle_wk_exchange()` | Integration |
| **mavproxy_hsm.py** | `HSMModule` | Integration |
| | `mavlink_packet()` (RX decrypt) | Integration |
| | `master_send_callback()` (TX encrypt) | Integration |

---

## 2. PLAN DE TESTS UNITAIRES (C++ GTest)

### 2.1 Structure des Fichiers

```
libraries/AP_HSM/tests/
├── wscript
├── test_ap_hsm.cpp           # Tests AP_HSM driver
├── test_key_orchestrator.cpp # Tests hiérarchie clés
├── test_key_exchange.cpp     # Tests KEP + ECIES
├── test_dual_dek.cpp         # Tests encryption/decryption
├── test_crypto_primitives.cpp # Tests micro-ecc, Monocypher
└── test_mock_hsm.cpp         # Tests Mock HSM storage
```

### 2.2 test_ap_hsm.cpp

```cpp
// Groupe: AP_HSM_Mock
TEST(AP_HSM_Mock, InitMockStorage)
TEST(AP_HSM_Mock, WriteReadMockEEPROM)
TEST(AP_HSM_Mock, InitMonolithMock)

// Groupe: AP_HSM_Keypair
TEST(AP_HSM_Keypair, GenerateP256Keypair)
TEST(AP_HSM_Keypair, KeypairIsValid)
TEST(AP_HSM_Keypair, StoreLoadPrivateKey)

// Groupe: AP_HSM_DEK
TEST(AP_HSM_DEK, GenerateDEK)
TEST(AP_HSM_DEK, DEKIs32Bytes)
TEST(AP_HSM_DEK, WrapUnwrapDEK)
TEST(AP_HSM_DEK, WrapUnwrapIntegrity)

// Groupe: AP_HSM_ECDH
TEST(AP_HSM_ECDH, ComputeECDH)
TEST(AP_HSM_ECDH, ECDHSymmetric)  // A-B == B-A
TEST(AP_HSM_ECDH, DeriveWrappingKey)

// Groupe: AP_HSM_Utils
TEST(AP_HSM_Utils, HexstrToBytes)
TEST(AP_HSM_Utils, HexstrToBytes_Invalid)
```

### 2.3 test_key_orchestrator.cpp

```cpp
// Groupe: KeyOrch_Init
TEST(KeyOrch_Init, SingletonPattern)
TEST(KeyOrch_Init, InitWithHSM)
TEST(KeyOrch_Init, InitWithoutHSM_Fails)

// Groupe: KeyOrch_MasterKey
TEST(KeyOrch_MasterKey, Generate)
TEST(KeyOrch_MasterKey, StoreToHSM)
TEST(KeyOrch_MasterKey, LoadFromHSM)
TEST(KeyOrch_MasterKey, IsRandom)  // Deux générations différentes

// Groupe: KeyOrch_WrapperKey
TEST(KeyOrch_WrapperKey, DeriveFromMK)
TEST(KeyOrch_WrapperKey, ComputePublic)
TEST(KeyOrch_WrapperKey, PublicIs64Bytes)
TEST(KeyOrch_WrapperKey, StoreLoadRoundtrip)
TEST(KeyOrch_WrapperKey, ValidP256Scalar)

// Groupe: KeyOrch_DEK
TEST(KeyOrch_DEK, Generate)
TEST(KeyOrch_DEK, StoreLoadRoundtrip)
TEST(KeyOrch_DEK, WrapUnwrapIntegrity)

// Groupe: KeyOrch_Wrapping
TEST(KeyOrch_Wrapping, WrapKey)
TEST(KeyOrch_Wrapping, UnwrapKey)
TEST(KeyOrch_Wrapping, WrongTagFails)
TEST(KeyOrch_Wrapping, TamperedDataFails)

// Groupe: KeyOrch_HKDF
TEST(KeyOrch_HKDF, DeriveP256Scalar)
TEST(KeyOrch_HKDF, ScalarIsValid)
TEST(KeyOrch_HKDF, DeterministicDerivation)

// Groupe: KeyOrch_Peers
TEST(KeyOrch_Peers, StorePeerDEK)
TEST(KeyOrch_Peers, GetPeerDEK)
TEST(KeyOrch_Peers, MaxPeersLimit)
TEST(KeyOrch_Peers, RemovePeer)

// Groupe: KeyOrch_ECIES
TEST(KeyOrch_ECIES, EncryptMyDEK)
TEST(KeyOrch_ECIES, DecryptPeerDEK)
TEST(KeyOrch_ECIES, EncryptDecryptRoundtrip)
TEST(KeyOrch_ECIES, WrongKeyFails)

// Groupe: KeyOrch_Mission
TEST(KeyOrch_Mission, InitMissionKeys)
TEST(KeyOrch_Mission, RestoreMissionKeys)
TEST(KeyOrch_Mission, IsFullyInitialized)

// Groupe: KeyOrch_Security
TEST(KeyOrch_Security, SecureEraseAll)
TEST(KeyOrch_Security, KeysZeroedAfterErase)
```

### 2.4 test_key_exchange.cpp

```cpp
// Groupe: KEP_Init
TEST(KEP_Init, SingletonPattern)
TEST(KEP_Init, InitWithKeyOrchestrator)
TEST(KEP_Init, WKPublicReady)

// Groupe: KEP_Peers
TEST(KEP_Peers, OnHeartbeatReceived)
TEST(KEP_Peers, IsKnownPeer)
TEST(KEP_Peers, MaxPeersLimit)
TEST(KEP_Peers, FindPeer)
TEST(KEP_Peers, FindPeerWildcardCompid)

// Groupe: KEP_ECIES
TEST(KEP_ECIES, EncryptDEK)
TEST(KEP_ECIES, DecryptDEK)
TEST(KEP_ECIES, EncryptDecryptRoundtrip)
TEST(KEP_ECIES, WrongEphemeralKeyFails)
TEST(KEP_ECIES, TamperedCiphertextFails)
TEST(KEP_ECIES, TamperedTagFails)

// Groupe: KEP_ECDH
TEST(KEP_ECDH, ComputeShared)
TEST(KEP_ECDH, SharedIsSymmetric)

// Groupe: KEP_HKDF
TEST(KEP_HKDF, DeriveKey)
TEST(KEP_HKDF, DifferentInfoDifferentKey)

// Groupe: KEP_ChaCha
TEST(KEP_ChaCha, Encrypt)
TEST(KEP_ChaCha, Decrypt)
TEST(KEP_ChaCha, EncryptDecryptRoundtrip)
TEST(KEP_ChaCha, WrongKeyFails)
TEST(KEP_ChaCha, WrongNonceFails)

// Groupe: KEP_State
TEST(KEP_State, InitialStateIdle)
TEST(KEP_State, StateAfterWKSent)
TEST(KEP_State, StateAfterDEKReceived)
TEST(KEP_State, IsExchangeComplete)

// Groupe: KEP_Timeout
TEST(KEP_Timeout, CheckTimeouts)
TEST(KEP_Timeout, PeerResetAfterTimeout)
```

### 2.5 test_dual_dek.cpp

```cpp
// Groupe: DDE_Init
TEST(DDE_Init, SingletonPattern)
TEST(DDE_Init, InitWithComponents)
TEST(DDE_Init, IsReady)

// Groupe: DDE_ShouldEncrypt
TEST(DDE_ShouldEncrypt, Heartbeat_No)
TEST(DDE_ShouldEncrypt, HSM_WK_EXCHANGE_No)
TEST(DDE_ShouldEncrypt, HSM_DEK_EXCHANGE_No)
TEST(DDE_ShouldEncrypt, HSM_KEY_ACK_No)
TEST(DDE_ShouldEncrypt, ATTITUDE_Yes)
TEST(DDE_ShouldEncrypt, COMMAND_LONG_Yes)
TEST(DDE_ShouldEncrypt, SET_MODE_Yes)

// Groupe: DDE_Encrypt
TEST(DDE_Encrypt, EncryptPayload)
TEST(DDE_Encrypt, EncryptedSizeLarger)
TEST(DDE_Encrypt, NonceIncluded)
TEST(DDE_Encrypt, TagIncluded)
TEST(DDE_Encrypt, DifferentNonceEachTime)

// Groupe: DDE_Decrypt
TEST(DDE_Decrypt, DecryptPayload)
TEST(DDE_Decrypt, EncryptDecryptRoundtrip)
TEST(DDE_Decrypt, WrongPeerDEKFails)
TEST(DDE_Decrypt, TamperedDataFails)
TEST(DDE_Decrypt, NoPeerDEKFails)

// Groupe: DDE_Nonce
TEST(DDE_Nonce, GenerateNonce)
TEST(DDE_Nonce, NonceIs24Bytes)
TEST(DDE_Nonce, NonceIsRandom)

// Groupe: DDE_Stats
TEST(DDE_Stats, TxEncryptedCount)
TEST(DDE_Stats, RxDecryptedCount)
TEST(DDE_Stats, RxFailedCount)
```

### 2.6 test_crypto_primitives.cpp

```cpp
// Groupe: uECC
TEST(uECC, MakeKey)
TEST(uECC, SharedSecret)
TEST(uECC, SharedSecretSymmetric)
TEST(uECC, ComputePublicKey)
TEST(uECC, ValidPrivateKey)

// Groupe: Monocypher
TEST(Monocypher, ChaCha20XOR)
TEST(Monocypher, CryptoLock)
TEST(Monocypher, CryptoUnlock)
TEST(Monocypher, CryptoLockUnlockRoundtrip)
TEST(Monocypher, WrongKeyUnlockFails)

// Groupe: HMAC
TEST(HMAC, SHA256)
TEST(HMAC, VerifyCorrect)
TEST(HMAC, VerifyTampered)
```

---

## 3. PLAN DE TESTS D'INTÉGRATION (Python)

### 3.1 Structure des Tests

```
Tools/autotest/
├── hsm_tests.py              # Tests d'intégration SITL
└── ArduCopter_Tests/
    └── HSM_KeyExchange/      # Mission test HSM

Tools/hsm/
├── test_hsm_integration.py   # Tests intégration complets
├── test_hsm_sitl.py          # Tests SITL spécifiques
└── test_hsm_e2e.py           # Tests end-to-end
```

### 3.2 Tests SITL Integration (hsm_tests.py pour autotest)

```python
class AutoTestHSM(AutoTestCopter):
    """HSM Integration Tests for ArduCopter"""

    def HSM_MockInit(self):
        '''Test HSM Mock initialization'''
        # Vérifie que Mock HSM s'initialise correctement
        # Vérifie les debug prints: HSM_DEBUG: init_monolith() SUCCESS

    def HSM_KeyOrchestratorInit(self):
        '''Test KeyOrchestrator initialization'''
        # Vérifie génération MK+WK+DEK
        # Vérifie prints: KEP singleton, KEP init SUCCESS

    def HSM_HeartbeatDiscovery(self):
        '''Test peer discovery via heartbeat'''
        # Connecte GCS, vérifie peer découvert
        # Vérifie: on_heartbeat_received appelé

    def HSM_WKExchange(self):
        '''Test Wrapper Key exchange'''
        # Envoie HSM_WK_EXCHANGE depuis GCS
        # Vérifie drone reçoit et stocke WK_pub
        # Vérifie ACK reçu

    def HSM_DEKExchange(self):
        '''Test DEK exchange via ECIES'''
        # Après WK exchange, vérifie DEK exchange
        # Vérifie ECIES encrypt/decrypt
        # Vérifie state=COMPLETE

    def HSM_FullKeyExchange(self):
        '''Test complete key exchange sequence'''
        # Séquence complète: WK → DEK → ACK → COMPLETE
        # Vérifie les deux côtés ont les DEKs

    def HSM_EncryptedTelemetry(self):
        '''Test telemetry encryption Drone→GCS'''
        # Après key exchange
        # Vérifie messages chiffrés (BAD_CRC)
        # Vérifie déchiffrement GCS

    def HSM_EncryptedCommands(self):
        '''Test command encryption GCS→Drone'''
        # Envoie SET_MODE chiffré
        # Vérifie drone déchiffre et exécute

    def HSM_CRCCollision(self):
        '''Test CRC collision handling'''
        # Vérifie que messages avec CRC OK par collision
        # sont quand même déchiffrés

    def HSM_PlaintextMessages(self):
        '''Test plaintext messages not decrypted'''
        # HEARTBEAT, HSM_* ne doivent pas être déchiffrés

    def HSM_PeerTimeout(self):
        '''Test peer timeout and reset'''
        # Simule timeout 30s
        # Vérifie peer reset
        # Vérifie re-exchange possible

    def HSM_MultiPeer(self):
        '''Test multiple peers'''
        # Connecte 2+ GCS
        # Vérifie key exchange avec chaque
        # Vérifie routing DEK correct

    def tests(self):
        return [
            self.HSM_MockInit,
            self.HSM_KeyOrchestratorInit,
            self.HSM_HeartbeatDiscovery,
            self.HSM_WKExchange,
            self.HSM_DEKExchange,
            self.HSM_FullKeyExchange,
            self.HSM_EncryptedTelemetry,
            self.HSM_EncryptedCommands,
            self.HSM_CRCCollision,
            self.HSM_PlaintextMessages,
            self.HSM_PeerTimeout,
            self.HSM_MultiPeer,
        ]
```

### 3.3 Tests Python Standalone (test_hsm_integration.py)

```python
class TestHSMIntegration(unittest.TestCase):
    """Integration tests for HSM Python components"""

    # === GCS_HSM Tests ===
    def test_hsm_power_on(self):
        """Test HSM power on sequence"""

    def test_hsm_select_applet(self):
        """Test applet selection"""

    def test_hsm_verify_pin(self):
        """Test PIN verification"""

    def test_hsm_read_write_binary(self):
        """Test EEPROM read/write"""

    def test_hsm_init_mission_keys(self):
        """Test full mission key initialization"""

    # === ECIES Tests ===
    def test_ecies_keypair_generation(self):
        """Test P-256 keypair generation"""

    def test_ecies_ecdh(self):
        """Test ECDH shared secret"""

    def test_ecies_hkdf(self):
        """Test HKDF derivation"""

    def test_ecies_encrypt_dek(self):
        """Test DEK encryption"""

    def test_ecies_decrypt_dek(self):
        """Test DEK decryption"""

    def test_ecies_roundtrip(self):
        """Test full ECIES encrypt/decrypt"""

    # === DualDekEngine Tests ===
    def test_dde_encrypt(self):
        """Test payload encryption"""

    def test_dde_decrypt(self):
        """Test payload decryption"""

    def test_dde_roundtrip(self):
        """Test encrypt/decrypt roundtrip"""

    def test_dde_wrong_key_fails(self):
        """Test decryption with wrong key fails"""

    # === Cross-Platform Compatibility ===
    def test_python_cpp_ecies_compat(self):
        """Test Python ECIES compatible with C++"""
        # Encrypt in Python, decrypt data that C++ would produce

    def test_python_cpp_chacha_compat(self):
        """Test Python ChaCha20 compatible with C++ Monocypher"""
```

### 3.4 Tests End-to-End (test_hsm_e2e.py)

```python
class TestHSMEndToEnd(unittest.TestCase):
    """End-to-end tests with SITL"""

    def setUp(self):
        """Start SITL with Mock HSM"""
        self.sitl = start_sitl_with_hsm()

    def tearDown(self):
        """Stop SITL"""
        self.sitl.stop()

    def test_e2e_key_exchange(self):
        """Test complete key exchange SITL + Python GCS"""
        client = GCSKeyExchangeClient(mavlink="tcp:127.0.0.1:5760")
        client.run()
        self.assertTrue(client.is_exchange_complete())

    def test_e2e_encrypted_arm(self):
        """Test encrypted ARM command"""
        # Key exchange
        # Send encrypted ARM
        # Verify drone arms

    def test_e2e_encrypted_takeoff(self):
        """Test encrypted TAKEOFF command"""

    def test_e2e_encrypted_mode_change(self):
        """Test encrypted SET_MODE command"""

    def test_e2e_encrypted_mission(self):
        """Test full encrypted mission"""
        # Séquence: ARM → TAKEOFF → WAYPOINT → LAND
        # Toutes commandes chiffrées

    def test_e2e_mavproxy_module(self):
        """Test MAVProxy HSM module"""
        # Charge module
        # Init HSM
        # Vérifie auto-encryption
```

---

## 4. MATRICE DE COUVERTURE

| Composant | Unit Tests | Integration Tests | E2E Tests |
|-----------|------------|-------------------|-----------|
| AP_HSM Mock | ✓ | | |
| AP_HSM UART | | ✓ (hardware) | |
| KeyOrchestrator MK | ✓ | ✓ | |
| KeyOrchestrator WK | ✓ | ✓ | |
| KeyOrchestrator DEK | ✓ | ✓ | |
| KeyOrchestrator ECIES | ✓ | ✓ | |
| KEP Discovery | ✓ | ✓ | ✓ |
| KEP WK Exchange | ✓ | ✓ | ✓ |
| KEP DEK Exchange | ✓ | ✓ | ✓ |
| KEP State Machine | ✓ | ✓ | |
| DualDekEngine Encrypt | ✓ | ✓ | ✓ |
| DualDekEngine Decrypt | ✓ | ✓ | ✓ |
| GCS_MAVLink TX | | ✓ | ✓ |
| GCS_MAVLink RX | | ✓ | ✓ |
| CRC Collision | | ✓ | ✓ |
| Python ECIES | ✓ | ✓ | |
| Python DualDekEngine | ✓ | ✓ | |
| Python GCS_HSM | ✓ | ✓ (hardware) | |
| MAVProxy Module | | ✓ | ✓ |
| Cross-platform compat | | ✓ | ✓ |

---

## 5. COMMANDES D'EXÉCUTION

### 5.1 Tests Unitaires C++

```bash
# Compiler avec tests
./waf configure --board sitl
./waf build

# Exécuter tous les tests
./waf check

# Exécuter un test spécifique
./build/sitl/tests/test_key_orchestrator

# Avec verbose
./build/sitl/tests/test_key_orchestrator --gtest_filter=KeyOrch_ECIES.*
```

### 5.2 Tests d'Intégration Python

```bash
# Tests standalone
cd Tools/hsm
python3 -m pytest test_hsm_integration.py -v

# Tests autotest (SITL)
python3 Tools/autotest/autotest.py --vehicle=ArduCopter --test=HSM_FullKeyExchange

# Tests E2E
python3 Tools/hsm/test_hsm_e2e.py
```

### 5.3 Tests Hardware HSM

```bash
# Phase A (HSM physique)
python3 Tools/hsm/test_hsm_phase_a1.py  # Communication
python3 Tools/hsm/test_hsm_phase_a2.py  # EEPROM
python3 Tools/hsm/test_hsm_phase_a3.py  # Crypto asym
python3 Tools/hsm/test_hsm_phase_a4.py  # Crypto sym
python3 Tools/hsm/test_hsm_phase_a5.py  # Hiérarchie
python3 Tools/hsm/test_hsm_phase_a6.py  # Stress
```

---

## 6. PRIORITÉ D'IMPLÉMENTATION

### Phase 1: Tests Unitaires Critiques
1. `test_crypto_primitives.cpp` - Valider micro-ecc et Monocypher
2. `test_key_orchestrator.cpp` - Valider hiérarchie clés
3. `test_key_exchange.cpp` - Valider ECIES et KEP

### Phase 2: Tests Unitaires Complets
4. `test_ap_hsm.cpp` - Driver HSM
5. `test_dual_dek.cpp` - Encryption payload

### Phase 3: Tests d'Intégration
6. `hsm_tests.py` (autotest) - Tests SITL
7. `test_hsm_integration.py` - Tests Python

### Phase 4: Tests E2E
8. `test_hsm_e2e.py` - Tests complets

---

## 7. CRITÈRES DE SUCCÈS

| Critère | Seuil | Comment atteindre |
|---------|-------|-------------------|
| Couverture Unit Tests | **100%** | Mock UART, injection fautes, tests platform-specific |
| Couverture Integration | **100%** | Mock HSM complet, contrôle timing, multi-process |
| Tests passants | **100%** | CI/CD obligatoire |
| Temps exécution unit tests | < 30s | Tests parallèles |
| Temps exécution integration | < 5min | SITL speedup=100 |
| Compatibilité C++/Python | **100%** | Tests cross-validation |

### Stratégies pour 100% de couverture

#### Unit Tests - Mocking complet
```cpp
// Mock UARTDriver pour tester tous les chemins
class MockUARTDriver : public AP_HAL::UARTDriver {
    bool _fail_next_write = false;
    std::vector<uint8_t> _rx_buffer;
public:
    void inject_rx_data(const uint8_t* data, size_t len);
    void set_fail_next_write(bool fail);
    // ... override all virtual methods
};

// Mock HAL::millis() pour tester timeouts
class MockScheduler {
    uint32_t _mock_time = 0;
public:
    void advance_time(uint32_t ms);
    uint32_t millis() { return _mock_time; }
};
```

#### Integration Tests - Injection de fautes
```python
class FaultInjector:
    """Injecte des fautes pour tester tous les chemins d'erreur"""

    def corrupt_message(self, msg):
        """Corrompt un message pour tester détection erreur"""

    def drop_message(self, probability=0.1):
        """Simule perte de message"""

    def delay_message(self, ms):
        """Simule latence réseau"""

    def inject_hsm_error(self, error_code):
        """Simule erreur HSM (PIN wrong, timeout, etc.)"""
```

#### Chemins d'erreur à couvrir
| Erreur | Test |
|--------|------|
| HSM timeout | `test_hsm_timeout_recovery` |
| PIN incorrect | `test_wrong_pin_handling` |
| APDU malformé | `test_malformed_apdu_response` |
| ECIES decrypt fail | `test_ecies_tampered_data` |
| CRC collision | `test_crc_collision_handling` |
| Peer timeout | `test_peer_timeout_reset` |
| Buffer overflow | `test_payload_too_large` |
| Out of memory | `test_max_peers_exceeded` |
