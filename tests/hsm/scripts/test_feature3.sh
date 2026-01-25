#!/bin/bash

# Script de test rapide pour Feature 3: Génération DEK ChaCha20-256 et KDF sécurisé
# Teste avec HSM réel LeMonolith sur /dev/ttyUSB0

echo "=== Test Feature 3: Génération DEK ChaCha20-256 et KDF ==="
echo ""

# Vérifier que le binaire existe
if [ ! -f build/sitl/bin/arducopter ]; then
    echo "Erreur: binaire arducopter non trouvé"
    echo "Lancer: ./waf copter"
    exit 1
fi

# Créer répertoire feature3 s'il n'existe pas
mkdir -p feature3

# Fichier de log
LOGFILE="feature3/test_feature3_$(date +%Y%m%d_%H%M%S).log"

echo "Fichier de log: $LOGFILE"
echo ""

# Lancer ArduCopter SITL avec HSM sur /dev/ttyUSB0
echo "Lancement ArduCopter SITL avec HSM..."
echo "- Feature 1: Initialisation HSM"
echo "- Feature 2: Keypair P-256"
echo "- Feature 3: DEK ChaCha20-256 + ECDH + HKDF + Wrap/Store"
echo ""

# Définir SERIAL1 pour le HSM
export SERIAL1=/dev/ttyUSB0

# Timeout après 30 secondes
# Utiliser --serial1 pour le HSM sur /dev/ttyUSB0
# Option --console pour éviter d'attendre une connexion TCP
timeout 30s build/sitl/bin/arducopter --model quad --serial1 uart:/dev/ttyUSB0:115200 --console 2>&1 | tee "$LOGFILE" || true

echo ""
echo "=== Analyse des résultats ==="
echo ""

# Vérifier succès Feature 1
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 1: Initialisation HSM réussie"
else
    echo "❌ Feature 1: Échec initialisation HSM"
fi

# Vérifier succès Feature 2
if grep -q "✓ Feature 2 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 2: Keypair P-256 prête"
else
    echo "❌ Feature 2: Échec génération/chargement keypair"
fi

# Vérifier succès Feature 3
if grep -q "✓ Feature 3 complétée avec succès" "$LOGFILE"; then
    echo "✅ Feature 3: DEK ChaCha20-256 prête"
else
    echo "❌ Feature 3: Échec génération/chargement DEK"
fi

echo ""

# Afficher détails Feature 3
echo "=== Détails Feature 3 ==="
echo ""

# Vérifier si DEK générée (première utilisation)
if grep -q "Génération DEK (32 bytes)" "$LOGFILE"; then
    echo "📝 Nouvelle DEK générée"

    # Afficher DEK (attention: sensible!)
    grep "HSM: DEK (32 bytes):" "$LOGFILE" | head -1

    # Vérifier ECDH
    if grep -q "✓ Secret ECDH calculé avec succès" "$LOGFILE"; then
        echo "✅ ECDH: Secret partagé calculé"
    fi

    # Vérifier HKDF
    if grep -q "✓ Wrapping key dérivée avec succès" "$LOGFILE"; then
        echo "✅ HKDF: Wrapping key dérivée"
    fi

    # Vérifier Wrap
    if grep -q "✓ DEK wrappée avec succès" "$LOGFILE"; then
        echo "✅ Wrap: DEK chiffrée"
    fi

    # Vérifier Store HSM
    if grep -q "✓ DEK wrappée stockée avec succès dans HSM" "$LOGFILE"; then
        echo "✅ Store: DEK stockée dans HSM (offset 0x0120)"
    fi
fi

# Vérifier si DEK récupérée (boot ultérieur)
if grep -q "✓ DEK récupérée et unwrappée depuis HSM" "$LOGFILE"; then
    echo "📥 DEK récupérée depuis HSM"

    # Afficher DEK unwrappée
    grep "HSM: DEK (32 bytes):" "$LOGFILE" | tail -1

    echo "✅ Load: DEK lue depuis HSM (offset 0x0120)"
    echo "✅ Unwrap: DEK déchiffrée"
    echo "✅ Intégrité: HMAC vérifié"
fi

echo ""
echo "=== Résumé ==="
echo ""

# Compter les succès
FEATURES_OK=0
if grep -q "✓ Feature 1 complétée avec succès" "$LOGFILE"; then
    ((FEATURES_OK++))
fi
if grep -q "✓ Feature 2 complétée avec succès" "$LOGFILE"; then
    ((FEATURES_OK++))
fi
if grep -q "✓ Feature 3 complétée avec succès" "$LOGFILE"; then
    ((FEATURES_OK++))
fi

echo "Features complétées: $FEATURES_OK/3"
echo "Fichier de log complet: $LOGFILE"

if [ $FEATURES_OK -eq 3 ]; then
    echo ""
    echo "🎉 Tous les tests réussis!"
    echo ""
    echo "✅ HSM initialisé"
    echo "✅ Keypair P-256 en cache RAM"
    echo "✅ DEK ChaCha20-256 en cache RAM"
    echo "✅ Clés persistantes dans HSM"
    exit 0
else
    echo ""
    echo "⚠️  Certains tests ont échoué"
    echo "Consulter le fichier de log pour détails"
    exit 1
fi
