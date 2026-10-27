# -*- coding: utf-8 -*-
"""Deux stations simulées font un QSO complet avec le séquenceur.
Usage : python tests/test_sequenceur.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sequenceur import Sequenceur


def qso(perdus=(), titre=""):
    """perdus : numéros d'émissions qui ne sont pas reçues (QSB, QRM)."""
    print(f"\n--- {titre}")
    a = Sequenceur("F4GOP", "IN98QR")
    b = Sequenceur("G4XYZ", "IO91WM")
    msg_a = a.lancer_cq()
    msg_b = None
    tx = 0
    for periode in range(30):
        emet, recoit, msg = (a, b, msg_a) if periode % 2 == 0 else (b, a, msg_b)
        if msg is None:
            if not a.actif() and not b.actif():
                break
            continue
        tx += 1
        recu = tx not in perdus
        print(f"  {'F4GOP' if emet is a else 'G4XYZ'} : {msg:22s}"
              f"{'' if recu else '   (perdu)'}")
        suivant = emet.apres_emission()
        if emet is a:
            msg_a = suivant
        else:
            msg_b = suivant
        if recu:
            if (recoit is b and b.etat == "repos" and msg.startswith("CQ")
                    and periode < 3):
                # l'opérateur de G4XYZ double-clique sur le CQ
                msg_b = b.repondre_a("F4GOP", -15, "IN98QR")
            else:
                if recoit.traiter([{"texte": msg, "snr": -12}]):
                    if recoit is a:
                        msg_a = recoit.message
                    else:
                        msg_b = recoit.message
    for nom, s in (("F4GOP", a), ("G4XYZ", b)):
        for q in s.prendre_qsos():
            print(f"  journal {nom} : {q['call']} loc {q['grid'] or '-'} "
                  f"envoyé {q['rst_sent']} reçu {q['rst_rcvd']}")
    return a, b


qso(titre="QSO parfait")
qso(perdus=(4,), titre="le R-report de G4XYZ est perdu une fois")
qso(perdus=(5,), titre="le RR73 de F4GOP est perdu une fois")
qso(perdus=(2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16),
    titre="G4XYZ disparaît après son appel : abandon")
