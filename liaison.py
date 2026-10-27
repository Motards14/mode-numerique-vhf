# -*- coding: utf-8 -*-
"""
Liaison avec le poste, dans un FIL SÉPARÉ : la fenêtre du programme n'attend
jamais le port COM (un poste qui ne répond pas ne peut plus la bloquer).

Elle utilise le module « radio » repris de HFImage : tous les postes Hamlib,
Kenwood en direct, Icom VHF/UHF en CI-V direct, FLRig, OmniRig, TCI…, et le PTT
par CAT, DTR, RTS ou VOX.
"""
import contextlib
import queue
import threading
import time

import radio


class LiaisonRadio:
    def __init__(self):
        self.etat = "aucun poste choisi"
        self.ok = False               # liaison CAT établie
        self.freq_hz = None
        self.mode = None
        self.ptt_actif = False
        self.modele = ""
        self._cfg = dict(radio.DEFAULTS)
        self._file = queue.Queue()
        self._rig = None
        self._ptt = None
        self._pause = 0
        self._prochain_essai = 0.0
        self._fil = threading.Thread(target=self._boucle, daemon=True)
        self._fil.start()

    # ---------------------------------------------------- appels (rendent la main tout de suite)
    def configurer(self, cfg):
        self._file.put(("config", dict(cfg)))

    def ptt(self, actif):
        self._file.put(("ptt", bool(actif)))

    def fermer(self):
        self._file.put(("stop", None))
        self._fil.join(timeout=2.0)

    @contextlib.contextmanager
    def tenir(self):
        """Libère le port le temps d'un test de la fenêtre « Poste radio »."""
        fait = threading.Event()
        self._file.put(("pause", fait))
        fait.wait(5)
        try:
            yield
        finally:
            self._file.put(("reprise", None))

    # ---------------------------------------------------- fil radio
    def _boucle(self):
        derniere = 0.0
        while True:
            try:
                cmd, arg = self._file.get(timeout=0.3)
            except queue.Empty:
                cmd, arg = None, None
            try:
                if cmd == "stop":
                    self._fermer()
                    return
                if cmd == "config":
                    self._fermer()
                    self._cfg = arg
                    self._prochain_essai = 0.0
                elif cmd == "pause":
                    self._pause += 1
                    self._fermer()
                    self.etat = "poste libéré pour le test"
                    arg.set()
                elif cmd == "reprise":
                    self._pause = max(0, self._pause - 1)
                    self._prochain_essai = 0.0
                elif cmd == "ptt":
                    self._commander_ptt(arg)
                if self._pause:
                    continue
                if self._ptt is None and time.time() >= self._prochain_essai:
                    self._ouvrir()
                poll = max(1.0, float(self._cfg.get("poll") or 1))
                if (self._rig is not None and not self.ptt_actif
                        and time.time() - derniere >= poll):
                    derniere = time.time()
                    f = self._rig.freq()
                    if f:
                        self.freq_hz = f
                        self.ok = True
                        self.etat = f"{self.modele} : {f / 1e6:.4f} MHz"
                    else:
                        self.ok = False
                        self.etat = f"{self.modele} : pas de réponse à la lecture de fréquence"
            except Exception as e:
                self.etat = f"erreur : {e}"
                self.ok = False
                self._fermer()
                self._prochain_essai = time.time() + 5

    def _ouvrir(self):
        cfg = self._cfg
        kind = radio.rig_entry(cfg.get("rig", "none"))["kind"]
        try:
            self._rig = radio.make_rig(cfg) if kind != "none" else None
            self._ptt = radio.Ptt(cfg, self._rig)
            self.modele = (self._rig.model if self._rig is not None else "") or \
                radio.rig_label(cfg.get("rig", "none"))
            if self._rig is None:
                self.ok = cfg.get("ptt") in ("VOX", "DTR", "RTS")
                self.etat = f"pas de CAT — PTT {cfg.get('ptt')}"
            else:
                self.etat = f"{self.modele} : liaison ouverte"
        except Exception as e:
            self._fermer()
            self.ok = False
            self.etat = f"{e}"
            self._prochain_essai = time.time() + 5

    def _commander_ptt(self, actif):
        if self._ptt is None:
            self.ptt_actif = False
            if actif:
                self.etat = f"PTT impossible : {self.etat}"
            return
        if actif:
            quoi = self._cfg.get("set_mode")
            if self._rig is not None and quoi in ("usb", "data"):
                try:
                    self._rig.set_mode(quoi)        # « Mode » de la fenêtre Poste radio
                except Exception:
                    pass
            self._ptt.tx()
        else:
            self._ptt.rx()
        self.ptt_actif = actif

    def _fermer(self):
        p, r = self._ptt, self._rig
        self._ptt = self._rig = None
        self.ptt_actif = False
        if p is not None:
            try:
                p.close()
            except Exception:
                pass
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
