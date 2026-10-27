# -*- coding: utf-8 -*-
"""
Thème sombre moderne de F4GOP VHF : couleurs, polices, style ttk, et petits
éléments graphiques (boutons « pilules » arrondis, panneaux à en-tête, badges).
"""
import sys
import tkinter as tk
from tkinter import ttk

C = {
    "fond": "#0a0e16",        # fond de la fenêtre
    "barre": "#0f1522",       # barre du haut
    "panneau": "#111827",     # panneaux
    "panneau2": "#162033",    # zones dans les panneaux
    "champ": "#0c1220",       # champs de saisie, tableaux
    "bord": "#24324b",
    "texte": "#e6edf7",
    "doux": "#8b98ae",
    "faible": "#5b6880",
    "accent": "#38bdf8",      # cyan
    "accent_fond": "#0c3550",
    "vert": "#22c55e",
    "vert_fond": "#0d3320",
    "rouge": "#ef4444",
    "rouge_fond": "#3a1216",
    "ambre": "#f59e0b",
    "violet": "#a78bfa",
    "pilule": "#1a2436",
    "pilule_survol": "#22304a",
    "selection": "#1d3b5c",
}

if sys.platform.startswith("win"):
    POLICE, MONO = "Segoe UI", "Consolas"
else:
    POLICE, MONO = "DejaVu Sans", "DejaVu Sans Mono"


def _choisir_polices(racine):
    """Hors Windows : Inter si elle est installée, sinon DejaVu Sans."""
    global POLICE
    if sys.platform.startswith("win"):
        return
    try:
        import tkinter.font as tkfont
        familles = set(tkfont.families(racine))
        for f in ("Inter", "Noto Sans", "DejaVu Sans"):
            if f in familles:
                POLICE = f
                break
    except Exception:
        pass


def police(taille=10, gras=False, mono=False):
    return (MONO if mono else POLICE, taille, "bold" if gras else "normal")


def appliquer(racine):
    """Style ttk sombre pour toute l'application (fenêtres de réglages comprises)."""
    racine.configure(bg=C["fond"])
    _choisir_polices(racine)
    st = ttk.Style(racine)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    racine.option_add("*Font", police(10))
    racine.option_add("*TCombobox*Listbox.background", C["champ"])
    racine.option_add("*TCombobox*Listbox.foreground", C["texte"])
    racine.option_add("*TCombobox*Listbox.selectBackground", C["selection"])
    racine.option_add("*TCombobox*Listbox.selectForeground", C["texte"])
    # fenêtres tk classiques (boîtes de la fenêtre Poste radio de HFImage)
    for cle, val in (("*Toplevel.background", C["fond"]), ("*Button.background", C["pilule"]),
                     ("*Button.foreground", C["texte"]), ("*Button.activeBackground", C["pilule_survol"]),
                     ("*Button.activeForeground", C["texte"]), ("*Button.relief", "flat"),
                     ("*Button.highlightThickness", 0), ("*Label.background", C["fond"]),
                     ("*Label.foreground", C["texte"])):
        racine.option_add(cle, val)
    st.configure(".", background=C["fond"], foreground=C["texte"], fieldbackground=C["champ"],
                 bordercolor=C["bord"], lightcolor=C["bord"], darkcolor=C["bord"],
                 troughcolor=C["champ"], selectbackground=C["selection"],
                 selectforeground=C["texte"], insertcolor=C["texte"], font=police(10))
    st.configure("TFrame", background=C["fond"])
    st.configure("Panneau.TFrame", background=C["panneau"])
    st.configure("TLabel", background=C["fond"], foreground=C["texte"])
    st.map("TLabel", background=[("disabled", C["fond"])], foreground=[("disabled", C["faible"])])
    st.map("TRadiobutton", foreground=[("disabled", C["faible"])],
           indicatorbackground=[("disabled", C["panneau"])])
    st.configure("Panneau.TLabel", background=C["panneau"])
    st.configure("Doux.TLabel", foreground=C["doux"])
    st.configure("TLabelframe", background=C["fond"], bordercolor=C["bord"], relief="solid")
    st.configure("TLabelframe.Label", background=C["fond"], foreground=C["accent"],
                 font=police(10, True))
    st.configure("TButton", background=C["pilule"], foreground=C["texte"], borderwidth=0,
                 focusthickness=0, padding=(10, 4))
    st.map("TButton", background=[("active", C["pilule_survol"]), ("disabled", C["panneau"])],
           foreground=[("disabled", C["faible"])])
    st.configure("Accent.TButton", background=C["accent"], foreground="#04121c")
    st.map("Accent.TButton", background=[("active", "#7dd3fc")])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(w, fieldbackground=C["champ"], foreground=C["texte"], background=C["pilule"],
                     arrowcolor=C["doux"], bordercolor=C["bord"], padding=3)
        st.map(w, fieldbackground=[("readonly", C["champ"]), ("disabled", C["panneau"])],
               foreground=[("disabled", C["faible"])], bordercolor=[("focus", C["accent"])])
    st.configure("TCheckbutton", background=C["fond"], foreground=C["texte"],
                 indicatorbackground=C["champ"], indicatorforeground=C["accent"])
    st.map("TCheckbutton", background=[("active", C["fond"])],
           indicatorbackground=[("selected", C["accent_fond"])])
    st.configure("TRadiobutton", background=C["fond"], foreground=C["texte"],
                 indicatorbackground=C["champ"], indicatorforeground=C["accent"])
    st.map("TRadiobutton", background=[("active", C["fond"]), ("disabled", C["fond"])],
           foreground=[("disabled", C["faible"])], indicatorbackground=[("disabled", C["panneau"])])
    st.configure("Treeview", background=C["champ"], fieldbackground=C["champ"],
                 foreground=C["texte"], bordercolor=C["bord"], rowheight=24, font=police(10, mono=True))
    st.map("Treeview", background=[("selected", C["selection"])],
           foreground=[("selected", C["texte"])])
    st.configure("Treeview.Heading", background=C["panneau2"], foreground=C["doux"],
                 relief="flat", font=police(9, True), padding=(4, 4))
    st.map("Treeview.Heading", background=[("active", C["pilule_survol"])])
    st.configure("Vertical.TScrollbar", background=C["pilule"], troughcolor=C["champ"],
                 arrowcolor=C["doux"], bordercolor=C["champ"])
    st.configure("Horizontal.TScale", background=C["accent"], troughcolor=C["pilule"])
    st.configure("TNotebook", background=C["fond"], bordercolor=C["bord"])
    st.configure("TNotebook.Tab", background=C["pilule"], foreground=C["doux"], padding=(12, 5))
    st.map("TNotebook.Tab", background=[("selected", C["panneau2"])],
           foreground=[("selected", C["accent"])])
    st.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor=C["pilule"])


def _arrondi(cv, x0, y0, x1, y1, r, **kw):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


STYLES_PILULE = {
    #             fond, texte, bord, fond survol
    "normal": (C["pilule"], C["texte"], C["bord"], C["pilule_survol"]),
    "accent": (C["accent"], "#04121c", C["accent"], "#7dd3fc"),
    "actif": (C["accent_fond"], C["accent"], C["accent"], "#114766"),
    "vert": (C["vert_fond"], C["vert"], C["vert"], "#11452b"),
    "rouge": (C["rouge_fond"], C["rouge"], C["rouge"], "#4e161b"),
    "plein_rouge": (C["rouge"], "#ffffff", C["rouge"], "#f87171"),
    "plein_vert": (C["vert"], "#04150b", C["vert"], "#4ade80"),
    "fantome": (C["panneau"], C["doux"], C["panneau"], C["pilule"]),
}


class Pilule(tk.Canvas):
    """Bouton arrondi. style : normal, accent, actif, vert, rouge, plein_rouge, plein_vert."""

    def __init__(self, parent, texte, commande=None, style="normal", taille=10, gras=True,
                 largeur=None, hauteur=28, fond_parent=None, **kw):
        self._fp = fond_parent or C["fond"]
        super().__init__(parent, height=hauteur, bg=self._fp, highlightthickness=0, bd=0, **kw)
        self._texte, self._cmd, self._style = texte, commande, style
        self._police = police(taille, gras)
        self._h = hauteur
        self._largeur_fixe = largeur
        self._survol = False
        self._actif_ok = True
        self.bind("<Enter>", lambda e: self._sur(True))
        self.bind("<Leave>", lambda e: self._sur(False))
        self.bind("<Button-1>", self._clic)
        self._dessiner()

    def _sur(self, v):
        self._survol = v
        self._dessiner()

    def _clic(self, e):
        if self._cmd and self._actif_ok:
            self._cmd()

    def regler(self, texte=None, style=None, commande=None, actif=None):
        if texte is not None:
            self._texte = texte
        if style is not None:
            self._style = style
        if commande is not None:
            self._cmd = commande
        if actif is not None:
            self._actif_ok = actif
        self._dessiner()

    def _dessiner(self):
        self.delete("all")
        fond, texte, bord, survol = STYLES_PILULE.get(self._style, STYLES_PILULE["normal"])
        if not self._actif_ok:
            fond, texte, bord, survol = C["panneau"], C["faible"], C["bord"], C["panneau"]
        tmp = self.create_text(0, 0, text=self._texte, font=self._police, anchor="nw")
        x0, y0, x1, y1 = self.bbox(tmp)
        self.delete(tmp)
        w = self._largeur_fixe or (x1 - x0 + 26)
        self.configure(width=w)
        h = self._h
        _arrondi(self, 1, 1, w - 1, h - 1, h / 2, fill=survol if self._survol else fond,
                 outline=bord)
        self.create_text(w / 2, h / 2, text=self._texte, font=self._police, fill=texte)


class Panneau(tk.Frame):
    """Panneau sombre à bord fin, avec un en-tête (titre en capitales) et un corps."""

    def __init__(self, parent, titre="", **kw):
        super().__init__(parent, bg=C["panneau"], highlightthickness=1,
                         highlightbackground=C["bord"], **kw)
        self.entete = tk.Frame(self, bg=C["panneau"])
        self.entete.pack(fill="x", padx=12, pady=(8, 4))
        self.titre = tk.Label(self.entete, text=titre.upper(), bg=C["panneau"], fg=C["texte"],
                              font=police(11, True))
        self.titre.pack(side="left")
        self.corps = tk.Frame(self, bg=C["panneau"])
        self.corps.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def etiquette(self, parent, texte, couleur=None, taille=9, **kw):
        return tk.Label(parent, text=texte, bg=parent.cget("bg"), fg=couleur or C["doux"],
                        font=police(taille), **kw)


def badge(parent, texte, couleur, fond=None):
    """Petite étiquette colorée (bande, état…)."""
    return tk.Label(parent, text=texte, bg=fond or C["pilule"], fg=couleur, font=police(9, True),
                    padx=8, pady=2)


def degrade_cascade():
    """256 couleurs pour la cascade : noir -> bleu nuit -> bleu -> cyan -> jaune -> rouge."""
    pts = [(0, (6, 8, 20)), (60, (15, 25, 90)), (110, (30, 70, 200)), (160, (40, 200, 230)),
           (205, (250, 220, 40)), (235, (250, 120, 30)), (255, (240, 40, 40))]
    out = []
    for v in range(256):
        for (a, ca), (b, cb) in zip(pts, pts[1:]):
            if a <= v <= b:
                u = (v - a) / (b - a)
                c = [int(ca[i] + u * (cb[i] - ca[i])) for i in range(3)]
                out.append("#%02x%02x%02x" % tuple(c))
                break
    return out


def curseur(parent, variable, de, a, longueur=140, commande=None):
    """Curseur plat (tk.Scale) aux couleurs du thème."""
    return tk.Scale(parent, variable=variable, from_=de, to=a, orient="horizontal",
                    length=longueur, showvalue=False, resolution=(a - de) / 200,
                    bg=C["accent"], troughcolor=C["pilule"],
                    activebackground="#7dd3fc", highlightthickness=0, bd=0, sliderrelief="flat",
                    sliderlength=14, width=8, command=commande)
