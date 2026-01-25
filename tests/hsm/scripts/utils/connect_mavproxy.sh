#!/bin/bash
# Script pour connecter MAVProxy à ArduCopter SITL
# Cela débloque l'initialisation et permet de voir les logs HSM

echo "Connexion à ArduCopter SITL sur tcp:127.0.0.1:5760..."
mavproxy.py --master=tcp:127.0.0.1:5760 --console --map
