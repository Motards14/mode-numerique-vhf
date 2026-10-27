# -*- coding: utf-8 -*-
"""Test du décodeur sur des périodes synthétiques (plusieurs stations + bruit).
Usage : python tests/test_decodeur.py"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from scipy.signal import hilbert
from modem import moduler, FS, SOUS_MODES, DEBUT_TX
from decodeur import decoder_periode

rng = np.random.default_rng(11)


def periode(sous_mode, stations, bruit=1.0, tc=30.0):
    """stations : liste de (texte, f_audio, dt, snr_dB)."""
    n = SOUS_MODES[sous_mode][0] * FS
    y = rng.normal(0, bruit, n)
    p_bruit_2500 = bruit ** 2 * 2500 / (FS / 2)
    for texte, f, dt, snr in stations:
        a = moduler(texte, sous_mode, f, 1.0).astype(float)
        t = np.arange(a.size) / FS
        derive = np.cumsum(rng.normal(0, np.sqrt(1 / FS / tc), a.size))
        a = np.real(hilbert(a) * np.exp(1j * (rng.uniform(0, 6.3) + derive)))
        a *= np.sqrt(p_bruit_2500 * 10 ** (snr / 10) / 0.5)
        d = int((DEBUT_TX + dt) * FS)
        y[d:d + a.size] += a[:max(0, min(a.size, n - d))]
    return y


def afficher(res):
    for r in res:
        print(f"      {r['snr']:+4d} dB  dt {r['dt']:+5.2f} s  "
              f"{r['f']:7.1f} Hz  {r['texte']}")


if __name__ == "__main__":
    for sm in ("R15", "R60"):
        base = -21 if sm == "R15" else -27
        st = [("CQ F4GOP IN98QR", 812.0, 0.0, base + 3),
              ("F4ABC F4GOP -12", 1500.4, 0.3, base),
              ("G4XYZ F4GOP R-08", 1530.0, -0.2, base - 2),
              ("CQ ON4ABC JO20", 2210.7, 0.8, base - 6)]
        print(f"\n{sm} : 4 stations émises")
        for texte, f, dt, snr in st:
            print(f"      {snr:+4d} dB  dt {dt:+5.2f} s  {f:7.1f} Hz  {texte}")
        t0 = time.time()
        res = decoder_periode(periode(sm, st), sm)
        print(f"   décodées en {time.time() - t0:.1f} s :")
        afficher(res)
    # seuil : 1 station, SNR décroissant
    for sm, snrs, n in (("R15", (-21, -22, -23, -24), 12),
                        ("R60", (-28, -29, -30), 6)):
        for snr in snrs:
            ok = 0
            for i in range(n):
                f = rng.uniform(400, 2500)
                dt = rng.uniform(-0.4, 1.2)
                r = decoder_periode(periode(sm, [("F4ABC F4GOP 73", f, dt, snr)]), sm)
                ok += any(x["texte"] == "F4ABC F4GOP 73" for x in r)
            print(f"{sm} seuil : {snr} dB -> {ok}/{n} décodés")
    # bruit seul : fausses alertes
    faux = 0
    for i in range(30):
        faux += len(decoder_periode(periode("R15", []), "R15"))
    print(f"bruit seul, 30 périodes R15 : {faux} faux décodage(s)")
