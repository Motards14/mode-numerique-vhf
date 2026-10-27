# -*- coding: utf-8 -*-
"""
F4GOP VHF — programme d'émission (étape 3a)

Émet le message choisi au début des périodes UTC choisies, en pilotant
le PTT de l'IC-9700 par CI-V et en envoyant le son par sa carte son USB.

IMPORTANT : l'horloge du PC doit être à l'heure exacte (à moins d'une
seconde près), comme pour FT8. Sous Windows : Paramètres > Heure et
langue > « Synchroniser maintenant », ou un logiciel comme Meinberg NTP.
"""
import json
import os
import threading
import time
import wave
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np

from message import coder_message, ErreurMessage
from modem import moduler, duree_tx, SOUS_MODES, FS, DEBUT_TX
from radio import IC9700, ports_disponibles

try:
    import sounddevice as sd
except Exception:                         # pas de carte son (tests)
    sd = None

VERSION = "0.1"
FICHIER_REGLAGES = os.path.join(os.path.expanduser("~"), ".f4gop_vhf.json")
REGLAGES_DEFAUT = {
    "indicatif": "F4GOP", "locator": "IN98QR", "port": "",
    "carte_son": "", "f_audio": 1500, "sous_mode": "R15", "parite": 0,
    "niveau": 0.5, "report": -12,
}


def sorties_audio():
    """Liste (index, nom) des sorties audio, en privilégiant l'API MME."""
    if sd is None:
        return []
    res = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            api = sd.query_hostapis(d["hostapi"])["name"]
            res.append((i, f"{d['name']}  [{api}]"))
    mme = [r for r in res if "MME" in r[1]]
    return mme or res


def position_periode(maintenant, periode):
    """(numéro de période, secondes écoulées dans la période)."""
    n = int(maintenant // periode)
    return n, maintenant - n * periode


class Emetteur(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"F4GOP VHF — Émission  v{VERSION}")
        self.resizable(False, False)
        self.reglages = dict(REGLAGES_DEFAUT)
        try:
            with open(FICHIER_REGLAGES, encoding="utf-8") as f:
                self.reglages.update(json.load(f))
        except Exception:
            pass
        self.poste = None
        self.emission_active = tk.BooleanVar(value=False)
        self.en_cours = False
        self.derniere_periode = None
        self.arret = threading.Event()
        self._construire()
        self.protocol("WM_DELETE_WINDOW", self.quitter)
        self.after(100, self._horloge)

    # ------------------------------------------------------------ interface
    def _construire(self):
        r = self.reglages
        pad = {"padx": 6, "pady": 3}

        st = ttk.LabelFrame(self, text="Station")
        st.grid(row=0, column=0, sticky="ew", **pad)
        ttk.Label(st, text="Indicatif").grid(row=0, column=0, sticky="w")
        self.v_ind = tk.StringVar(value=r["indicatif"])
        ttk.Entry(st, textvariable=self.v_ind, width=10).grid(row=0, column=1)
        ttk.Label(st, text="Locator").grid(row=0, column=2, sticky="w")
        self.v_loc = tk.StringVar(value=r["locator"])
        ttk.Entry(st, textvariable=self.v_loc, width=8).grid(row=0, column=3)

        ma = ttk.LabelFrame(self, text="Matériel (IC-9700)")
        ma.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Label(ma, text="Port CI-V").grid(row=0, column=0, sticky="w")
        self.v_port = tk.StringVar(value=r["port"])
        self.cb_port = ttk.Combobox(ma, textvariable=self.v_port, width=12,
                                    values=ports_disponibles())
        self.cb_port.grid(row=0, column=1, sticky="w")
        ttk.Button(ma, text="Tester PTT (2 s)",
                   command=self.tester_ptt).grid(row=0, column=2, **pad)
        self.l_freq = ttk.Label(ma, text="")
        self.l_freq.grid(row=0, column=3)
        ttk.Label(ma, text="Carte son").grid(row=1, column=0, sticky="w")
        self.sorties = sorties_audio()
        noms = [n for _, n in self.sorties]
        defaut = r["carte_son"] if r["carte_son"] in noms else next(
            (n for n in noms if "USB Audio CODEC" in n), noms[0] if noms else "")
        self.v_son = tk.StringVar(value=defaut)
        ttk.Combobox(ma, textvariable=self.v_son, values=noms, width=48,
                     state="readonly").grid(row=1, column=1, columnspan=3,
                                            sticky="w")
        ttk.Label(ma, text="Niveau audio").grid(row=2, column=0, sticky="w")
        self.v_niv = tk.DoubleVar(value=r["niveau"])
        ttk.Scale(ma, from_=0.02, to=1.0, variable=self.v_niv,
                  length=200).grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Label(ma, text="(régler pour que l'ALC ne bouge pas)").grid(
            row=2, column=3, sticky="w")

        mo = ttk.LabelFrame(self, text="Mode")
        mo.grid(row=2, column=0, sticky="ew", **pad)
        ttk.Label(mo, text="Sous-mode").grid(row=0, column=0, sticky="w")
        self.v_sm = tk.StringVar(value=r["sous_mode"])
        for i, sm in enumerate(SOUS_MODES):
            ttk.Radiobutton(mo, text=f"{sm} ({SOUS_MODES[sm][0]} s)",
                            value=sm, variable=self.v_sm).grid(
                row=0, column=1 + i, sticky="w")
        ttk.Label(mo, text="Émettre en").grid(row=1, column=0, sticky="w")
        self.v_par = tk.IntVar(value=r["parite"])
        ttk.Radiobutton(mo, text="1re période (paire)", value=0,
                        variable=self.v_par).grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(mo, text="2e période (impaire)", value=1,
                        variable=self.v_par).grid(row=1, column=2, sticky="w")
        ttk.Label(mo, text="Fréquence audio (Hz)").grid(row=2, column=0,
                                                        sticky="w")
        self.v_fa = tk.IntVar(value=r["f_audio"])
        ttk.Spinbox(mo, from_=300, to=2700, increment=10, width=7,
                    textvariable=self.v_fa).grid(row=2, column=1, sticky="w")

        ms = ttk.LabelFrame(self, text="Message")
        ms.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Label(ms, text="Indicatif du correspondant").grid(row=0, column=0,
                                                              sticky="w")
        self.v_dx = tk.StringVar()
        ttk.Entry(ms, textvariable=self.v_dx, width=10).grid(row=0, column=1,
                                                             sticky="w")
        ttk.Label(ms, text="Report").grid(row=0, column=2, sticky="e")
        self.v_rep = tk.IntVar(value=r["report"])
        ttk.Spinbox(ms, from_=-50, to=49, width=5,
                    textvariable=self.v_rep).grid(row=0, column=3, sticky="w")
        cadre = ttk.Frame(ms)
        cadre.grid(row=1, column=0, columnspan=4, sticky="w", pady=3)
        for i, (nom, fn) in enumerate([
                ("CQ", lambda c, l, d, p: f"CQ {c} {l}"),
                ("Locator", lambda c, l, d, p: f"{d} {c} {l}"),
                ("Report", lambda c, l, d, p: f"{d} {c} {p:+03d}"),
                ("R+report", lambda c, l, d, p: f"{d} {c} R{p:+03d}"),
                ("RR73", lambda c, l, d, p: f"{d} {c} RR73"),
                ("73", lambda c, l, d, p: f"{d} {c} 73")]):
            ttk.Button(cadre, text=nom, width=9,
                       command=lambda f=fn: self._remplir(f)).grid(
                row=0, column=i, padx=2)
        ttk.Label(ms, text="À émettre").grid(row=2, column=0, sticky="w")
        self.v_msg = tk.StringVar()
        ttk.Entry(ms, textvariable=self.v_msg, width=30,
                  font=("Consolas", 11)).grid(row=2, column=1, columnspan=3,
                                              sticky="w")
        self._remplir(lambda c, l, d, p: f"CQ {c} {l}")

        bo = ttk.Frame(self)
        bo.grid(row=4, column=0, sticky="ew", **pad)
        self.b_act = tk.Checkbutton(
            bo, text="Émission activée", variable=self.emission_active,
            indicatoron=False, width=18, selectcolor="#e05050",
            command=self._activer)
        self.b_act.grid(row=0, column=0, padx=3)
        ttk.Button(bo, text="ARRÊT IMMÉDIAT", command=self.stop).grid(
            row=0, column=1, padx=3)
        ttk.Button(bo, text="Enregistrer en WAV…",
                   command=self.enregistrer_wav).grid(row=0, column=2, padx=3)

        self.l_heure = ttk.Label(self, font=("Consolas", 13))
        self.l_heure.grid(row=5, column=0, sticky="w", **pad)
        self.l_etat = ttk.Label(self, text="Prêt", foreground="#2060c0")
        self.l_etat.grid(row=6, column=0, sticky="w", **pad)
        self.journal = tk.Text(self, height=8, width=70, font=("Consolas", 9),
                               state="disabled")
        self.journal.grid(row=7, column=0, **pad)

    def _remplir(self, fn):
        c = self.v_ind.get().strip().upper()
        loc = self.v_loc.get().strip().upper()
        d = self.v_dx.get().strip().upper() or "F4ABC"
        try:
            p = int(self.v_rep.get())
        except (ValueError, tk.TclError):
            p = -12
        self.v_msg.set(fn(c, loc, d, p))

    def log(self, texte):
        h = time.strftime("%H:%M:%S", time.gmtime())
        self.journal.configure(state="normal")
        self.journal.insert("end", f"{h}  {texte}\n")
        self.journal.see("end")
        self.journal.configure(state="disabled")

    def _etat(self, texte, couleur="#2060c0"):
        self.after(0, lambda: self.l_etat.configure(text=texte,
                                                     foreground=couleur))

    # ------------------------------------------------------------ matériel
    def _poste(self):
        port = self.v_port.get().strip()
        if not port:
            return None
        if self.poste is None or self.poste.ser.port != port:
            if self.poste:
                self.poste.fermer()
            self.poste = IC9700(port)
        return self.poste

    def _index_son(self):
        for i, n in self.sorties:
            if n == self.v_son.get():
                return i
        return None

    def tester_ptt(self):
        try:
            p = self._poste()
            if p is None:
                messagebox.showwarning("PTT", "Choisis d'abord le port CI-V.")
                return
            f = p.frequence()
            if f:
                self.l_freq.configure(text=f"{f / 1e6:.6f} MHz")
            p.ptt(True)
            self.log("Test PTT : émission 2 s (sans modulation)")
            self.after(2000, lambda: self._ptt_off())
        except Exception as e:
            messagebox.showerror("PTT", str(e))

    def _ptt_off(self):
        try:
            if self.poste:
                self.poste.ptt(False)
        except Exception as e:
            self.log(f"Erreur PTT : {e}")

    # ------------------------------------------------------------ émission
    def _verifier_message(self):
        try:
            coder_message(self.v_msg.get())
            return True
        except ErreurMessage as e:
            messagebox.showerror("Message", str(e))
            return False

    def _activer(self):
        if self.emission_active.get() and not self._verifier_message():
            self.emission_active.set(False)

    def stop(self):
        self.emission_active.set(False)
        self.arret.set()
        if sd is not None:
            sd.stop()
        self._ptt_off()
        self._etat("Arrêté", "#c03030")
        self.log("Arrêt immédiat")

    def _horloge(self):
        maintenant = time.time()
        periode = SOUS_MODES[self.v_sm.get()][0]
        n, t = position_periode(maintenant, periode)
        self.l_heure.configure(
            text=time.strftime("%H:%M:%S UTC", time.gmtime(maintenant))
            + f"   période {'paire' if n % 2 == 0 else 'impaire'}"
            + f"   {periode - t:4.1f} s restantes")
        if (self.emission_active.get() and not self.en_cours
                and n % 2 == self.v_par.get() and t < DEBUT_TX - 0.15
                and n != self.derniere_periode):
            self.derniere_periode = n
            self._lancer(n * periode)
        elif not self.en_cours and self.emission_active.get():
            self._etat("En attente de la prochaine période d'émission")
        self.after(50, self._horloge)

    def _lancer(self, debut_periode):
        texte = self.v_msg.get().strip().upper()
        sm = self.v_sm.get()
        try:
            audio = moduler(texte, sm, float(self.v_fa.get()),
                            float(self.v_niv.get()))
        except Exception as e:
            self.emission_active.set(False)
            messagebox.showerror("Message", str(e))
            return
        self.en_cours = True
        self.arret.clear()
        threading.Thread(target=self._emettre,
                         args=(audio, texte, debut_periode), daemon=True).start()

    def _emettre(self, audio, texte, debut_periode):
        poste = None
        try:
            poste = self._poste()
            if poste:
                poste.ptt(True)
            attente = debut_periode + DEBUT_TX - time.time()
            if attente > 0:
                time.sleep(attente)
            if self.arret.is_set():
                return
            self._etat(f"ÉMISSION : {texte}", "#c03030")
            self.after(0, lambda: self.log(f"TX  {texte}"))
            if sd is None:
                time.sleep(audio.size / FS)
            else:
                idx = self._index_son()
                canaux = 1
                if idx is not None and sd.query_devices(idx)[
                        "max_output_channels"] >= 2:
                    canaux = 2
                donnees = np.repeat(audio[:, None], canaux, 1)
                sd.play(donnees, FS, device=idx)
                sd.wait()
        except Exception as e:
            msg = f"Erreur émission : {e}"
            self.after(0, lambda: (self.log(msg),
                                   self.emission_active.set(False)))
        finally:
            try:
                if poste:
                    poste.ptt(False)
            except Exception:
                pass
            self.en_cours = False
            self._etat("Réception", "#2060c0")

    def enregistrer_wav(self):
        if not self._verifier_message():
            return
        nom = filedialog.asksaveasfilename(
            defaultextension=".wav", filetypes=[("Fichier WAV", "*.wav")],
            initialfile=self.v_msg.get().strip().replace(" ", "_") + ".wav")
        if not nom:
            return
        audio = moduler(self.v_msg.get(), self.v_sm.get(),
                        float(self.v_fa.get()), float(self.v_niv.get()))
        ecrire_wav(nom, audio)
        self.log(f"WAV enregistré : {nom}")

    def quitter(self):
        self.stop()
        try:
            self.reglages.update({
            "indicatif": self.v_ind.get(), "locator": self.v_loc.get(),
            "port": self.v_port.get(), "carte_son": self.v_son.get(),
            "f_audio": int(self.v_fa.get()), "sous_mode": self.v_sm.get(),
            "parite": int(self.v_par.get()), "niveau": float(self.v_niv.get()),
            "report": int(self.v_rep.get())})
        except (ValueError, tk.TclError):
            pass
        try:
            with open(FICHIER_REGLAGES, "w", encoding="utf-8") as f:
                json.dump(self.reglages, f, indent=1)
        except Exception:
            pass
        if self.poste:
            self.poste.fermer()
        self.destroy()


def ecrire_wav(nom, audio):
    with wave.open(nom, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    Emetteur().mainloop()
