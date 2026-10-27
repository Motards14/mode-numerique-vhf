# -*- coding: utf-8 -*-
"""
Simulateur F4GOP - étapes 1 et 2 : démodulation cohérente RÉALISTE

Le récepteur ne connaît plus la phase : il doit la retrouver lui-même.
  - décalage de fréquence inconnu, après une recherche grossière sur le
    signal audio (comme FT8) : ±2,5 Hz pour 10,4 s, ±0,4 Hz pour 60 s
  - phase qui dérive au hasard (bruit de phase des oscillateurs + propagation)

La stabilité est résumée par le « temps de cohérence » Tc :
au bout de Tc secondes, la phase a dérivé en moyenne d'environ 1 radian (57°).

Récepteur :
  1. symboles pilotes connus, 1 symbole sur 4 (25 % du temps, comme la
     synchro de FT8 qui en prend 27 %)
  2. recherche de la fréquence par FFT sur les pilotes
  3. estimation de la phase par moyenne glissante sur les pilotes
  4. décodage, puis 2e passe : les bits décodés servent de pilotes
     supplémentaires (synchronisation « assistée par décision »)

Usage : python simulateur_phase.py [K]   (K = 7, 9 ou 11, défaut 11)
"""
import sys
import numpy as np
from simulateur import fsk8_noncoherent, NBITS, rng
from convolutif import Convolutif

PAS_PILOTE = 4                 # 1 pilote tous les 4 symboles


class Trame:
    """Disposition des symboles : pilotes + données codées."""

    def __init__(self, code):
        self.code = code
        ncode = code.longueur(NBITS)
        ngroupes = -(-ncode // (PAS_PILOTE - 1))
        self.nsym = ngroupes * PAS_PILOTE
        est_pilote = (np.arange(self.nsym) % PAS_PILOTE) == 0
        self.idx_data = np.flatnonzero(~est_pilote)[:ncode]
        self.idx_pil = np.flatnonzero(est_pilote)
        self.seq_pil = 1 - 2 * np.random.default_rng(7).integers(
            0, 2, self.idx_pil.size)


def moyenne_glissante(z, demi):
    """Somme complexe sur une fenêtre de ±demi symboles (par trame)."""
    if demi is None:
        return np.repeat(z.sum(1, keepdims=True), z.shape[1], 1)
    c = np.concatenate([np.zeros((z.shape[0], 1)), np.cumsum(z, 1)], 1)
    k = np.arange(z.shape[1])
    hi = np.minimum(k + demi + 1, z.shape[1])
    lo = np.maximum(k - demi, 0)
    return c[:, hi] - c[:, lo]


def estimer_freq(z, ts, f_centre=None, plage=None):
    """Fréquence de la composante dominante de z (FFT zéro-paddée)."""
    nfft = 1 << 14
    spec = np.abs(np.fft.fft(z, nfft, axis=1)) ** 2
    f = np.fft.fftfreq(nfft, ts)
    if plage is not None:
        hors = np.abs(f[None, :] - f_centre[:, None]) > plage
        spec = np.where(hors, 0, spec)
    return f[np.argmax(spec, 1)]


def bpsk_reel(tr, bits, snr_db, duree, tc, demi):
    F = bits.shape[0]
    nsym = tr.nsym
    ts = duree / nsym
    es = 10 ** (snr_db / 10) * 2500 * ts
    s = np.zeros((F, nsym))
    s[:, tr.idx_pil] = tr.seq_pil
    s[:, tr.idx_data] = 1.0 - 2 * tr.code.coder(bits)

    # --- canal : fréquence inconnue + phase qui dérive + bruit ---
    t = np.arange(nsym) * ts
    fmax = 0.4 / (PAS_PILOTE * ts)          # résidu après recherche grossière
    f0 = rng.uniform(-fmax, fmax, (F, 1))
    derive = np.cumsum(rng.normal(0, np.sqrt(ts / tc), (F, nsym)), 1)
    phase = rng.uniform(0, 2 * np.pi, (F, 1)) + 2 * np.pi * f0 * t + derive
    y = (np.sqrt(es) * s * np.exp(1j * phase)
         + rng.normal(0, np.sqrt(0.5), (F, nsym))
         + 1j * rng.normal(0, np.sqrt(0.5), (F, nsym)))

    # --- récepteur, passe 1 : pilotes seuls ---
    zp = y[:, tr.idx_pil] * tr.seq_pil
    fh = estimer_freq(zp, PAS_PILOTE * ts)
    ref = np.zeros((F, nsym))
    ref[:, tr.idx_pil] = tr.seq_pil

    for passe in range(2):
        yr = y * np.exp(-2j * np.pi * fh[:, None] * t)
        c = moyenne_glissante(yr * ref, demi)
        yc = yr * np.exp(-1j * np.angle(c))
        llr = 4 * np.sqrt(es) * yc.real[:, tr.idx_data]
        dec = tr.code.decoder(llr)
        if passe == 0:
            # passe 2 : les bits décodés deviennent des pilotes
            ref[:, tr.idx_data] = 1.0 - 2 * tr.code.coder(dec)
            fh = estimer_freq(y * ref, ts, fh, 0.5)
    return np.all(dec == bits, axis=1)


def taux(tr, snr, duree, tc, demi, F=400):
    bits = rng.integers(0, 2, (F, NBITS), dtype=np.int8)
    return bpsk_reel(tr, bits, snr, duree, tc, demi).mean()


def seuil(fonction, bas=-36.0, haut=-14.0, precision=0.2):
    """Recherche par dichotomie du SNR donnant 50 % de décodage."""
    while haut - bas > precision:
        m = (bas + haut) / 2
        if fonction(m) >= 0.5:
            haut = m
        else:
            bas = m
    return (bas + haut) / 2


FENETRES = [4, 8, 16, 32, 64, None]   # None = toute la trame


def meilleure_fenetre(tr, duree, tc, snr_test):
    scores = [taux(tr, snr_test, duree, tc, w, 300) for w in FENETRES]
    return FENETRES[int(np.argmax(scores))]


def taux_fsk(code, snr, duree, F=400):
    """8-FSK type FT8 avec la même part de synchro que FT8 (21 / 79)."""
    bits = rng.integers(0, 2, (F, NBITS), dtype=np.int8)
    llr = fsk8_noncoherent(code.coder(bits), snr, duree * 58 / 79)
    return np.mean(np.all(code.decoder(llr) == bits, axis=1))


SCENARIOS = [
    ("GPSDO, tropo stable        (Tc = 1000 s)", 1000.0),
    ("bon TCXO                   (Tc = 30 s)  ", 30.0),
    ("oscillateur moyen          (Tc = 3 s)   ", 3.0),
    ("très instable / scatter    (Tc = 0,5 s) ", 0.5),
]

if __name__ == "__main__":
    K = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    nb = int(sys.argv[2]) if len(sys.argv) > 2 else len(SCENARIOS)
    code = Convolutif(K)
    tr = Trame(code)
    print(f"Code convolutif K={K}, même code pour tous les modes")
    for duree in (10.4, 60.0):
        print(f"\n=== Trame de {duree:g} s — seuil de décodage (50 %), "
              f"SNR dans 2500 Hz ===", flush=True)
        ref_fsk = seuil(lambda s: taux_fsk(code, s, duree))
        print(f"8-FSK non cohérent type FT8 (synchro comprise) : "
              f"{ref_fsk:6.1f} dB   <- référence", flush=True)
        for nom, tc in SCENARIOS[:nb]:
            w = meilleure_fenetre(tr, duree, tc, ref_fsk - 3)
            s = seuil(lambda x: taux(tr, x, duree, tc, w))
            fen = "trame" if w is None else f"±{w}"
            print(f"BPSK cohérent, {nom} : {s:6.1f} dB   "
                  f"(gain {ref_fsk - s:+.1f} dB, fenêtre {fen})", flush=True)
