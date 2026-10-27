# -*- coding: utf-8 -*-
"""
F4GOP VHF — programme complet : émission + réception

  - capture du son de l'IC-9700 (carte son USB)
  - waterfall (cliquer dessus règle la fréquence d'émission)
  - décodage à la fin de chaque période
  - liste des messages ; les messages qui te sont adressés sont en couleur
  - double-clic sur un message : répond au correspondant ; avec le
    séquençage automatique, le QSO se déroule ensuite tout seul
    (report, R-report, RR73, 73) et il est enregistré dans le journal
    ADIF (Documents\\F4GOP-VHF\\journal.adi)

Lancer : python station.py
"""
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

import emetteur
from emetteur import Emetteur, sd
from modem import SOUS_MODES, FS, DEBUT_TX, duree_tx
from message import hash21
from decodeur import decoder_periode, PLAGE_DT
from sequenceur import Sequenceur, _est_locator
import journal_adif

TAMPON_S = 130                     # secondes d'audio gardées en mémoire
WF_LARGEUR, WF_HAUTEUR = 640, 170
WF_FMIN, WF_FMAX = 200.0, 2800.0


def entrees_audio():
    if sd is None:
        return []
    res = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            api = sd.query_hostapis(d["hostapi"])["name"]
            res.append((i, f"{d['name']}  [{api}]"))
    mme = [r for r in res if "MME" in r[1]]
    return mme or res


def _palette():
    """256 couleurs : noir -> bleu -> cyan -> jaune -> rouge."""
    pts = [(0, (0, 0, 0)), (70, (0, 0, 140)), (140, (0, 170, 220)),
           (200, (255, 230, 0)), (255, (255, 40, 0))]
    out = []
    for v in range(256):
        for (a, ca), (b, cb) in zip(pts, pts[1:]):
            if a <= v <= b:
                u = (v - a) / (b - a)
                c = [int(ca[i] + u * (cb[i] - ca[i])) for i in range(3)]
                out.append("#%02x%02x%02x" % tuple(c))
                break
    return out


class TamponAudio:
    """Mémoire circulaire d'audio datée en temps UTC (time.time())."""

    def __init__(self, duree):
        self.n = int(duree * FS)
        self.buf = np.zeros(self.n, dtype=np.float32)
        self.ecrit = 0                 # nb total d'échantillons reçus
        self.t_fin = None              # heure du dernier échantillon
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
        """Audio entre t_debut et t_debut + duree (secondes UTC)."""
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


class Station(Emetteur):
    def __init__(self):
        self.tampon = TamponAudio(TAMPON_S)
        self.flux = None
        self.derniere_decodee = None
        self.decodage_en_cours = False
        self.carnet = {}
        self.palette = _palette()
        self.wf = np.zeros((WF_HAUTEUR, WF_LARGEUR), dtype=np.uint8)
        self.niveau_entree = 1e-9
        self.seq = Sequenceur("", "")
        super().__init__()
        self.title(f"F4GOP VHF — Station  v{emetteur.VERSION}")
        self._construire_reception()
        self._demarrer_capture()
        self.after(250, self._rafraichir_wf)

    # ------------------------------------------------------------ interface
    def _construire_reception(self):
        rx = ttk.LabelFrame(self, text="Réception")
        rx.grid(row=0, column=1, rowspan=8, sticky="nsew", padx=6, pady=3)
        ttk.Label(rx, text="Entrée son").grid(row=0, column=0, sticky="w")
        self.entrees = entrees_audio()
        noms = [n for _, n in self.entrees]
        defaut = self.reglages.get("entree_son")
        if defaut not in noms:
            defaut = next((n for n in noms if "USB Audio CODEC" in n),
                          noms[0] if noms else "")
        self.v_entree = tk.StringVar(value=defaut)
        cb = ttk.Combobox(rx, textvariable=self.v_entree, values=noms,
                          width=46, state="readonly")
        cb.grid(row=0, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._demarrer_capture())
        self.l_niveau = ttk.Label(rx, text="niveau : —", width=16)
        self.l_niveau.grid(row=0, column=2, sticky="w")

        self.canvas = tk.Canvas(rx, width=WF_LARGEUR, height=WF_HAUTEUR + 16,
                                bg="black", highlightthickness=0)
        self.canvas.grid(row=1, column=0, columnspan=3, pady=4)
        self.image_wf = tk.PhotoImage(width=WF_LARGEUR, height=WF_HAUTEUR)
        self.canvas.create_image(0, 16, image=self.image_wf, anchor="nw")
        for f in range(500, 2800, 500):
            x = self._x_de_f(f)
            self.canvas.create_line(x, 10, x, 16, fill="white")
            self.canvas.create_text(x, 5, text=str(f), fill="white",
                                    font=("Consolas", 7))
        self.marque_tx = self.canvas.create_rectangle(0, 0, 0, 0,
                                                      outline="#ff4040")
        self.canvas.bind("<Button-1>", self._clic_wf)
        ttk.Label(rx, text="Clic sur le waterfall = fréquence d'émission",
                  foreground="gray").grid(row=2, column=0, columnspan=3,
                                          sticky="w")

        cols = ("utc", "db", "dt", "freq", "msg")
        self.liste = ttk.Treeview(rx, columns=cols, show="headings",
                                  height=14)
        for c, titre, w in zip(cols, ("UTC", "dB", "DT", "Fréq.", "Message"),
                               (70, 45, 50, 60, 300)):
            self.liste.heading(c, text=titre)
            self.liste.column(c, width=w, anchor="w" if c == "msg" else "e")
        self.liste.tag_configure("moi", background="#ffd0d0")
        self.liste.tag_configure("cq", background="#d8f0d8")
        self.liste.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.liste.bind("<Double-1>", self._double_clic)
        ttk.Button(rx, text="Effacer", command=lambda: self.liste.delete(
            *self.liste.get_children())).grid(row=4, column=0, sticky="w")
        self.l_dec = ttk.Label(rx, text="")
        self.l_dec.grid(row=4, column=1, columnspan=2, sticky="w")

        qa = ttk.LabelFrame(rx, text="QSO automatique")
        qa.grid(row=5, column=0, columnspan=3, sticky="ew", pady=4)
        self.v_auto = tk.BooleanVar(value=self.reglages.get("auto", True))
        ttk.Checkbutton(qa, text="Séquençage automatique",
                        variable=self.v_auto).grid(row=0, column=0, sticky="w")
        self.v_cq_apres = tk.BooleanVar(
            value=self.reglages.get("cq_apres", False))
        ttk.Checkbutton(qa, text="Relancer CQ après chaque QSO",
                        variable=self.v_cq_apres).grid(row=0, column=1,
                                                       sticky="w")
        ttk.Button(qa, text="Lancer CQ", command=self.lancer_cq).grid(
            row=0, column=2, padx=3)
        ttk.Button(qa, text="Arrêter le QSO", command=self.arreter_qso).grid(
            row=0, column=3, padx=3)
        self.l_qso = ttk.Label(qa, text="État : aucun QSO en cours",
                               foreground="#2060c0")
        self.l_qso.grid(row=1, column=0, columnspan=4, sticky="w")
        self.l_nb_qso = ttk.Label(qa, text="", foreground="gray")
        self.l_nb_qso.grid(row=2, column=0, columnspan=4, sticky="w")
        self.nb_qso = 0

    def _x_de_f(self, f):
        return (f - WF_FMIN) / (WF_FMAX - WF_FMIN) * WF_LARGEUR

    def _clic_wf(self, ev):
        f = WF_FMIN + ev.x / WF_LARGEUR * (WF_FMAX - WF_FMIN)
        self.v_fa.set(int(round(f / 10) * 10))

    # ------------------------------------------------------------ capture
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
        idx = next((i for i, n in self.entrees if n == self.v_entree.get()),
                   None)

        def rappel(indata, frames, temps, statut):
            bloc = indata[:, 0].astype(np.float32)
            self.tampon.ajouter(bloc, time.time())
            self.niveau_entree = float(np.sqrt(np.mean(bloc ** 2)) + 1e-9)

        try:
            self.flux = sd.InputStream(device=idx, samplerate=FS, channels=1,
                                       blocksize=2400, callback=rappel)
            self.flux.start()
            self.log("Réception audio démarrée")
        except Exception as e:
            self.log(f"Erreur entrée son : {e}")

    # ------------------------------------------------------------ waterfall
    def _rafraichir_wf(self):
        try:
            x = self.tampon.derniers(16384)
            if x is not None:
                spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
                f = np.fft.rfftfreq(x.size, 1 / FS)
                bords = np.linspace(WF_FMIN, WF_FMAX, WF_LARGEUR + 1)
                idx = np.searchsorted(f, bords)
                ligne = np.maximum.reduceat(spec, idx[:-1])
                db = 10 * np.log10(ligne + 1e-20)
                ref = np.median(db)
                val = np.clip((db - ref + 3) * 12, 0, 255).astype(np.uint8)
                self.wf = np.roll(self.wf, 1, axis=0)
                self.wf[0] = val
                pal = self.palette
                donnees = " ".join(
                    "{" + " ".join(pal[v] for v in row) + "}"
                    for row in self.wf)
                self.image_wf.put(donnees, to=(0, 0))
                niv = 20 * np.log10(self.niveau_entree)
                self.l_niveau.configure(text=f"niveau : {niv:5.1f} dBFS")
            # repère de la fréquence d'émission
            fa = float(self.v_fa.get())
            sm = self.v_sm.get()
            larg = 1.2 * FS / SOUS_MODES[sm][1]
            x0, x1 = self._x_de_f(fa - larg / 2), self._x_de_f(fa + larg / 2)
            self.canvas.coords(self.marque_tx, x0, 12, x1, WF_HAUTEUR + 16)
        except (tk.TclError, ValueError):
            pass
        self.after(250, self._rafraichir_wf)

    # ------------------------------------------------------------ décodage
    def _tic(self, n, t, periode):
        """Décode la période en cours dès que le signal le plus tardif
        possible est terminé (R15 : 14,8 s ; R60 : 57,5 s), pour avoir le
        temps de répondre au début de la période suivante."""
        sm = self.v_sm.get()
        seuil = min(DEBUT_TX + duree_tx(sm) + PLAGE_DT[1] + 0.05, periode)
        if t >= seuil:
            cible = n
        elif t < 0.5:
            cible = n - 1                    # rattrapage (seuil manqué)
        else:
            return
        if (sm, cible) != self.derniere_decodee and not self.decodage_en_cours:
            self.derniere_decodee = (sm, cible)
            if (sm, cible) in self.periodes_tx:
                return                       # on émettait : rien à décoder
            audio = self.tampon.extraire(cible * periode, periode)
            if audio is None:
                return
            precedente = cible
            self.decodage_en_cours = True
            moi = self.v_ind.get().strip().upper()
            if moi:
                self.carnet[hash21(moi)] = moi
            threading.Thread(target=self._decoder,
                             args=(audio, sm, precedente, periode),
                             daemon=True).start()

    def _decoder(self, audio, sm, n, periode):
        t0 = time.time()
        try:
            res = decoder_periode(audio, sm, dict(self.carnet))
        except Exception as e:
            res = []
            self.after(0, lambda: self.log(f"Erreur décodage : {e}"))
        duree = time.time() - t0
        self.after(0, lambda: self._afficher(res, n, periode, duree))

    def _afficher(self, res, n, periode, duree):
        self.decodage_en_cours = False
        heure = time.strftime("%H:%M:%S", time.gmtime(n * periode))
        moi = self.v_ind.get().strip().upper()
        for r in res:
            mots = r["texte"].split()
            for m in mots[:2]:
                if m not in ("CQ", "QRZ", "DE", "<...>"):
                    self.carnet[hash21(m)] = m
            tag = ()
            if moi and mots and mots[0] == moi:
                tag = ("moi",)
            elif mots and mots[0] == "CQ":
                tag = ("cq",)
            self.liste.insert("", "end", tags=tag, values=(
                heure, f"{r['snr']:+d}", f"{r['dt']:+.1f}", f"{r['f']:.0f}",
                r["texte"]), text=str(n))
        if res:
            self.liste.see(self.liste.get_children()[-1])
        self.l_dec.configure(
            text=f"{heure} : {len(res)} décodé(s) en {duree:.1f} s")
        if self.v_auto.get() and self.seq.actif():
            self._maj_seq()
            if self.seq.traiter(res):
                if self.seq.etat != "cq" and self.seq.dx:
                    # on répond dans la période opposée à celle reçue
                    self.v_par.set((n + 1) % 2)
                self._appliquer_seq("réponse reçue")

    def _double_clic(self, ev):
        item = self.liste.focus()
        if not item:
            return
        utc, db, dt, freq, texte = self.liste.item(item, "values")
        n = int(self.liste.item(item, "text"))
        mots = texte.split()
        moi = self.v_ind.get().strip().upper()
        if len(mots) < 2:
            return
        dx = mots[1]                          # celui qui émet = 2e mot
        if dx == moi:
            return
        self.v_dx.set(dx)
        try:
            self.v_rep.set(int(db))
        except ValueError:
            pass
        self.v_par.set((n + 1) % 2)            # on répond dans l'autre période
        if self.v_auto.get():
            self._maj_seq()
            if mots[0] == moi:
                self.seq.reprendre(texte, int(db))
            else:
                loc = mots[2] if len(mots) > 2 and _est_locator(mots[2]) else ""
                self.seq.repondre_a(dx, int(db), loc)
            self._appliquer_seq("double-clic")
            return
        if mots[0] == moi and len(mots) == 3:
            # il nous répond : on envoie l'étape suivante du QSO
            fin = mots[2]
            if fin.startswith("R") and fin[1:2] in "+-":
                self._remplir(lambda c, l, d, p: f"{d} {c} RR73")
            elif fin in ("RR73", "RRR"):
                self._remplir(lambda c, l, d, p: f"{d} {c} 73")
            elif fin[:1] in "+-":
                self._remplir(lambda c, l, d, p: f"{d} {c} R{p:+03d}")
            else:
                self._remplir(lambda c, l, d, p: f"{d} {c} {p:+03d}")
        else:
            # appel d'un CQ (ou d'une station quelconque) : on envoie le locator
            self._remplir(lambda c, l, d, p: f"{d} {c} {l}")
        self.emission_active.set(True)
        self._activer()
        self.log(f"Réponse préparée : {self.v_msg.get()}")

    # ------------------------------------------------------------ QSO auto
    def _maj_seq(self):
        self.seq.moi = self.v_ind.get().strip().upper()
        self.seq.locator = self.v_loc.get().strip().upper()
        self.seq.cq_apres_qso = bool(self.v_cq_apres.get())

    def _appliquer_seq(self, raison=""):
        """Met à jour le message à émettre d'après le séquenceur."""
        if self.seq.message:
            if self.seq.message != self.v_msg.get():
                self.v_msg.set(self.seq.message)
                self.log(f"Séquenceur : {self.seq.message}"
                         + (f"  ({raison})" if raison else ""))
            if not self.emission_active.get():
                self.emission_active.set(True)
                self._activer()
        else:
            if self.emission_active.get():
                self.emission_active.set(False)
                self.log("Séquenceur : fin d'émission"
                         + (f" ({raison})" if raison else ""))
        self.dx_courant()
        self._enregistrer_qsos()

    def dx_courant(self):
        txt = self.seq.libelle()
        self.l_qso.configure(text=f"État : {txt}")
        if self.seq.dx:
            self.v_dx.set(self.seq.dx)

    def lancer_cq(self):
        self._maj_seq()
        if not self.v_auto.get():
            self._remplir(lambda c, l, d, p: f"CQ {c} {l}")
            return
        self.seq.lancer_cq()
        self._appliquer_seq("CQ")

    def arreter_qso(self):
        self.seq.arreter()
        self._appliquer_seq("arrêt demandé")

    def _peut_emettre(self, t):
        # on attend la fin du décodage pour émettre le bon message
        if (self.v_auto.get() and self.seq.actif() and self.decodage_en_cours
                and t < emetteur.RETARD_MAX_TX - 0.1):
            return False
        return True

    def _fin_emission(self, interrompue):
        if interrompue:
            self.seq.arreter()
            self.dx_courant()
            return
        if self.v_auto.get() and self.seq.actif():
            self._maj_seq()
            self.seq.apres_emission()
            raison = ""
            if not self.seq.actif():
                raison = "pas de réponse" if not self.seq.qsos_finis else \
                    "QSO terminé"
            self._appliquer_seq(raison)

    def _enregistrer_qsos(self):
        for q in self.seq.prendre_qsos():
            freq = None
            f = self.radio.freq_hz
            if f:
                freq = (f + float(self.v_fa.get())) / 1e6
            try:
                fichier = journal_adif.enregistrer(
                    q, self.v_ind.get().strip().upper(),
                    self.v_loc.get().strip().upper(), freq,
                    sous_mode_tr=self.v_sm.get())
                self.nb_qso += 1
                self.l_nb_qso.configure(
                    text=f"{self.nb_qso} QSO cette session — {fichier}")
                self.log(f"QSO enregistré : {q['call']} {q['grid']} "
                         f"envoyé {q['rst_sent']} reçu {q['rst_rcvd']}")
            except Exception as e:
                self.log(f"Erreur journal : {e}")

    def quitter(self):
        self.reglages["entree_son"] = self.v_entree.get()
        self.reglages["auto"] = bool(self.v_auto.get())
        self.reglages["cq_apres"] = bool(self.v_cq_apres.get())
        if self.flux is not None:
            try:
                self.flux.stop()
                self.flux.close()
            except Exception:
                pass
        super().quitter()


if __name__ == "__main__":
    Station().mainloop()
