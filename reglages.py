# -*- coding: utf-8 -*-
"""Fenêtre « Réglages » de F4GOP VHF : station, poste radio, audio, QSO automatique, journal."""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import radio
from sequenceur import _est_locator
from theme_vhf import C, Pilule, police, curseur

SECTIONS = [("station", "Station"), ("poste", "Poste radio"), ("audio", "Audio"),
            ("qso", "QSO automatique"), ("journal", "Journal ADIF")]


class FenetreReglages(tk.Toplevel):
    def __init__(self, app, onglet=None):
        super().__init__(app)
        self.app = app
        self.title("Réglages — F4GOP VHF")
        self.configure(bg=C["fond"])
        self.transient(app)
        self.geometry("820x560")
        self.minsize(760, 520)
        cfg = app.cfg
        self.v = {
            "indicatif": tk.StringVar(value=cfg["indicatif"]),
            "locator": tk.StringVar(value=cfg["locator"]),
            "entree_son": tk.StringVar(value=cfg["entree_son"]),
            "sortie_son": tk.StringVar(value=cfg["sortie_son"]),
            "auto": tk.BooleanVar(value=bool(cfg["auto"])),
            "cq_apres": tk.BooleanVar(value=bool(cfg["cq_apres"])),
            "max_rep": tk.IntVar(value=int(cfg["max_rep"])),
            "max_cq": tk.IntVar(value=int(cfg["max_cq"])),
            "f_audio": tk.IntVar(value=int(cfg["f_audio"])),
            "fichier_adif": tk.StringVar(value=cfg["fichier_adif"]),
            "adif_mode": tk.StringVar(value=cfg["adif_mode"]),
            "adif_sous_mode": tk.StringVar(value=cfg["adif_sous_mode"]),
            "verif_maj": tk.BooleanVar(value=bool(cfg.get("verif_maj", True))),
        }

        # ---- navigation à gauche
        nav = tk.Frame(self, bg=C["barre"], width=190, highlightthickness=1,
                       highlightbackground=C["bord"])
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Label(nav, text="RÉGLAGES", bg=C["barre"], fg=C["accent"],
                 font=police(12, True)).pack(anchor="w", padx=16, pady=(16, 12))
        self.boutons = {}
        for cle, nom in SECTIONS:
            b = tk.Label(nav, text=nom, bg=C["barre"], fg=C["doux"], font=police(10, True),
                         anchor="w", padx=16, pady=8, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=cle: self.montrer(k))
            self.boutons[cle] = b

        droite = tk.Frame(self, bg=C["fond"])
        droite.pack(side="left", fill="both", expand=True)
        self.zone = tk.Frame(droite, bg=C["fond"])
        self.zone.pack(fill="both", expand=True, padx=22, pady=18)
        bas = tk.Frame(droite, bg=C["fond"])
        bas.pack(fill="x", padx=22, pady=(0, 16))
        Pilule(bas, "Enregistrer", self.enregistrer, style="accent").pack(side="right")
        Pilule(bas, "Annuler", self.destroy).pack(side="right", padx=8)

        self.pages = {}
        for cle, _ in SECTIONS:
            f = tk.Frame(self.zone, bg=C["fond"])
            getattr(self, f"_page_{cle}")(f)
            self.pages[cle] = f
        self.montrer(onglet or "station")
        self._suivre_poste()

    # ------------------------------------------------------------ outils
    def montrer(self, cle):
        for k, f in self.pages.items():
            f.pack_forget()
            self.boutons[k].configure(bg=C["barre"], fg=C["doux"])
        self.pages[cle].pack(fill="both", expand=True)
        self.boutons[cle].configure(bg=C["accent_fond"], fg=C["accent"])

    @staticmethod
    def _titre(f, texte, aide=""):
        tk.Label(f, text=texte, bg=C["fond"], fg=C["texte"], font=police(15, True)).pack(
            anchor="w")
        if aide:
            tk.Label(f, text=aide, bg=C["fond"], fg=C["doux"], font=police(9), justify="left",
                     wraplength=560).pack(anchor="w", pady=(2, 12))

    @staticmethod
    def _ligne(f, libelle, widget_fn, aide=""):
        l = tk.Frame(f, bg=C["fond"])
        l.pack(fill="x", pady=5)
        tk.Label(l, text=libelle, bg=C["fond"], fg=C["texte"], width=24, anchor="w",
                 font=police(10)).pack(side="left")
        w = widget_fn(l)
        w.pack(side="left")
        if aide:
            tk.Label(l, text=aide, bg=C["fond"], fg=C["faible"], font=police(9)).pack(
                side="left", padx=8)
        return w

    # ------------------------------------------------------------ pages
    def _page_station(self, f):
        self._titre(f, "Station", "Ton indicatif et ton locator (4 ou 6 caractères) : ils sont "
                                  "envoyés dans les CQ et servent à calculer distance et cap "
                                  "des stations reçues.")
        self._ligne(f, "Indicatif", lambda p: ttk.Entry(p, textvariable=self.v["indicatif"],
                                                        width=12, font=police(11, True, True)))
        self._ligne(f, "Locator", lambda p: ttk.Entry(p, textvariable=self.v["locator"], width=8,
                                                      font=police(11, True, True)),
                    "ex. IN98QR")
        tk.Label(f, text="Indicatifs « standard » de 3 à 6 caractères (pas encore de /P ni de "
                         "préfixe F/ON4ABC).", bg=C["fond"], fg=C["faible"],
                 font=police(9)).pack(anchor="w", pady=(14, 0))
        from f4gop_vhf import VERSION
        cadre = tk.Frame(f, bg=C["panneau"], highlightthickness=1, highlightbackground=C["bord"])
        cadre.pack(fill="x", pady=(24, 0))
        tk.Label(cadre, text="MISE À JOUR AUTOMATIQUE", bg=C["panneau"], fg=C["faible"],
                 font=police(8, True)).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(cadre, text=f"Version installée : {VERSION}", bg=C["panneau"], fg=C["texte"],
                 font=police(10)).pack(anchor="w", padx=12)
        l = tk.Frame(cadre, bg=C["panneau"])
        l.pack(fill="x", padx=12, pady=(6, 10))
        tk.Checkbutton(l, text="Vérifier au démarrage (puis toutes les 3 heures)",
                       variable=self.v["verif_maj"], bg=C["panneau"], fg=C["texte"],
                       selectcolor=C["champ"], activebackground=C["panneau"],
                       activeforeground=C["texte"], highlightthickness=0, bd=0,
                       font=police(10)).pack(side="left")
        Pilule(l, "Vérifier maintenant", lambda: self.app.verifier_maj(silencieux=False),
               fond_parent=C["panneau"]).pack(side="right")

    def _page_poste(self, f):
        self._titre(f, "Poste radio", "Tous les postes connus de Hamlib, plus les Icom VHF/UHF "
                                      "en CI-V direct (sans rien installer), Kenwood en direct, "
                                      "FLRig, OmniRig, SunSDR (TCI)… La fenêtre de choix est "
                                      "celle de HFImage, avec en plus la case « Postes VHF/UHF "
                                      "seulement ».")
        cadre = tk.Frame(f, bg=C["panneau"], highlightthickness=1, highlightbackground=C["bord"])
        cadre.pack(fill="x", pady=(4, 10))
        tk.Label(cadre, text="POSTE ACTUEL", bg=C["panneau"], fg=C["faible"],
                 font=police(8, True)).pack(anchor="w", padx=12, pady=(10, 0))
        self.l_poste = tk.Label(cadre, text="", bg=C["panneau"], fg=C["accent"],
                                font=police(11, True), justify="left", wraplength=540)
        self.l_poste.pack(anchor="w", padx=12, pady=(2, 2))
        self.l_liaison = tk.Label(cadre, text="", bg=C["panneau"], fg=C["doux"], font=police(9),
                                  justify="left", wraplength=540)
        self.l_liaison.pack(anchor="w", padx=12, pady=(0, 10))
        Pilule(f, "Choisir et régler le poste…", self.ouvrir_poste, style="accent").pack(
            anchor="w")
        aide = ("IC-9700 : choisir « Icom IC-9700 — CI-V direct », le port COM marqué "
                "« Enhanced », 115200 bauds, PTT par CAT. Sur le poste (Menu > Set > Connectors) : "
                "CI-V USB Port = Unlink from [REMOTE], CI-V USB Baud Rate = 115200, "
                "CI-V Address = A2h, DATA MOD = USB, et le poste en USB-D.")
        tk.Label(f, text=aide, bg=C["fond"], fg=C["faible"], font=police(9), justify="left",
                 wraplength=560).pack(anchor="w", pady=(14, 0))

    def _page_audio(self, f):
        from f4gop_vhf import appareils_audio
        self._titre(f, "Audio", "Carte son du poste : « USB Audio CODEC » pour l'IC-9700 "
                                "(entrée = réception, sortie = émission).")
        self.cb_entree = self._ligne(f, "Entrée (réception)", lambda p: ttk.Combobox(
            p, textvariable=self.v["entree_son"], width=46, state="readonly",
            values=[n for _, n in appareils_audio(True)]))
        self.cb_sortie = self._ligne(f, "Sortie (émission)", lambda p: ttk.Combobox(
            p, textvariable=self.v["sortie_son"], width=46, state="readonly",
            values=[n for _, n in appareils_audio(False)]))
        Pilule(f, "Actualiser la liste", self._actualiser_audio).pack(anchor="w", pady=(6, 0))
        self._ligne(f, "Niveau de sortie", lambda p: curseur(p, self.app.v_niv, 0.02, 1.0, 240),
            "régler pour que l'ALC ne bouge pas")

    def _actualiser_audio(self):
        from f4gop_vhf import appareils_audio, sd
        if sd is not None:
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
        self.cb_entree.configure(values=[n for _, n in appareils_audio(True)])
        self.cb_sortie.configure(values=[n for _, n in appareils_audio(False)])

    def _page_qso(self, f):
        self._titre(f, "QSO automatique", "Le séquenceur enchaîne tout seul locator, report, "
                                          "R-report, RR73 et 73, et enregistre le QSO.")
        self._ligne(f, "Séquence automatique", lambda p: ttk.Checkbutton(
            p, variable=self.v["auto"]))
        self._ligne(f, "Relancer CQ après un QSO", lambda p: ttk.Checkbutton(
            p, variable=self.v["cq_apres"]))
        self._ligne(f, "Répétitions sans réponse", lambda p: ttk.Spinbox(
            p, from_=2, to=20, width=5, textvariable=self.v["max_rep"]),
            "avant d'abandonner un QSO")
        self._ligne(f, "Nombre de CQ maximum", lambda p: ttk.Spinbox(
            p, from_=1, to=200, width=5, textvariable=self.v["max_cq"]),
            "puis l'émission s'arrête (1 = un seul CQ)")
        self._ligne(f, "Fréquence audio TX (Hz)", lambda p: ttk.Spinbox(
            p, from_=300, to=2700, increment=10, width=6, textvariable=self.v["f_audio"]))

    def _page_journal(self, f):
        self._titre(f, "Journal ADIF", "Chaque QSO terminé est ajouté à ce fichier, importable "
                                       "dans ton logiciel de trafic.")
        l = tk.Frame(f, bg=C["fond"])
        l.pack(fill="x", pady=5)
        tk.Label(l, text="Fichier", bg=C["fond"], fg=C["texte"], width=24, anchor="w").pack(
            side="left")
        ttk.Entry(l, textvariable=self.v["fichier_adif"], width=44).pack(side="left")
        Pilule(l, "Choisir…", self._choisir_fichier, hauteur=26).pack(side="left", padx=6)
        Pilule(f, "Ouvrir le dossier du journal", self._ouvrir_dossier).pack(anchor="w",
                                                                              pady=(4, 10))
        self._ligne(f, "MODE ADIF", lambda p: ttk.Entry(p, textvariable=self.v["adif_mode"],
                                                        width=12))
        self._ligne(f, "SUBMODE ADIF", lambda p: ttk.Entry(
            p, textvariable=self.v["adif_sous_mode"], width=16))
        tk.Label(f, text="Ce mode est nouveau : il n'existe pas encore dans la liste officielle "
                         "ADIF. Par défaut MFSK / F4GOP-VHF ; LoTW peut refuser un sous-mode "
                         "inconnu.", bg=C["fond"], fg=C["faible"], font=police(9),
                 justify="left", wraplength=560).pack(anchor="w", pady=(10, 0))

    # ------------------------------------------------------------ actions
    def _choisir_fichier(self):
        p = filedialog.asksaveasfilename(parent=self, defaultextension=".adi",
                                         filetypes=[("Journal ADIF", "*.adi *.adif")],
                                         initialfile=os.path.basename(self.v["fichier_adif"].get()))
        if p:
            self.v["fichier_adif"].set(p)

    def _ouvrir_dossier(self):
        d = os.path.dirname(self.v["fichier_adif"].get())
        os.makedirs(d, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(d)
        else:
            subprocess.Popen(["xdg-open", d])

    def ouvrir_poste(self):
        from radiodlg import RadioDialog
        try:
            RadioDialog(self.app)
        except Exception as e:
            messagebox.showerror("Poste radio", f"Impossible d'ouvrir la fenêtre : {e}",
                                 parent=self)

    def _suivre_poste(self):
        if not self.winfo_exists():
            return
        self.l_poste.configure(text=radio.describe(self.app.cfg["radio"]))
        r = self.app.radio
        self.l_liaison.configure(text=("● " + r.etat), fg=C["vert"] if r.ok else C["rouge"])
        self.after(500, self._suivre_poste)

    def enregistrer(self):
        ind = self.v["indicatif"].get().strip().upper()
        loc = self.v["locator"].get().strip().upper()
        if not (3 <= len(ind) <= 6) or not any(c.isdigit() for c in ind):
            messagebox.showerror("Réglages", "Indicatif : 3 à 6 caractères avec un chiffre.",
                                 parent=self)
            return
        if not _est_locator(loc):
            messagebox.showerror("Réglages", "Locator : 4 ou 6 caractères, par exemple IN98QR.",
                                 parent=self)
            return
        try:
            nouveaux = {
                "indicatif": ind, "locator": loc,
                "entree_son": self.v["entree_son"].get(),
                "sortie_son": self.v["sortie_son"].get(),
                "auto": bool(self.v["auto"].get()), "cq_apres": bool(self.v["cq_apres"].get()),
                "max_rep": int(self.v["max_rep"].get()), "max_cq": int(self.v["max_cq"].get()),
                "f_audio": min(2700, max(300, int(self.v["f_audio"].get()))),
                "fichier_adif": self.v["fichier_adif"].get().strip(),
                "adif_mode": self.v["adif_mode"].get().strip() or "MFSK",
                "adif_sous_mode": self.v["adif_sous_mode"].get().strip(),
                "verif_maj": bool(self.v["verif_maj"].get()),
            }
        except (ValueError, tk.TclError):
            messagebox.showerror("Réglages", "Un nombre n'est pas valide.", parent=self)
            return
        self.app.appliquer_reglages(nouveaux)
        self.destroy()
