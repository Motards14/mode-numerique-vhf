# -*- coding: utf-8 -*-
"""
F4GOP VHF — programme principal (interface moderne, version 2)

Mode numérique cohérent pour la VHF/UHF : émission, réception, cascade,
QSO automatique, journal ADIF. Le poste est piloté par le module « Poste
radio » repris de HFImage (tous les postes Hamlib, Icom VHF/UHF en CI-V
direct, Kenwood direct, FLRig, OmniRig, TCI…).

IMPORTANT : l'horloge du PC doit être à l'heure exacte (à moins d'une seconde
près), comme pour FT8.
"""
import json
import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np

import journal_adif
import radio
from decodeur import decoder_periode, PLAGE_DT
from liaison import LiaisonRadio
from message import coder_message, ErreurMessage, hash21
from modem import moduler, duree_tx, SOUS_MODES, FS, DEBUT_TX
from sequenceur import Sequenceur, _est_locator
from theme_vhf import C, Pilule, Panneau, badge, police, appliquer, degrade_cascade, curseur

try:
    import sounddevice as sd
except Exception:                                  # pas de carte son (tests)
    sd = None

VERSION = "2.0"
RETARD_MAX_TX = 1.2           # départ d'émission le plus tardif (s)
TAMPON_S = 130                # secondes d'audio gardées en mémoire
CASC_FMIN, CASC_FMAX = 200.0, 2800.0
FICHIER_REGLAGES = os.path.join(os.path.expanduser("~"), ".f4gop_vhf.json")

REGLAGES_DEFAUT = {
    "indicatif": "F4GOP", "locator": "IN98QR", "sous_mode": "R15", "parite": 0,
    "f_audio": 1500, "niveau": 0.5, "entree_son": "", "sortie_son": "",
    "auto": True, "cq_apres": False, "max_rep": 6, "max_cq": 40,
    "adif_mode": "MFSK", "adif_sous_mode": "F4GOP-VHF", "fichier_adif": journal_adif.FICHIER,
    "contraste": 12, "radio": None,
}


# ====================================================================== outils
def charger_reglages():
    r = dict(REGLAGES_DEFAUT)
    try:
        with open(FICHIER_REGLAGES, encoding="utf-8") as f:
            r.update(json.load(f))
    except Exception:
        pass
    if not isinstance(r.get("radio"), dict):
        # reprise des réglages de la version 1 (port COM + PTT CI-V/RTS/DTR de l'IC-9700)
        rc = dict(radio.DEFAULTS, rig="icom:IC-9700", baud=115200, ptt="CAT")
        if r.get("port"):
            rc["port"] = r["port"]
            if r.get("ptt") in ("RTS", "DTR"):
                rc.update(rig="none", ptt=r["ptt"], ptt_port=r["port"])
        r["radio"] = rc
    else:
        r["radio"] = dict(radio.DEFAULTS, **r["radio"])
    return r


def locator_latlon(loc):
    """Centre du carré Maidenhead (4 ou 6 caractères) -> (lat, lon) en degrés."""
    loc = (loc or "").strip().upper()
    if len(loc) < 4 or not _est_locator(loc[:6] if len(loc) >= 6 else loc[:4]):
        return None
    lon = (ord(loc[0]) - 65) * 20 - 180 + int(loc[2]) * 2
    lat = (ord(loc[1]) - 65) * 10 - 90 + int(loc[3])
    if len(loc) >= 6:
        lon += (ord(loc[4]) - 65) * (2 / 24) + 1 / 24
        lat += (ord(loc[5]) - 65) * (1 / 24) + 1 / 48
    else:
        lon += 1
        lat += 0.5
    return lat, lon


def distance_cap(loc1, loc2):
    """Distance (km) et cap (°) de loc1 vers loc2, ou (None, None)."""
    a, b = locator_latlon(loc1), locator_latlon(loc2)
    if not a or not b:
        return None, None
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    d = 2 * 6371 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1)
                                       * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return d, (math.degrees(math.atan2(y, x)) + 360) % 360


def appareils_audio(entree):
    """Liste (index, nom) des entrées ou sorties audio (API MME de préférence)."""
    if sd is None:
        return []
    res = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels" if entree else "max_output_channels"] > 0:
                api = sd.query_hostapis(d["hostapi"])["name"]
                res.append((i, f"{d['name']}  [{api}]"))
    except Exception:
        return []
    mme = [r for r in res if "MME" in r[1]]
    return mme or res


def choisir_appareil(liste, voulu):
    noms = [n for _, n in liste]
    if voulu in noms:
        return voulu
    return next((n for n in noms if "USB Audio CODEC" in n), noms[0] if noms else "")


def age_texte(s):
    if s < 60:
        return f"{int(s)} s"
    if s < 3600:
        return f"{int(s // 60)} min"
    return f"{int(s // 3600)} h"


class TamponAudio:
    """Mémoire circulaire d'audio datée en temps UTC (time.time())."""

    def __init__(self, duree):
        self.n = int(duree * FS)
        self.buf = np.zeros(self.n, dtype=np.float32)
        self.ecrit = 0
        self.t_fin = None
        self.verrou = threading.Lock()

    def ajouter(self, bloc, t_fin):
        with self.verrou:
            k = bloc.size
            i = self.ecrit % self.n
            j = min(k, self.n - i)
            self.buf[i:i + j] = bloc[:j]
            self.buf[:k - j] = bloc[j:]
            self.ecrit += k
            self.t_fin = t_fin

    def extraire(self, t_debut, duree):
        with self.verrou:
            if self.t_fin is None:
                return None
            fin_abs = self.ecrit
            debut_abs = fin_abs - int(round((self.t_fin - t_debut) * FS))
            n = int(duree * FS)
            if debut_abs < max(0, fin_abs - self.n):
                return None
            out = np.zeros(n, dtype=np.float32)
            dispo = min(n, fin_abs - debut_abs)
            for k in range(0, dispo, 65536):
                m = min(65536, dispo - k)
                a = (debut_abs + k) % self.n
                b = min(m, self.n - a)
                out[k:k + b] = self.buf[a:a + b]
                out[k + b:k + m] = self.buf[:m - b]
            return out

    def derniers(self, n):
        with self.verrou:
            if self.ecrit < n:
                return None
            a = (self.ecrit - n) % self.n
            if a + n <= self.n:
                return self.buf[a:a + n].copy()
            return np.concatenate([self.buf[a:], self.buf[:a + n - self.n]])


# ====================================================================== application
class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"F4GOP VHF  v{VERSION}")
        self.minsize(1180, 760)
        appliquer(self)
        self.cfg = charger_reglages()
        self.file_ui = queue.Queue()
        self.radio = LiaisonRadio()
        self.radio.configurer(self.cfg["radio"])
        self.seq = Sequenceur(self.cfg["indicatif"], self.cfg["locator"],
                              int(self.cfg["max_rep"]), int(self.cfg["max_cq"]))
        self.tampon = TamponAudio(TAMPON_S)
        self.flux = None
        self.niveau_entree = 1e-9
        self.carnet = {}
        self.decodes = []                  # tous les décodages (pour les filtres)
        self.stations = {}                 # indicatif -> infos
        self.contactes = set()
        self.etiquettes_casc = []          # (f, indicatif, heure)
        self.nb_qso = 0
        self.emission_active = False
        self.en_cours = False
        self.tune = False
        self.arret = threading.Event()
        self.derniere_periode = None
        self.periodes_tx = set()
        self.derniere_decodee = None
        self.decodage_en_cours = False
        self.dernier_decodage = ""
        self.filtre = "tous"
        self.casc_l = 900
        self.casc_h = 150
        self.casc = np.zeros((self.casc_h, self.casc_l), dtype=np.uint8)
        self.degrade = degrade_cascade()

        self.v_msg = tk.StringVar()
        self.v_dx = tk.StringVar()
        self.v_rep = tk.IntVar(value=-12)
        self.v_niv = tk.DoubleVar(value=float(self.cfg["niveau"]))
        self._construire()
        self.v_msg.set(f"CQ {self.cfg['indicatif']} {self.cfg['locator']}")
        self.protocol("WM_DELETE_WINDOW", self.quitter)
        self._demarrer_capture()
        self.after(50, self._horloge)
        self.after(250, self._rafraichir_cascade)
        self.after(400, self._rafraichir_etat)
        self.after(5000, self._rafraichir_ages)
        self.log(f"F4GOP VHF {VERSION} démarré — poste : {radio.describe(self.cfg['radio'])}")

    # ================================================================== interface
    def _construire(self):
        self._barre_haut()
        self._barre_frequence()
        corps = tk.Frame(self, bg=C["fond"])
        corps.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._panneau_cascade(corps)
        self._panneau_commandes(corps)
        bas = tk.PanedWindow(corps, orient="horizontal", bg=C["fond"], sashwidth=8, bd=0,
                             sashrelief="flat")
        bas.pack(fill="both", expand=True, pady=(8, 0))
        g = self._panneau_stations(bas)
        d = self._panneau_activite(bas)
        bas.add(g, minsize=420, stretch="always")
        bas.add(d, minsize=420, stretch="always")
        self._barre_etat()

    # ---------------------------------------------------------------- barre du haut
    def _barre_haut(self):
        b = tk.Frame(self, bg=C["barre"], highlightthickness=1, highlightbackground=C["bord"])
        b.pack(fill="x")
        z = tk.Frame(b, bg=C["barre"])
        z.pack(fill="x", padx=12, pady=8)
        logo = tk.Frame(z, bg=C["barre"])
        logo.pack(side="left")
        tk.Label(logo, text="F4GOP", bg=C["barre"], fg=C["accent"], font=police(16, True)).pack(
            side="left")
        tk.Label(logo, text=" VHF", bg=C["barre"], fg=C["texte"], font=police(16, True)).pack(
            side="left")
        tk.Label(logo, text=f"  v{VERSION}", bg=C["barre"], fg=C["faible"],
                 font=police(8)).pack(side="left", anchor="s", pady=(0, 4))

        st = tk.Frame(z, bg=C["barre"])
        st.pack(side="left", padx=(18, 10))
        self.l_ind = tk.Label(st, text=self.cfg["indicatif"], bg=C["barre"], fg=C["texte"],
                              font=police(12, True))
        self.l_ind.pack(anchor="w")
        self.l_loc = tk.Label(st, text=self.cfg["locator"], bg=C["barre"], fg=C["doux"],
                              font=police(9, mono=True))
        self.l_loc.pack(anchor="w")

        # badge du poste (clic = réglages du poste)
        self.badge_poste = tk.Frame(z, bg=C["pilule"], highlightthickness=1,
                                    highlightbackground=C["bord"], cursor="hand2")
        self.badge_poste.pack(side="left", padx=6)
        self.l_poste = tk.Label(self.badge_poste, text="", bg=C["pilule"], fg=C["accent"],
                                font=police(10, True), cursor="hand2")
        self.l_poste.pack(anchor="w", padx=10, pady=(3, 0))
        self.l_poste_etat = tk.Label(self.badge_poste, text="", bg=C["pilule"], fg=C["doux"],
                                     font=police(8), cursor="hand2")
        self.l_poste_etat.pack(anchor="w", padx=10, pady=(0, 3))
        for w in (self.badge_poste, self.l_poste, self.l_poste_etat):
            w.bind("<Button-1>", lambda e: self.ouvrir_reglages("poste"))

        self.p_rxtx = Pilule(z, "RX", style="vert", taille=12, largeur=64, hauteur=34,
                             fond_parent=C["barre"])
        self.p_rxtx.pack(side="left", padx=(16, 8))

        pr = tk.Frame(z, bg=C["barre"])
        pr.pack(side="left", padx=6)
        self.cv_prog = tk.Canvas(pr, width=150, height=8, bg=C["pilule"], highlightthickness=0)
        self.cv_prog.pack(anchor="w", pady=(4, 2))
        self.l_prog = tk.Label(pr, text="", bg=C["barre"], fg=C["doux"], font=police(8))
        self.l_prog.pack(anchor="w")

        hz = tk.Frame(z, bg=C["barre"])
        hz.pack(side="left", padx=12)
        self.l_heure = tk.Label(hz, text="", bg=C["barre"], fg=C["texte"],
                                font=police(16, True, mono=True))
        self.l_heure.pack(side="left")
        tk.Label(hz, text=" UTC", bg=C["barre"], fg=C["doux"], font=police(9)).pack(
            side="left", anchor="s", pady=(0, 4))

        self.l_sync = tk.Label(z, text="● en attente", bg=C["barre"], fg=C["doux"],
                               font=police(9))
        self.l_sync.pack(side="left", padx=10)

        self.p_reglages = Pilule(z, "⚙  Réglages", lambda: self.ouvrir_reglages(),
                                 fond_parent=C["barre"], hauteur=30)
        self.p_reglages.pack(side="right")
        self.p_sm = {}
        for sm in reversed(list(SOUS_MODES)):
            p = Pilule(z, f"{sm}  {SOUS_MODES[sm][0]} s", lambda s=sm: self.choisir_sous_mode(s),
                       fond_parent=C["barre"], hauteur=30)
            p.pack(side="right", padx=3)
            self.p_sm[sm] = p
        tk.Label(z, text="Sous-mode", bg=C["barre"], fg=C["faible"], font=police(8)).pack(
            side="right", padx=(0, 4))
        self._maj_sous_mode()

    # ---------------------------------------------------------------- fréquence
    def _barre_frequence(self):
        b = tk.Frame(self, bg=C["fond"])
        b.pack(fill="x", padx=10, pady=8)
        fz = tk.Frame(b, bg=C["panneau"], highlightthickness=1, highlightbackground=C["bord"])
        fz.pack(side="left")
        self.l_freq = tk.Label(fz, text="---.--- ---", bg=C["panneau"], fg=C["accent"],
                               font=police(24, True, mono=True))
        self.l_freq.pack(side="left", padx=(14, 4), pady=4)
        tk.Label(fz, text="MHz", bg=C["panneau"], fg=C["doux"], font=police(10, True)).pack(
            side="left", pady=(8, 0))
        self.l_bande = badge(fz, "—", C["accent"], C["accent_fond"])
        self.l_bande.pack(side="left", padx=12)

        tx = tk.Frame(b, bg=C["fond"])
        tx.pack(side="left", padx=14)
        tk.Label(tx, text="ÉMISSION EN", bg=C["fond"], fg=C["faible"], font=police(8)).pack(
            anchor="w")
        ligne = tk.Frame(tx, bg=C["fond"])
        ligne.pack(anchor="w")
        self.p_par = [Pilule(ligne, "1re période (paire)", lambda: self.choisir_parite(0),
                             hauteur=28),
                      Pilule(ligne, "2e période (impaire)", lambda: self.choisir_parite(1),
                             hauteur=28)]
        for p in self.p_par:
            p.pack(side="left", padx=(0, 4))
        self._maj_parite()

        au = tk.Frame(b, bg=C["fond"])
        au.pack(side="left", padx=10)
        tk.Label(au, text="QSO", bg=C["fond"], fg=C["faible"], font=police(8)).pack(anchor="w")
        self.p_auto = Pilule(au, "", self.basculer_auto, hauteur=28)
        self.p_auto.pack(anchor="w")
        self._maj_auto()

        fa = tk.Frame(b, bg=C["fond"])
        fa.pack(side="left", padx=10)
        tk.Label(fa, text="FRÉQUENCE AUDIO TX", bg=C["fond"], fg=C["faible"],
                 font=police(8)).pack(anchor="w")
        lf = tk.Frame(fa, bg=C["fond"])
        lf.pack(anchor="w")
        Pilule(lf, "−", lambda: self.decaler_fa(-10), largeur=30, hauteur=28).pack(side="left")
        self.l_fa = tk.Label(lf, text="", bg=C["fond"], fg=C["texte"], width=8,
                             font=police(11, True, mono=True))
        self.l_fa.pack(side="left")
        Pilule(lf, "+", lambda: self.decaler_fa(10), largeur=30, hauteur=28).pack(side="left")
        self._maj_fa()

        nv = tk.Frame(b, bg=C["fond"])
        nv.pack(side="right", padx=4)
        tk.Label(nv, text="NIVEAUX", bg=C["fond"], fg=C["faible"], font=police(8)).pack(
            anchor="w")
        l1 = tk.Frame(nv, bg=C["fond"])
        l1.pack(anchor="w")
        tk.Label(l1, text="Entrée", bg=C["fond"], fg=C["doux"], width=6, anchor="w",
                 font=police(9)).pack(side="left")
        self.cv_niv = tk.Canvas(l1, width=140, height=8, bg=C["pilule"], highlightthickness=0)
        self.cv_niv.pack(side="left", padx=4)
        self.l_niv = tk.Label(l1, text="", bg=C["fond"], fg=C["doux"], width=9,
                              font=police(9, mono=True))
        self.l_niv.pack(side="left")
        l2 = tk.Frame(nv, bg=C["fond"])
        l2.pack(anchor="w", pady=(2, 0))
        tk.Label(l2, text="Sortie", bg=C["fond"], fg=C["doux"], width=6, anchor="w",
                 font=police(9)).pack(side="left")
        curseur(l2, self.v_niv, 0.02, 1.0, 140, lambda v: self._maj_niv_tx()).pack(
            side="left", padx=4)
        self.l_niv_tx = tk.Label(l2, text="", bg=C["fond"], fg=C["doux"], width=9,
                                 font=police(9, mono=True))
        self.l_niv_tx.pack(side="left")
        self._maj_niv_tx()

    # ---------------------------------------------------------------- cascade
    def _panneau_cascade(self, parent):
        p = Panneau(parent, "Cascade")
        p.pack(fill="x")
        tk.Label(p.entete, text="  clic = fréquence d'émission · les indicatifs décodés "
                 "s'affichent à leur fréquence", bg=C["panneau"], fg=C["faible"],
                 font=police(8)).pack(side="left")
        tk.Label(p.entete, text="Contraste", bg=C["panneau"], fg=C["doux"],
                 font=police(8)).pack(side="right")
        self.v_contraste = tk.DoubleVar(value=float(self.cfg["contraste"]))
        curseur(p.entete, self.v_contraste, 4, 30, 110).pack(side="right", padx=6)
        self.cv_casc = tk.Canvas(p.corps, height=self.casc_h + 18, bg="#05070d",
                                 highlightthickness=0, cursor="crosshair")
        self.cv_casc.pack(fill="x")
        self.img_casc = tk.PhotoImage(width=self.casc_l, height=self.casc_h)
        self.cv_casc.create_image(0, 0, image=self.img_casc, anchor="nw", tags="img")
        self.cv_casc.bind("<Button-1>", self._clic_cascade)
        self.cv_casc.bind("<Configure>", self._taille_cascade)

    def _taille_cascade(self, ev):
        l = max(300, ev.width)
        if l != self.casc_l:
            nouv = np.zeros((self.casc_h, l), dtype=np.uint8)
            m = min(l, self.casc_l)
            nouv[:, :m] = self.casc[:, :m]
            self.casc, self.casc_l = nouv, l
            self.img_casc.configure(width=l)
        self._dessiner_echelle()

    def _x_de_f(self, f):
        return (f - CASC_FMIN) / (CASC_FMAX - CASC_FMIN) * self.casc_l

    def _dessiner_echelle(self):
        cv = self.cv_casc
        cv.delete("echelle")
        y = self.casc_h
        cv.create_rectangle(0, y, self.casc_l, y + 18, fill=C["panneau"], outline="",
                            tags="echelle")
        for f in range(500, 2800, 250):
            x = self._x_de_f(f)
            grand = f % 500 == 0
            cv.create_line(x, y, x, y + (6 if grand else 3), fill=C["doux"], tags="echelle")
            if grand:
                cv.create_text(x, y + 12, text=str(f), fill=C["doux"], font=police(8),
                               tags="echelle")
        self._dessiner_reperes()

    def _dessiner_reperes(self):
        cv = self.cv_casc
        cv.delete("repere")
        fa = float(self.cfg["f_audio"])
        larg = 1.2 * FS / SOUS_MODES[self.cfg["sous_mode"]][1]
        x0, x1 = self._x_de_f(fa - larg / 2), self._x_de_f(fa + larg / 2)
        cv.create_rectangle(x0, 2, x1, self.casc_h - 1, outline=C["rouge"], width=2,
                            tags="repere")
        cv.create_text(x1 + 4, 10, text="TX", anchor="w", fill=C["rouge"],
                       font=police(8, True), tags="repere")
        maintenant = time.time()
        periode = SOUS_MODES[self.cfg["sous_mode"]][0]
        for f, ind, t, moi in self.etiquettes_casc:
            if maintenant - t > 2.2 * periode:
                continue
            x = self._x_de_f(f)
            coul = C["rouge"] if moi else C["texte"]
            tid = cv.create_text(x + 4, 22, text=ind, anchor="w", fill=coul,
                                 font=police(8, True), tags="repere")
            bx = cv.bbox(tid)
            r = cv.create_rectangle(bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1,
                                    fill="#0b1220", outline=C["vert"] if not moi else C["rouge"],
                                    tags="repere")
            cv.tag_raise(tid, r)
            cv.create_line(x, 14, x, self.casc_h - 1, fill=C["vert"], dash=(2, 3),
                           tags="repere")

    def _clic_cascade(self, ev):
        if ev.y > self.casc_h:
            return
        f = CASC_FMIN + ev.x / self.casc_l * (CASC_FMAX - CASC_FMIN)
        self.cfg["f_audio"] = int(round(f / 10) * 10)
        self._maj_fa()

    # ---------------------------------------------------------------- commandes TX
    def _panneau_commandes(self, parent):
        p = tk.Frame(parent, bg=C["panneau"], highlightthickness=1, highlightbackground=C["bord"])
        p.pack(fill="x", pady=(8, 0))
        l1 = tk.Frame(p, bg=C["panneau"])
        l1.pack(fill="x", padx=10, pady=(8, 4))
        fp = C["panneau"]
        Pilule(l1, "Appel CQ", self.lancer_cq, style="accent", fond_parent=fp).pack(side="left")
        self.p_tx = Pilule(l1, "", self.basculer_tx, fond_parent=fp, largeur=110)
        self.p_tx.pack(side="left", padx=6)
        Pilule(l1, "Stop TX", self.stop, style="rouge", fond_parent=fp).pack(side="left")
        self.p_tune = Pilule(l1, "Tune", self.basculer_tune, fond_parent=fp)
        self.p_tune.pack(side="left", padx=6)
        Pilule(l1, "Arrêter le QSO", self.arreter_qso, style="fantome", fond_parent=fp).pack(
            side="left")
        self.l_qso = tk.Label(l1, text="", bg=fp, fg=C["accent"], font=police(10, True))
        self.l_qso.pack(side="left", padx=14)
        self.l_prochain = tk.Label(l1, text="", bg=fp, fg=C["doux"], font=police(9))
        self.l_prochain.pack(side="right")
        self._maj_tx()

        l2 = tk.Frame(p, bg=fp)
        l2.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(l2, text="TX ›", bg=fp, fg=C["rouge"], font=police(11, True, mono=True)).pack(
            side="left")
        e = tk.Entry(l2, textvariable=self.v_msg, width=28, bg=C["champ"], fg=C["texte"],
                     insertbackground=C["texte"], relief="flat", font=police(12, True, mono=True),
                     highlightthickness=1, highlightbackground=C["bord"],
                     highlightcolor=C["accent"])
        e.pack(side="left", padx=6, ipady=3)
        e.bind("<Return>", lambda ev: self.envoyer_manuel())
        Pilule(l2, "Envoyer", self.envoyer_manuel, style="vert", fond_parent=fp).pack(side="left")
        tk.Label(l2, text="   Correspondant", bg=fp, fg=C["doux"], font=police(9)).pack(
            side="left")
        tk.Entry(l2, textvariable=self.v_dx, width=9, bg=C["champ"], fg=C["texte"],
                 insertbackground=C["texte"], relief="flat", font=police(10, True, mono=True),
                 highlightthickness=1, highlightbackground=C["bord"]).pack(side="left", padx=4,
                                                                           ipady=2)
        tk.Label(l2, text="Report", bg=fp, fg=C["doux"], font=police(9)).pack(side="left",
                                                                              padx=(6, 2))
        ttk.Spinbox(l2, from_=-50, to=49, width=4, textvariable=self.v_rep).pack(side="left")
        for nom, fn in (("Locator", lambda c, l, d, r: f"{d} {c} {l}"),
                        ("Report", lambda c, l, d, r: f"{d} {c} {r:+03d}"),
                        ("R-report", lambda c, l, d, r: f"{d} {c} R{r:+03d}"),
                        ("RR73", lambda c, l, d, r: f"{d} {c} RR73"),
                        ("73", lambda c, l, d, r: f"{d} {c} 73")):
            Pilule(l2, nom, lambda f=fn: self._remplir(f), fond_parent=fp, gras=False,
                   hauteur=26).pack(side="left", padx=2)

    # ---------------------------------------------------------------- stations
    def _panneau_stations(self, parent):
        p = Panneau(parent, "Stations")
        self.l_nb_st = badge(p.entete, "0", "#04121c", C["accent"])
        self.l_nb_st.pack(side="left", padx=8)
        tk.Label(p.entete, text="double-clic = appeler", bg=C["panneau"], fg=C["faible"],
                 font=police(8)).pack(side="right")
        cols = ("ind", "appelle", "loc", "dist", "cap", "snr", "age")
        tv = ttk.Treeview(p.corps, columns=cols, show="headings", height=8)
        for c, t, w, a in zip(cols, ("INDICATIF", "APPELLE", "LOC.", "DIST", "CAP", "SNR", "ÂGE"),
                              (100, 90, 70, 75, 55, 50, 60),
                              ("w", "w", "w", "e", "e", "e", "e")):
            tv.heading(c, text=t, anchor=a)
            tv.column(c, width=w, anchor=a, stretch=c in ("ind", "appelle"))
        tv.tag_configure("moi", background="#3a1520", foreground="#fecaca")
        tv.tag_configure("cq", foreground="#86efac")
        tv.tag_configure("contacte", foreground=C["faible"])
        sb = ttk.Scrollbar(p.corps, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.bind("<Double-1>", self._double_clic_station)
        self.tv_st = tv
        return p

    # ---------------------------------------------------------------- activité
    def _panneau_activite(self, parent):
        p = Panneau(parent, "Activité bande")
        self.p_filtres = {}
        for cle, nom in (("tous", "Tous"), ("cq", "CQ"), ("moi", "Pour moi")):
            q = Pilule(p.entete, nom, lambda k=cle: self.choisir_filtre(k), hauteur=24,
                       gras=False, fond_parent=C["panneau"])
            q.pack(side="left", padx=(8 if cle == "tous" else 2, 0))
            self.p_filtres[cle] = q
        Pilule(p.entete, "Effacer", self.effacer_activite, style="fantome", hauteur=24,
               gras=False, fond_parent=C["panneau"]).pack(side="right")
        self._maj_filtres()
        cols = ("utc", "db", "dt", "freq", "msg")
        haut = tk.Frame(p.corps, bg=C["panneau"])
        haut.pack(fill="both", expand=True)
        tv = ttk.Treeview(haut, columns=cols, show="headings", height=8)
        for c, t, w, a in zip(cols, ("UTC", "dB", "DT", "FRÉQ.", "MESSAGE"),
                              (70, 45, 50, 60, 260), ("w", "e", "e", "e", "w")):
            tv.heading(c, text=t, anchor=a)
            tv.column(c, width=w, anchor=a, stretch=c == "msg")
        tv.tag_configure("moi", background="#3a1520", foreground="#fecaca")
        tv.tag_configure("cq", foreground="#86efac")
        tv.tag_configure("tx", foreground=C["ambre"])
        sb = ttk.Scrollbar(haut, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.bind("<Double-1>", self._double_clic_activite)
        self.tv_act = tv
        tk.Label(p.corps, text="ÉVÉNEMENTS", bg=C["panneau"], fg=C["faible"],
                 font=police(8, True)).pack(anchor="w", pady=(6, 0))
        self.journal = tk.Text(p.corps, height=4, bg=C["champ"], fg=C["doux"], relief="flat",
                               font=police(9, mono=True), state="disabled", wrap="none",
                               highlightthickness=0)
        self.journal.pack(fill="x")
        return p

    # ---------------------------------------------------------------- barre d'état
    def _barre_etat(self):
        b = tk.Frame(self, bg=C["barre"], highlightthickness=1, highlightbackground=C["bord"])
        b.pack(fill="x", side="bottom")
        self.l_etat_g = tk.Label(b, text="", bg=C["barre"], fg=C["doux"], font=police(9))
        self.l_etat_g.pack(side="left", padx=10, pady=3)
        self.l_etat_d = tk.Label(b, text="", bg=C["barre"], fg=C["doux"], font=police(9))
        self.l_etat_d.pack(side="right", padx=10)

    # ================================================================== mises à jour visuelles
    def _maj_sous_mode(self):
        for sm, p in self.p_sm.items():
            p.regler(style="actif" if sm == self.cfg["sous_mode"] else "normal")

    def _maj_parite(self):
        for i, p in enumerate(self.p_par):
            p.regler(style="actif" if i == int(self.cfg["parite"]) else "normal")

    def _maj_auto(self):
        on = bool(self.cfg["auto"])
        self.p_auto.regler(texte="Séquence auto : OUI" if on else "Séquence auto : NON",
                           style="vert" if on else "normal")

    def _maj_fa(self):
        self.l_fa.configure(text=f"{int(self.cfg['f_audio'])} Hz")
        if hasattr(self, "cv_casc"):
            self._dessiner_reperes()

    def _maj_niv_tx(self):
        self.l_niv_tx.configure(text=f"{int(self.v_niv.get() * 100):3d} %")

    def _maj_tx(self):
        if self.emission_active:
            self.p_tx.regler(texte="TX activé", style="vert")
        else:
            self.p_tx.regler(texte="TX coupé", style="normal")

    def _maj_filtres(self):
        for k, p in self.p_filtres.items():
            p.regler(style="actif" if k == self.filtre else "normal")

    def log(self, texte):
        h = time.strftime("%H:%M:%S", time.gmtime())
        self.journal.configure(state="normal")
        self.journal.insert("end", f"{h}  {texte}\n")
        n = int(self.journal.index("end-1c").split(".")[0])
        if n > 300:
            self.journal.delete("1.0", f"{n - 300}.0")
        self.journal.see("end")
        self.journal.configure(state="disabled")

    def ui(self, fn, *a):
        """Exécute fn dans le fil de l'interface (appelable depuis n'importe quel fil)."""
        self.file_ui.put((fn, a))

    def log_exc(self, ou, e):
        self.log(f"Erreur ({ou}) : {e}")

    # ================================================================== actions
    def choisir_sous_mode(self, sm):
        if self.en_cours:
            return
        self.cfg["sous_mode"] = sm
        self._maj_sous_mode()
        self._dessiner_reperes()

    def choisir_parite(self, p):
        self.cfg["parite"] = p
        self._maj_parite()

    def basculer_auto(self):
        self.cfg["auto"] = not self.cfg["auto"]
        self._maj_auto()

    def decaler_fa(self, d):
        self.cfg["f_audio"] = int(min(2700, max(300, int(self.cfg["f_audio"]) + d)))
        self._maj_fa()

    def choisir_filtre(self, k):
        self.filtre = k
        self._maj_filtres()
        self.tv_act.delete(*self.tv_act.get_children())
        for d in self.decodes:
            self._inserer_activite(d)

    def effacer_activite(self):
        self.decodes.clear()
        self.tv_act.delete(*self.tv_act.get_children())

    def _remplir(self, fn):
        c = self.cfg["indicatif"].upper()
        loc = self.cfg["locator"].upper()
        d = self.v_dx.get().strip().upper() or "F4ABC"
        try:
            r = int(self.v_rep.get())
        except (ValueError, tk.TclError):
            r = -12
        self.v_msg.set(fn(c, loc, d, r))

    def _verifier(self, texte):
        try:
            coder_message(texte)
            return True
        except ErreurMessage as e:
            messagebox.showerror("Message", str(e), parent=self)
            return False

    def activer_tx(self, on):
        if on and not self._verifier(self.v_msg.get()):
            on = False
        self.emission_active = on
        self._maj_tx()

    def basculer_tx(self):
        self.activer_tx(not self.emission_active)

    def envoyer_manuel(self):
        texte = self.v_msg.get().strip().upper()
        if not self._verifier(texte):
            return
        self.v_msg.set(texte)
        self.seq.arreter()                      # message choisi à la main : pas de séquenceur
        self.activer_tx(True)
        self.log(f"Message manuel : {texte}")

    def stop(self):
        self.emission_active = False
        self.tune = False
        self.arret.set()
        if sd is not None:
            try:
                sd.stop()
            except Exception:
                pass
        self.radio.ptt(False)
        self._maj_tx()
        self.p_tune.regler(style="normal")
        self.log("Arrêt de l'émission")

    def basculer_tune(self):
        if self.tune or self.en_cours:
            self.stop()
            return
        self.tune = True
        self.p_tune.regler(style="plein_rouge")
        self.arret.clear()
        n = int(10 * FS)
        t = np.arange(n) / FS
        a = (float(self.v_niv.get()) * np.sin(2 * np.pi * float(self.cfg["f_audio"]) * t)
             ).astype(np.float32)
        self.en_cours = True
        threading.Thread(target=self._jouer, args=(a, "porteuse (Tune)", None, True),
                         daemon=True).start()

    # ---------------------------------------------------------------- QSO automatique
    def _maj_seq(self):
        self.seq.moi = self.cfg["indicatif"].upper()
        self.seq.locator = self.cfg["locator"].upper()
        self.seq.cq_apres_qso = bool(self.cfg["cq_apres"])
        self.seq.max_rep = int(self.cfg["max_rep"])
        self.seq.max_cq = int(self.cfg["max_cq"])

    def _appliquer_seq(self, raison=""):
        if self.seq.message:
            if self.seq.message != self.v_msg.get():
                self.v_msg.set(self.seq.message)
                self.log(f"Séquence : {self.seq.message}" + (f"  ({raison})" if raison else ""))
            if not self.emission_active:
                self.activer_tx(True)
        elif self.emission_active:
            self.activer_tx(False)
            self.log("Séquence : fin d'émission" + (f" ({raison})" if raison else ""))
        if self.seq.dx:
            self.v_dx.set(self.seq.dx)
        self._enregistrer_qsos()

    def lancer_cq(self):
        self._maj_seq()
        if not self.cfg["auto"]:
            self._remplir(lambda c, l, d, r: f"CQ {c} {l}")
            self.activer_tx(True)
            return
        self.seq.lancer_cq()
        self._appliquer_seq("CQ")

    def arreter_qso(self):
        self.seq.arreter()
        self._appliquer_seq("arrêt demandé")

    def repondre(self, texte, snr, n_periode):
        mots = texte.split()
        moi = self.cfg["indicatif"].upper()
        if len(mots) < 2 or mots[1] in (moi, "<...>"):
            return
        dx = mots[1]
        self.v_dx.set(dx)
        self.v_rep.set(int(snr))
        self.cfg["parite"] = (n_periode + 1) % 2
        self._maj_parite()
        if self.cfg["auto"]:
            self._maj_seq()
            if mots[0] == moi:
                self.seq.reprendre(texte, int(snr))
            else:
                loc = mots[2] if len(mots) > 2 and _est_locator(mots[2]) else ""
                self.seq.repondre_a(dx, int(snr), loc)
            self._appliquer_seq("appel")
        else:
            self._remplir(lambda c, l, d, r: f"{d} {c} {l}")
            self.activer_tx(True)

    def _enregistrer_qsos(self):
        for q in self.seq.prendre_qsos():
            freq = None
            if self.radio.freq_hz:
                freq = (self.radio.freq_hz + float(self.cfg["f_audio"])) / 1e6
            try:
                fichier = journal_adif.enregistrer(
                    q, self.cfg["indicatif"].upper(), self.cfg["locator"].upper(), freq,
                    fichier=self.cfg["fichier_adif"], mode=self.cfg["adif_mode"],
                    sous_mode=self.cfg["adif_sous_mode"], sous_mode_tr=self.cfg["sous_mode"])
                self.nb_qso += 1
                self.contactes.add(q["call"])
                self.log(f"QSO enregistré : {q['call']} {q['grid']} envoyé {q['rst_sent']} "
                         f"reçu {q['rst_rcvd']} → {fichier}")
            except Exception as e:
                self.log(f"Erreur journal : {e}")

    # ================================================================== horloge / émission
    def _horloge(self):
        while True:
            try:
                fn, a = self.file_ui.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*a)
            except Exception as e:
                self.log(f"Erreur interface : {e}")
        maintenant = time.time()
        sm = self.cfg["sous_mode"]
        periode = SOUS_MODES[sm][0]
        n = int(maintenant // periode)
        t = maintenant - n * periode
        self.l_heure.configure(text=time.strftime("%H:%M:%S", time.gmtime(maintenant)))
        self.cv_prog.delete("all")
        coul = C["rouge"] if self.en_cours else (C["accent"] if n % 2 == int(self.cfg["parite"])
                                                  else C["vert"])
        self.cv_prog.create_rectangle(0, 0, 150 * t / periode, 8, fill=coul, outline="")
        quoi = "émission" if n % 2 == int(self.cfg["parite"]) else "écoute"
        self.l_prog.configure(text=f"{periode - t:4.1f} s · période {'paire' if n % 2 == 0 else 'impaire'}"
                                   f" ({quoi})")
        self._tic(n, t, periode)
        if (self.emission_active and not self.en_cours and n % 2 == int(self.cfg["parite"])
                and t < RETARD_MAX_TX and n != self.derniere_periode and self._peut_emettre(t)):
            self.derniere_periode = n
            self.periodes_tx.add((sm, n))
            self._lancer(n * periode)
        if self.emission_active and not self.en_cours:
            prochain = (n + (1 if n % 2 == int(self.cfg["parite"]) and t >= RETARD_MAX_TX else 0))
            if prochain % 2 != int(self.cfg["parite"]):
                prochain += 1
            self.l_prochain.configure(text=f"prochaine émission dans "
                                           f"{max(0.0, prochain * periode + DEBUT_TX - maintenant):.0f} s")
        elif self.en_cours:
            self.l_prochain.configure(text="émission en cours")
        else:
            self.l_prochain.configure(text="")
        self.p_rxtx.regler(texte="TX" if self.en_cours else "RX",
                           style="plein_rouge" if self.en_cours else "vert")
        self.after(50, self._horloge)

    def _peut_emettre(self, t):
        return not (self.cfg["auto"] and self.seq.actif() and self.decodage_en_cours
                    and t < RETARD_MAX_TX - 0.1)

    def _lancer(self, debut_periode):
        texte = self.v_msg.get().strip().upper()
        try:
            audio = moduler(texte, self.cfg["sous_mode"], float(self.cfg["f_audio"]),
                            float(self.v_niv.get()))
        except Exception as e:
            self.activer_tx(False)
            messagebox.showerror("Message", str(e), parent=self)
            return
        self.en_cours = True
        self.arret.clear()
        self._ajouter_tx(texte)
        threading.Thread(target=self._jouer, args=(audio, texte, debut_periode, False),
                         daemon=True).start()

    def _index_sortie(self):
        for i, n in appareils_audio(False):
            if n == self.cfg["sortie_son"]:
                return i
        return None

    def _jouer(self, audio, texte, debut_periode, est_tune):
        try:
            self.radio.ptt(True)
            if debut_periode is not None:
                attente = debut_periode + DEBUT_TX - time.time()
                if attente > 0:
                    time.sleep(attente)
            if self.arret.is_set():
                return
            self.ui(self.log, f"TX  {texte}")
            if sd is None:
                fin = time.time() + audio.size / FS
                while time.time() < fin and not self.arret.is_set():
                    time.sleep(0.05)
            else:
                idx = self._index_sortie()
                canaux = 1
                try:
                    if idx is not None and sd.query_devices(idx)["max_output_channels"] >= 2:
                        canaux = 2
                except Exception:
                    pass
                sd.play(np.repeat(audio[:, None], canaux, 1), FS, device=idx)
                sd.wait()
        except Exception as e:
            self.ui(self.log, f"Erreur émission : {e}")
            self.ui(self.activer_tx, False)
        finally:
            self.radio.ptt(False)
            self.en_cours = False
            interrompue = self.arret.is_set()
            if est_tune:
                self.tune = False
                self.ui(self.p_tune.regler, None, "normal")
            else:
                self.ui(self._fin_emission, interrompue)

    def _fin_emission(self, interrompue):
        if interrompue:
            self.seq.arreter()
            return
        if self.cfg["auto"] and self.seq.actif():
            self._maj_seq()
            self.seq.apres_emission()
            raison = ""
            if not self.seq.actif():
                raison = "QSO terminé" if self.seq.qsos_finis else "pas de réponse"
            self._appliquer_seq(raison)
        else:
            self._enregistrer_qsos()

    # ================================================================== réception
    def _demarrer_capture(self):
        if sd is None:
            return
        if self.flux is not None:
            try:
                self.flux.stop()
                self.flux.close()
            except Exception:
                pass
            self.flux = None
        entrees = appareils_audio(True)
        nom = choisir_appareil(entrees, self.cfg["entree_son"])
        self.cfg["entree_son"] = nom
        idx = next((i for i, n in entrees if n == nom), None)
        if not self.cfg["sortie_son"]:
            self.cfg["sortie_son"] = choisir_appareil(appareils_audio(False), "")

        def rappel(indata, frames, temps, statut):
            bloc = indata[:, 0].astype(np.float32)
            self.tampon.ajouter(bloc, time.time())
            self.niveau_entree = float(np.sqrt(np.mean(bloc ** 2)) + 1e-9)

        try:
            self.flux = sd.InputStream(device=idx, samplerate=FS, channels=1, blocksize=2400,
                                       callback=rappel)
            self.flux.start()
            self.log(f"Réception : {nom}")
        except Exception as e:
            self.log(f"Erreur entrée son ({nom}) : {e}")

    def _tic(self, n, t, periode):
        sm = self.cfg["sous_mode"]
        seuil = min(DEBUT_TX + duree_tx(sm) + PLAGE_DT[1] + 0.05, periode)
        if t >= seuil:
            cible = n
        elif t < 0.5:
            cible = n - 1
        else:
            return
        if (sm, cible) == self.derniere_decodee or self.decodage_en_cours:
            return
        self.derniere_decodee = (sm, cible)
        if (sm, cible) in self.periodes_tx:
            return
        audio = self.tampon.extraire(cible * periode, periode)
        if audio is None:
            return
        self.decodage_en_cours = True
        moi = self.cfg["indicatif"].upper()
        if moi:
            self.carnet[hash21(moi)] = moi
        threading.Thread(target=self._decoder, args=(audio, sm, cible, periode),
                         daemon=True).start()

    def _decoder(self, audio, sm, n, periode):
        t0 = time.time()
        try:
            res = decoder_periode(audio, sm, dict(self.carnet))
        except Exception as e:
            res = []
            self.ui(self.log, f"Erreur décodage : {e}")
        self.ui(self._afficher, res, n, periode, time.time() - t0)

    def _afficher(self, res, n, periode, duree):
        self.decodage_en_cours = False
        heure = time.strftime("%H%M%S", time.gmtime(n * periode))
        moi = self.cfg["indicatif"].upper()
        maintenant = time.time()
        for r in res:
            mots = r["texte"].split()
            for m in mots[:2]:
                if m not in ("CQ", "QRZ", "DE", "<...>"):
                    self.carnet[hash21(m)] = m
            d = dict(r, utc=heure, n=n, moi=bool(mots and mots[0] == moi),
                     cq=bool(mots and mots[0] == "CQ"), tx=False)
            self.decodes.append(d)
            self._inserer_activite(d)
            if len(mots) >= 2 and mots[1] not in ("<...>",):
                self._maj_station(mots, r, maintenant)
                self.etiquettes_casc.append((r["f"], mots[1], maintenant, d["moi"]))
        self.decodes = self.decodes[-1000:]
        self.etiquettes_casc = [e for e in self.etiquettes_casc if maintenant - e[2] < 300]
        self._dessiner_reperes()
        self._remplir_stations()
        self.dernier_decodage = f"● {len(res)} décodé{'s' if len(res) > 1 else ''} · {duree:.1f} s"
        self.l_sync.configure(text=self.dernier_decodage,
                              fg=C["vert"] if res else C["doux"])
        if self.cfg["auto"] and self.seq.actif():
            self._maj_seq()
            if self.seq.traiter(res):
                if self.seq.etat != "cq" and self.seq.dx:
                    self.cfg["parite"] = (n + 1) % 2
                    self._maj_parite()
                self._appliquer_seq("réponse reçue")

    def _inserer_activite(self, d):
        if self.filtre == "cq" and not d["cq"]:
            return
        if self.filtre == "moi" and not (d["moi"] or d["tx"]):
            return
        tag = ("tx",) if d["tx"] else ("moi",) if d["moi"] else ("cq",) if d["cq"] else ()
        if d["tx"]:
            vals = (d["utc"], "TX", "", f"{d['f']:.0f}", d["texte"])
        else:
            vals = (d["utc"], f"{d['snr']:+d}", f"{d['dt']:+.1f}", f"{d['f']:.0f}", d["texte"])
        it = self.tv_act.insert("", "end", values=vals, tags=tag)
        self.tv_act.see(it)

    def _ajouter_tx(self, texte):
        d = {"utc": time.strftime("%H%M%S", time.gmtime()), "texte": texte, "tx": True,
             "f": float(self.cfg["f_audio"]), "moi": False, "cq": False, "snr": 0, "dt": 0, "n": 0}
        self.decodes.append(d)
        self._inserer_activite(d)

    def _maj_station(self, mots, r, t):
        ind = mots[1]
        s = self.stations.setdefault(ind, {"loc": "", "appelle": "", "snr": 0, "t": t,
                                           "f": r["f"], "n": 0})
        s.update(appelle=mots[0], snr=r["snr"], t=t, f=r["f"], n=r.get("n", 0))
        if len(mots) >= 3 and _est_locator(mots[2]):
            if len(mots[2]) >= len(s["loc"]):
                s["loc"] = mots[2]

    def _remplir_stations(self):
        tv = self.tv_st
        tv.delete(*tv.get_children())
        moi = self.cfg["indicatif"].upper()
        maintenant = time.time()
        for ind, s in sorted(self.stations.items(), key=lambda kv: -kv[1]["t"]):
            if maintenant - s["t"] > 3600:
                continue
            km, cap = distance_cap(self.cfg["locator"], s["loc"])
            tag = ("moi",) if s["appelle"] == moi else ("contacte",) if ind in self.contactes \
                else ("cq",) if s["appelle"] == "CQ" else ()
            tv.insert("", "end", iid=ind, tags=tag, values=(
                ind, s["appelle"], s["loc"] or "—", f"{km:.0f} km" if km is not None else "—",
                f"{cap:.0f}°" if cap is not None else "—", f"{s['snr']:+d}",
                age_texte(maintenant - s["t"])))
        self.l_nb_st.configure(text=str(len(tv.get_children())))

    def _rafraichir_ages(self):
        if self.stations:
            self._remplir_stations()
        self._dessiner_reperes()
        self.after(5000, self._rafraichir_ages)

    def _double_clic_activite(self, ev):
        it = self.tv_act.focus()
        if not it:
            return
        utc, db, dt, freq, texte = self.tv_act.item(it, "values")
        if db == "TX":
            return
        d = next((x for x in reversed(self.decodes) if x["texte"] == texte and not x["tx"]), None)
        if d:
            self.repondre(texte, d["snr"], d["n"])

    def _double_clic_station(self, ev):
        ind = self.tv_st.focus()
        if not ind:
            return
        d = next((x for x in reversed(self.decodes)
                  if not x["tx"] and len(x["texte"].split()) >= 2
                  and x["texte"].split()[1] == ind), None)
        if d:
            self.repondre(d["texte"], d["snr"], d["n"])

    # ================================================================== rafraîchissements
    def _rafraichir_cascade(self):
        try:
            x = self.tampon.derniers(16384)
            if x is not None:
                spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
                f = np.fft.rfftfreq(x.size, 1 / FS)
                bords = np.linspace(CASC_FMIN, CASC_FMAX, self.casc_l + 1)
                idx = np.searchsorted(f, bords)
                idx = np.minimum(idx, f.size - 1)
                ligne = np.maximum.reduceat(spec, idx[:-1])
                db = 10 * np.log10(ligne + 1e-20)
                ref = np.median(db)
                val = np.clip((db - ref + 2) * float(self.v_contraste.get()), 0, 255)
                self.casc = np.roll(self.casc, 1, axis=0)
                self.casc[0] = val.astype(np.uint8)
                pal = self.degrade
                donnees = " ".join("{" + " ".join(pal[v] for v in row) + "}" for row in self.casc)
                self.img_casc.put(donnees, to=(0, 0))
            niv = 20 * np.log10(self.niveau_entree)
            self.cv_niv.delete("all")
            u = min(1.0, max(0.0, (niv + 60) / 60))
            coul = C["vert"] if niv < -12 else C["ambre"] if niv < -4 else C["rouge"]
            self.cv_niv.create_rectangle(0, 0, 140 * u, 8, fill=coul, outline="")
            self.l_niv.configure(text=f"{niv:5.0f} dB" if niv > -150 else "  — dB")
        except (tk.TclError, ValueError):
            pass
        self.after(250, self._rafraichir_cascade)

    def _rafraichir_etat(self):
        r = self.radio
        e = radio.rig_entry(self.cfg["radio"].get("rig", "none"))
        nom = e.get("model") or e["label"].split(" — ")[0]
        self.l_poste.configure(text=nom[:26])
        ok = r.ok
        self.l_poste_etat.configure(text=("● " if ok else "● ") + (r.etat[:48] or ""),
                                    fg=C["vert"] if ok else C["rouge"])
        if r.freq_hz:
            mhz = r.freq_hz / 1e6
            self.l_freq.configure(text=f"{mhz:8.3f} {int(r.freq_hz % 1000):03d}".replace(" ", " "))
            self.l_bande.configure(text=journal_adif.bande(mhz) or "?")
        self.l_ind.configure(text=self.cfg["indicatif"].upper())
        self.l_loc.configure(text=self.cfg["locator"].upper())
        etat = self.seq.libelle() if self.cfg["auto"] else "séquence manuelle"
        self.l_qso.configure(text=f"QSO : {etat}")
        self.l_etat_g.configure(text=f"{self.nb_qso} QSO cette session  ·  journal : "
                                     f"{os.path.basename(self.cfg['fichier_adif'])}")
        court = lambda n: (n or "—").split("  [")[0][:34]
        self.l_etat_d.configure(text=f"Entrée : {court(self.cfg['entree_son'])}   ·   "
                                     f"Sortie : {court(self.cfg['sortie_son'])}")
        self.after(400, self._rafraichir_etat)

    # ================================================================== réglages
    def ouvrir_reglages(self, onglet=None):
        from reglages import FenetreReglages
        FenetreReglages(self, onglet)

    # appelés par la fenêtre « Poste radio » (reprise de HFImage)
    @property
    def radio_cfg(self):
        return self.cfg["radio"]

    @property
    def tx_busy(self):
        return self.en_cours

    def rig_hold(self):
        return self.radio.tenir()

    def _translate_ui(self, fenetre):
        """Traduction des fenêtres reprises de HFImage : le programme est en français."""

    def set_radio(self, cfg):
        self.cfg["radio"] = dict(cfg)
        self.radio.configurer(self.cfg["radio"])
        self.sauver()
        self.log("Poste radio : " + radio.describe(self.cfg["radio"]))

    def appliquer_reglages(self, nouveaux):
        ancien_entree = self.cfg["entree_son"]
        self.cfg.update(nouveaux)
        self._maj_seq()
        self._maj_auto()
        self._maj_fa()
        self._maj_sous_mode()
        self._maj_parite()
        if self.cfg["entree_son"] != ancien_entree:
            self._demarrer_capture()
        self.sauver()

    def sauver(self):
        self.cfg["niveau"] = float(self.v_niv.get())
        self.cfg["contraste"] = float(self.v_contraste.get())
        try:
            with open(FICHIER_REGLAGES, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=1, ensure_ascii=False)
        except Exception as e:
            self.log(f"Réglages non enregistrés : {e}")

    def quitter(self):
        self.stop()
        self.sauver()
        if self.flux is not None:
            try:
                self.flux.stop()
                self.flux.close()
            except Exception:
                pass
        self.radio.fermer()
        self.destroy()


def main():
    Application().mainloop()


if __name__ == "__main__":
    main()
