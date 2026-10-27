# -*- coding: utf-8 -*-
"""
Test de bout en bout de la fenêtre F4GOP VHF, EN TEMPS RÉEL (Linux + écran
virtuel Xvfb) :
  - un faux IC-9700 sur un port série virtuel (PTT et fréquence en CI-V) ;
  - une station simulée G4XYZ (avec son propre séquenceur) qui lance appel ;
    ses signaux sont modulés, bruités à -16 dB et injectés dans l'entrée
    audio du programme, période après période ;
  - le programme décode le CQ, on « double-clique » dessus, puis le QSO doit
    se dérouler tout seul jusqu'au journal ADIF.

Usage : xvfb-run -a python tests/test_qso_reel.py
"""
import json
import os
import sys
import tempfile
import threading
import time

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, ".."))
sys.path.insert(0, ICI)
os.environ["HOME"] = tempfile.mkdtemp()

import numpy as np                                       # noqa: E402
import f4gop_vhf as A                                    # noqa: E402
import radio                                             # noqa: E402
from faux_ic9700 import FauxIC9700                       # noqa: E402
from sequenceur import Sequenceur                        # noqa: E402
import test_decodeur as T                                # noqa: E402

A.sd = None
A.FICHIER_REGLAGES = os.path.join(os.environ["HOME"], ".f4gop_vhf.json")
poste = FauxIC9700(freq=432174000)
adif = os.path.join(os.environ["HOME"], "journal.adi")
json.dump({"radio": dict(radio.DEFAULTS, rig="icom:IC-9700", port=poste.port, ptt="CAT"),
           "fichier_adif": adif, "parite": 0}, open(A.FICHIER_REGLAGES, "w"))

app = A.Application()
B = Sequenceur("G4XYZ", "IO91WM")
B.lancer_cq()
PER = 15
journal = []
fin_test = threading.Event()


def station_g4xyz():
    """Chaque période : si c'est le tour de G4XYZ (impaire), il émet son message ;
    sinon il « reçoit » ce que F4GOP a émis."""
    n_prec = None
    audio = None
    while not fin_test.is_set():
        now = time.time()
        n = int(now // PER)
        if n != n_prec:
            if n_prec is not None and n_prec % 2 == 0:
                # période paire précédente : F4GOP a peut-être émis -> G4XYZ le reçoit
                tx = [d for d in app.decodes if d["tx"] and d.get("n_tx") == n_prec]
                if tx and B.traiter([{"texte": tx[-1]["texte"], "snr": -14}]):
                    pass
            n_prec = n
            if n % 2 == 1 and B.message:
                journal.append(f"G4XYZ émet : {B.message}")
                audio = T.periode("R15", [(B.message, 1100.0, 0.1, -16)]).astype(np.float32)
                B.apres_emission()
            else:
                audio = (np.random.default_rng(n).normal(0, 1, PER * A.FS)).astype(np.float32)
            pos = 0
        # injecte l'audio de la période au rythme réel
        cible = int((time.time() - n * PER) * A.FS)
        cible = min(cible, audio.size)
        if cible > pos:
            app.tampon.ajouter(audio[pos:cible] * 0.05, n * PER + cible / A.FS)
            pos = cible
        time.sleep(0.05)


# on note le numéro de période de chaque émission de F4GOP
ancien_ajouter_tx = app._ajouter_tx


def ajouter_tx(texte):
    ancien_ajouter_tx(texte)
    app.decodes[-1]["n_tx"] = int(time.time() // PER)
    journal.append(f"F4GOP émet : {texte}")


app._ajouter_tx = ajouter_tx


def surveiller():
    """Double-clic sur le CQ dès qu'il est décodé, puis attente de la fin du QSO."""
    if not app.seq.actif() and not getattr(app, "_appel_fait", False):
        cq = [d for d in app.decodes if not d["tx"] and d["texte"].startswith("CQ G4XYZ")]
        if cq:
            app._appel_fait = True
            journal.append(f"F4GOP décode : {cq[-1]['texte']} ({cq[-1]['snr']:+d} dB) "
                           f"-> double-clic")
            app.repondre(cq[-1]["texte"], cq[-1]["snr"], cq[-1]["n"])
    if os.path.exists(adif) and not B.actif() and not app.seq.actif():
        fin_test.set()
        app.after(500, app.quitter)
        return
    app.after(200, surveiller)


threading.Thread(target=station_g4xyz, daemon=True).start()
app.after(1000, surveiller)
app.after(240000, lambda: (journal.append("TEMPS DÉPASSÉ"), fin_test.set(), app.quitter()))
t0 = time.time()
app.mainloop()
for l in journal:
    print(" ", l)
print(f"durée : {time.time() - t0:.0f} s ; PTT reçus par le faux IC-9700 : {poste.journal}")
print("journal ADIF :")
print(open(adif).read() if os.path.exists(adif) else "  (vide)")
print("journal de G4XYZ :", B.prendre_qsos())
