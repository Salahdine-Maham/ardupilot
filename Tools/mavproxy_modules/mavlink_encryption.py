#!/usr/bin/env python
'''Module MAVProxy pour encoder/décoder les messages MAVLink (ex: chiffrement AES avec KEK)'''
import time
from pymavlink import mavutil
from MAVProxy.modules.lib import mp_module
from cryptography.fernet import Fernet  # Pour AES (installez via pip si besoin)

class EncryptModule(mp_module.MPModule):
    def __init__(self, mpstate):
        super(EncryptModule, self).__init__(mpstate, "encrypt", "Module pour chiffrer/déchiffrer MAVLink")
        self.key = b'OWf8D4klfPaVKl75nNis5pSHnHtJLQWigef2UecnbZ0='  # Remplacez par votre KEK (générez avec Fernet.generate_key())
        self.cipher = Fernet(self.key)  # Initialisez le chiffreur AES
        self.add_command('toggle_encrypt', self.cmd_toggle_encrypt, "Activer/désactiver chiffrement")
        self.encrypt_enabled = False  # État initial : chiffrement désactivé

    def cmd_toggle_encrypt(self, args):
        self.encrypt_enabled = not self.encrypt_enabled
        print(f"Chiffrement {'activé' if self.encrypt_enabled else 'désactivé'}")

    def mavlink_packet(self, m):
        '''Intercepte les paquets entrants et les décode si chiffrés'''
        if self.encrypt_enabled:
            if m.get_type() == 'HEARTBEAT':  # Remplacez par votre message custom ou un type spécifique
                # Exemple : Décode le payload si chiffré
                try:
                    decrypted_payload = self.cipher.decrypt(m.payload)  # Assume payload est chiffré
                    m.payload = decrypted_payload  # Remplace le payload déchiffré
                    print("Paquet déchiffré:", m)
                except Exception as e:
                    print("Erreur de déchiffrement:", e)
        # Laissez passer le paquet (modifié ou non) au GCS

    def master_callback(self, m, master):
        '''Intercepte les paquets sortants avant envoi et les encode'''
        if self.encrypt_enabled:
            if m.get_type() == 'HEARTBEAT':  # Pour messages à chiffrer
                try:
                    encrypted_payload = self.cipher.encrypt(m.payload)  # Chiffre le payload
                    m.payload = encrypted_payload  # Remplace par le payload chiffré
                    print("Paquet chiffré avant envoi:", m)
                except Exception as e:
                    print("Erreur de chiffrement:", e)
        # Laissez passer le paquet au master (envoi)

def init(mpstate):
    '''Initialise le module'''
    return EncryptModule(mpstate)
