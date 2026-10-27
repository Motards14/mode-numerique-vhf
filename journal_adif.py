# -*- coding: utf-8 -*-
"""
Journal des QSO au format ADIF (importable dans la plupart des logiciels
de trafic).

Fichier : Documents\\F4GOP-VHF\\journal.adi

Remarque : ce mode est nouveau, il n'existe donc pas encore dans la liste
officielle des modes ADIF. Par défaut il est noté MODE=MFSK avec
SUBMODE=F4GOP-VHF (modifiable dans les réglages). Certains logiciels ou
LoTW peuvent refuser un sous-mode inconnu.
"""
import os
import time

DOSSIER = os.path.join(os.path.expanduser("~"), "Documents", "F4GOP-VHF")
FICHIER = os.path.join(DOSSIER, "journal.adi")

BANDES = [  # (MHz min, MHz max, bande ADIF)
    (50, 54, "6m"), (70, 71, "4m"), (144, 148, "2m"), (220, 225, "1.25m"),
    (420, 450, "70cm"), (902, 928, "33cm"), (1240, 1300, "23cm"),
    (2300, 2450, "13cm"), (10000, 10500, "3cm"),
]


def bande(freq_mhz):
    if not freq_mhz:
        return ""
    for a, b, nom in BANDES:
        if a <= freq_mhz <= b:
            return nom
    return ""


def _champ(nom, valeur):
    v = str(valeur)
    return f"<{nom}:{len(v)}>{v} " if v else ""


def ligne_adif(qso, moi, mon_locator, freq_mhz=None, mode="MFSK",
               sous_mode="F4GOP-VHF", sous_mode_tr=""):
    d = time.gmtime(qso["debut"])
    f = time.gmtime(qso["fin"])
    champs = [
        _champ("CALL", qso["call"]),
        _champ("GRIDSQUARE", qso.get("grid", "")),
        _champ("MODE", mode),
        _champ("SUBMODE", sous_mode),
        _champ("RST_SENT", qso.get("rst_sent", "")),
        _champ("RST_RCVD", qso.get("rst_rcvd", "")),
        _champ("QSO_DATE", time.strftime("%Y%m%d", d)),
        _champ("TIME_ON", time.strftime("%H%M%S", d)),
        _champ("QSO_DATE_OFF", time.strftime("%Y%m%d", f)),
        _champ("TIME_OFF", time.strftime("%H%M%S", f)),
        _champ("BAND", bande(freq_mhz)),
        _champ("FREQ", f"{freq_mhz:.6f}" if freq_mhz else ""),
        _champ("STATION_CALLSIGN", moi),
        _champ("MY_GRIDSQUARE", mon_locator),
        _champ("COMMENT", f"F4GOP VHF {sous_mode_tr}".strip()),
    ]
    return "".join(champs) + "<EOR>\n"


def enregistrer(qso, moi, mon_locator, freq_mhz=None, fichier=FICHIER,
                **options):
    os.makedirs(os.path.dirname(fichier), exist_ok=True)
    nouveau = not os.path.exists(fichier)
    with open(fichier, "a", encoding="utf-8") as f:
        if nouveau:
            f.write("Journal F4GOP VHF\n<ADIF_VER:5>3.1.4 "
                    "<PROGRAMID:9>F4GOP-VHF <EOH>\n")
        f.write(ligne_adif(qso, moi, mon_locator, freq_mhz, **options))
    return fichier
