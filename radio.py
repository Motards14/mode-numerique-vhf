# -*- coding: utf-8 -*-
"""
Commande de l'Icom IC-9700 par CI-V (câble USB, port COM virtuel).

Réglages à faire sur le poste (Menu > Set > Connectors) :
  - CI-V USB Port        : Unlink from [REMOTE]
  - CI-V USB Baud Rate   : 115200 (ou Auto)
  - CI-V Address         : A2h (valeur d'usine)
  - DATA MOD             : USB   (le son arrive par le câble USB)
et mettre le poste en USB-D (mode USB + DATA).
"""
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:                      # permet d'utiliser le reste sans pyserial
    serial = None

ADRESSE_IC9700 = 0xA2
ADRESSE_PC = 0xE0


def ports_disponibles():
    if serial is None:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]


class IC9700:
    def __init__(self, port, vitesse=115200, adresse=ADRESSE_IC9700):
        if serial is None:
            raise RuntimeError("module pyserial absent")
        self.adresse = adresse
        self.ser = serial.Serial(port, vitesse, timeout=0.3)

    def fermer(self):
        try:
            self.ptt(False)
        finally:
            self.ser.close()

    def _commande(self, octets):
        trame = bytes([0xFE, 0xFE, self.adresse, ADRESSE_PC]) + bytes(
            octets) + b"\xFD"
        self.ser.reset_input_buffer()
        self.ser.write(trame)
        return self._lire_reponse()

    def _lire_reponse(self, delai=0.5):
        """Renvoie la charge utile de la 1re trame venant du poste."""
        fin = time.time() + delai
        tampon = b""
        while time.time() < fin:
            tampon += self.ser.read(self.ser.in_waiting or 1)
            while b"\xFD" in tampon:
                trame, tampon = tampon.split(b"\xFD", 1)
                i = trame.find(b"\xFE\xFE")
                if i < 0:
                    continue
                trame = trame[i + 2:]
                # on ignore l'écho de notre propre commande
                if len(trame) >= 2 and trame[0] == ADRESSE_PC and \
                        trame[1] == self.adresse:
                    return trame[2:]
        return None

    def ptt(self, actif):
        rep = self._commande([0x1C, 0x00, 0x01 if actif else 0x00])
        if rep != b"\xFB":
            raise RuntimeError("le poste n'a pas confirmé le PTT "
                               "(vérifier port COM, vitesse, adresse CI-V)")

    def frequence(self):
        """Fréquence affichée en Hz, ou None."""
        rep = self._commande([0x03])
        if not rep or rep[0] != 0x03 or len(rep) < 6:
            return None
        f = 0
        for octet in reversed(rep[1:6]):          # BCD, poids faibles d'abord
            f = f * 100 + (octet >> 4) * 10 + (octet & 0x0F)
        return f
