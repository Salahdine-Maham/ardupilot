# Branche de test HSM – ArduPilot 4.5.7

Cette branche est basée sur la version stable `4.5.7` (commit `2a3dc4b7bf2507120f7378a7b2fde73185e0c325`) d'ArduPilot.  
Elle est utilisée pour tester l'intégration d'un HSM (Hardware Security Module).

Tous les changements apportés seront documentés dans ce fichier.

## Étapes d'installation et de simulation

1. **Installation des prérequis**  
   Le système utilisé est **Ubuntu**. Un script est disponible dans `Tools/environment_install`.

   - Installer `pip` :
     ```bash
     sudo apt-get install python-pip
     ```

   - Lancer le script d'installation :
     ```bash
     ./install-prereqs-ubuntu.sh -y
     ```
     ⚠️ Certaines bibliothèques peuvent échouer à l'installation. Ces erreurs peuvent être ignorées.

2. **Compilation du firmware**

   - Lister les cartes disponibles :
     ```bash
     ./waf list_boards
     ```

   - Configurer la carte pour le build (ex : `sitl`) :
     ```bash
     ./waf configure --board sitl
     ```

   - Compiler un véhicule, par exemple pour un avion :
     ```bash
     ./waf plane
     ```

   - Si une erreur liée aux sous-modules apparaît, exécuter :
     ```bash
     git submodule update --init --recursive
     ```

3. **Résolution de problème de lien symbolique avec Python**

   Lors du lancement de la simulation, l'erreur suivante peut apparaître :
/usr/bin/env: «python»: Aucun fichier ou dossier de ce nom
Cela signifie que le système ne trouve pas `python`. Pour corriger cela, il faut modifier le fichier `waf-light` :

- Éditer le fichier :
  ```bash
  nano /home/salah/repositories/ardupilot/modules/waf/waf-light
  ```

- Remplacer la ligne :
  ```bash
  #!/usr/bin/env python
  ```
  par :
  ```bash
  #!/usr/bin/env python3
  ```

4. **Lancer la simulation SITL**

Une fois la compilation terminée, lancer la simulation avec la commande suivante :
```bash
../Tools/autotest/sim_vehicle.py --console --map -w
