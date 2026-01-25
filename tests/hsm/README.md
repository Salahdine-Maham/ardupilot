# Tests HSM LeMonolith

Scripts et outils de test pour le projet de sécurité MAVLink avec HSM.

---

## Structure

```
tests/hsm/
├── scripts/           # Scripts de test principaux (.sh)
│   ├── test_feature*.sh
│   ├── test_all_features*.sh
│   └── utils/         # Scripts utilitaires
│       ├── quick_hsm_test.sh
│       ├── hsm_timing_scan.sh
│       └── ...
├── cpp/               # Tests C++ standalone
│   ├── test_feature1_direct.cpp
│   └── test_crypto.cpp
├── python/            # Tests Python
│   ├── test_hsm.py
│   └── simulate_hsm_write_issue.py
└── logs/              # Logs de test (organisés par date)
```

---

## Scripts Principaux

### Tests par Feature

| Script | Description | Usage |
|--------|-------------|-------|
| `test_feature2_quick.sh` | Test rapide Feature 2 | `./scripts/test_feature2_quick.sh` |
| `test_feature3.sh` | Test Feature 3 (DEK) | `./scripts/test_feature3.sh` |
| `test_feature4_final.sh` | Test Feature 4 (encryption) | `./scripts/test_feature4_final.sh` |
| `test_feature123_final.sh` | Test Features 1-3 | `./scripts/test_feature123_final.sh` |

### Tests Complets

| Script | Description | Usage |
|--------|-------------|-------|
| `test_all_features_complete.sh` | Tous les tests | `./scripts/test_all_features_complete.sh` |
| `test_all_features_sitl.sh` | Tests avec SITL | `./scripts/test_all_features_sitl.sh` |

---

## Scripts Utilitaires

| Script | Description |
|--------|-------------|
| `utils/quick_hsm_test.sh` | Test rapide communication HSM |
| `utils/test_hsm_direct.sh` | Test direct UART sans ArduPilot |
| `utils/test_hsm_timing_scan.sh` | Scan des délais timing |
| `utils/test_hsm_usb_real.sh` | Test avec HSM USB réel |
| `utils/reset_dek_hsm.sh` | Reset DEK dans HSM |
| `utils/connect_mavproxy.sh` | Connexion MAVProxy |

---

## Prérequis

### Matériel
- LeMonolith HSM v0.6 sur `/dev/ttyUSB0`

### Logiciel
```bash
# Permissions UART
sudo usermod -a -G dialout $USER
# Puis logout/login

# Build ArduPilot
./waf configure --board sitl
./waf copter
```

---

## Exécution

### Test Rapide HSM
```bash
cd tests/hsm
./scripts/utils/quick_hsm_test.sh
```

### Test Complet SITL
```bash
cd tests/hsm
./scripts/test_all_features_sitl.sh
```

### Test C++ Direct
```bash
cd tests/hsm/cpp
g++ -o test_feature1 test_feature1_direct.cpp
./test_feature1
```

---

## Logs

Les logs sont sauvegardés dans `logs/` avec format:
```
test_<feature>_<YYYYMMDD_HHMMSS>.log
```

Pour nettoyer les anciens logs:
```bash
find logs/ -name "*.log" -mtime +7 -delete
```

---

## Documentation

- Documentation projet: [/docs/hsm-project/](../../docs/hsm-project/)
- Skills HSM: [/build_skill/hsm_skills.md](../../build_skill/hsm_skills.md)
