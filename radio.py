# -*- coding: utf-8 -*-
"""
Liaison avec l'Icom IC-9700 (câble USB, port COM virtuel).

Toutes les opérations sur le port COM se font dans un FIL SÉPARÉ, avec des
délais maximum : un port qui ne répond pas ne peut plus bloquer la
fenêtre du programme.

Le câble USB de l'IC-9700 crée DEUX ports COM (pilote Silicon Labs
CP210x) : prendre celui marqué « Enhanced » pour le CI-V.

PTT possible par :
  - CI-V : commande envoyée au poste (réglages ci-dessous)
  - RTS ou DTR : sur le port COM, si le poste est réglé en
    « USB SEND » = RTS ou DTR (Menu > Set > Connectors > USB SEND/Keying)

Réglages CI-V de l'IC-9700 (Menu > Set > Connectors > CI-V) :
  - CI-V USB Port        : Unlink from [REMOTE]
  - CI-V USB Baud Rate   : 115200 (ou Auto)
  - CI-V Address         : A2h (valeur d'usine)
  - DATA MOD             : USB   (le son arrive par le câble USB)
et mettre le poste en USB-D (mode USB + DATA).
"""
import queue
import threading
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:                      # permet d'utiliser le reste sans pyserial
    serial = None

ADRESSE_IC9700 = 0xA2
ADRESSE_PC = 0xE0
METHODES_PTT = ("CI-V", "RTS", "DTR")


def ports_disponibles():
    """Liste de (port, description), ex. ('COM5', 'Silicon Labs ... Enhanced')."""
    if serial is None:
        return []
    res = []
    for p in serial.tools.list_ports.comports():
        res.append((p.device, p.description or ""))
    return sorted(res, key=lambda x: (len(x[0]), x[0]))


def port_conseille(ports):
    """Le port CI-V probable de l'IC-9700."""
    for mot in ("Enhanced", "IC-9700", "CP210"):
        for dev, desc in ports:
            if mot.lower() in desc.lower():
                return dev
    return ports[0][0] if ports else ""


class _CIV:
    """Échanges CI-V élémentaires (appelés uniquement depuis le fil radio)."""

    def __init__(self, ser, adresse=ADRESSE_IC9700):
        self.ser = ser
        self.adresse = adresse

    def commande(self, octets, delai=0.4):
        trame = bytes([0xFE, 0xFE, self.adresse, ADRESSE_PC]) + bytes(
            octets) + b"\xFD"
        self.ser.reset_input_buffer()
        self.ser.write(trame)
        fin = time.time() + delai
        tampon = b""
        while time.time() < fin:
            tampon += self.ser.read(max(1, self.ser.in_waiting))
            while b"\xFD" in tampon:
                t, tampon = tampon.split(b"\xFD", 1)
                i = t.find(b"\xFE\xFE")
                if i < 0:
                    continue
                t = t[i + 2:]
                # on ignore l'écho de notre propre commande
                if len(t) >= 2 and t[0] == ADRESSE_PC and t[1] == self.adresse:
                    return t[2:]
        return None

    def ptt(self, actif):
        return self.commande([0x1C, 0x00, 0x01 if actif else 0x00]) == b"\xFB"

    def frequence(self):
        rep = self.commande([0x03])
        if not rep or rep[0] != 0x03 or len(rep) < 6:
            return None
        f = 0
        for octet in reversed(rep[1:6]):          # BCD, poids faibles d'abord
            f = f * 100 + (octet >> 4) * 10 + (octet & 0x0F)
        return f


class LiaisonRadio:
    """Pilote le poste dans un fil séparé. Toutes les méthodes publiques
    rendent la main immédiatement."""

    def __init__(self):
        self.etat = "aucun port choisi"
        self.connecte = False
        self.freq_hz = None
        self.ptt_actif = False
        self._file = queue.Queue()
        self._ser = None
        self._civ = None
        self._port = ""
        self._methode = "CI-V"
        self._vitesse = 115200
        self._prochain_essai = 0.0
        self._fil = threading.Thread(target=self._boucle, daemon=True)
        self._fil.start()

    # ---------------------------------------------------- appels publics
    def configurer(self, port, methode="CI-V", vitesse=115200):
        self._file.put(("config", (port, methode, vitesse)))

    def ptt(self, actif):
        self._file.put(("ptt", bool(actif)))

    def fermer(self):
        self._file.put(("stop", None))
        self._fil.join(timeout=1.5)

    # ---------------------------------------------------- fil radio
    def _boucle(self):
        derniere_freq = 0.0
        while True:
            try:
                cmd, arg = self._file.get(timeout=0.5)
            except queue.Empty:
                cmd, arg = None, None
            try:
                if cmd == "stop":
                    self._ptt(False)
                    self._fermer_port()
                    return
                if cmd == "config":
                    self._port, self._methode, self._vitesse = arg
                    self._fermer_port()
                    self._ouvrir()
                elif cmd == "ptt":
                    self._ptt(arg)
                # reconnexion automatique, lecture de fréquence
                if not self.connecte and self._port and \
                        time.time() > self._prochain_essai:
                    self._ouvrir()
                if (self.connecte and self._methode == "CI-V"
                        and not self.ptt_actif
                        and time.time() - derniere_freq > 2.0):
                    derniere_freq = time.time()
                    f = self._civ.frequence()
                    if f:
                        self.freq_hz = f
                        self.etat = f"CI-V OK — {f / 1e6:.4f} MHz"
                    else:
                        self.etat = ("port ouvert, le poste ne répond pas "
                                     "(vérifier les réglages CI-V)")
            except Exception as e:
                self.etat = f"erreur : {e}"
                self._fermer_port()
                self._prochain_essai = time.time() + 5

    def _ouvrir(self):
        if serial is None:
            self.etat = "module pyserial absent"
            return
        if not self._port:
            self.etat = "aucun port choisi"
            return
        try:
            s = serial.Serial()
            s.port = self._port
            s.baudrate = self._vitesse
            s.timeout = 0.1
            s.write_timeout = 0.3
            # RTS/DTR au repos AVANT l'ouverture (sinon le poste peut
            # passer en émission si USB SEND = RTS ou DTR)
            s.rts = False
            s.dtr = False
            s.open()
            self._ser = s
            self._civ = _CIV(s)
            self.connecte = True
            self.etat = f"port {self._port} ouvert (PTT par {self._methode})"
        except Exception as e:
            self.connecte = False
            self.etat = f"impossible d'ouvrir {self._port} : {e}"
            self._prochain_essai = time.time() + 5

    def _fermer_port(self):
        self.connecte = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self._civ = None

    def _ptt(self, actif):
        if not self.connecte:
            self.ptt_actif = False
            return
        if self._methode == "RTS":
            self._ser.rts = actif
        elif self._methode == "DTR":
            self._ser.dtr = actif
        else:
            if not self._civ.ptt(actif):
                self.etat = ("le poste n'a pas confirmé le PTT (port, "
                             "vitesse ou adresse CI-V ?)")
        self.ptt_actif = actif
