# -*- coding: utf-8 -*-
"""
Simulateur F4GOP - étape 1 : démodulation cohérente RÉALISTE

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
"""
import numpy as np
from simulateur import coder, viterbi, fsk8_noncoherent, NBITS, rng

NCODE = 2 * (NBITS + 6)        # 194 bits codés
PAS_PILOTE = 4                 # 1 pilote tous les 4 symboles
NGROUPES = -(-NCODE // (PAS_PILOTE - 1))
NSYM = NGROUPES * PAS_PILOTE   # symboles émis (données + pilotes)
EST_PILOTE = (np.arange(NSYM) % PAS_PILOTE) == 0
IDX_DATA = np.flatnonzero(~EST_PILOTE)[:NCODE]
IDX_PIL = np.flatnonzero(EST_PILOTE)
SEQ_PIL = 1 - 2 * rng.integers(0, 2, IDX_PIL.size)   # séquence pilote ±1


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


def bpsk_reel(bits, snr_db, duree, tc, demi):
    F = bits.shape[0]
    ts = duree / NSYM
    es = 10 ** (snr_db / 10) * 2500 * ts
    cb = coder(bits)
    s = np.zeros((F, NSYM))
    s[:, IDX_PIL] = SEQ_PIL
    s[:, IDX_DATA] = 1.0 - 2 * cb

    # --- canal : fréquence inconnue + phase qui dérive + bruit ---
    t = np.arange(NSYM) * ts
    fmax = 0.4 / (PAS_PILOTE * ts)          # résidu après recherche grossière
    f0 = rng.uniform(-fmax, fmax, (F, 1))
    derive = np.cumsum(rng.normal(0, np.sqrt(ts / tc), (F, NSYM)), 1)
    phase = rng.uniform(0, 2 * np.pi, (F, 1)) + 2 * np.pi * f0 * t + derive
    y = (np.sqrt(es) * s * np.exp(1j * phase)
         + rng.normal(0, np.sqrt(0.5), (F, NSYM))
         + 1j * rng.normal(0, np.sqrt(0.5), (F, NSYM)))

    # --- récepteur, passe 1 : pilotes seuls ---
    zp = y[:, IDX_PIL] * SEQ_PIL
    fh = estimer_freq(zp, PAS_PILOTE * ts)
    ref = np.zeros((F, NSYM))
    ref[:, IDX_PIL] = SEQ_PIL

    for passe in range(2):
        yr = y * np.exp(-2j * np.pi * fh[:, None] * t)
        c = moyenne_glissante(yr * ref, demi)
        yc = yr * np.exp(-1j * np.angle(c))
        llr = 4 * np.sqrt(es) * yc.real[:, IDX_DATA]
        dec = viterbi(llr, NBITS)
        if passe == 0:
            # passe 2 : les bits décodés deviennent des pilotes
            ref[:, IDX_DATA] = 1.0 - 2 * coder(dec)
            fh = estimer_freq(y * ref, ts, fh, 0.5)
    return np.all(dec == bits, axis=1)


def taux(snr, duree, tc, demi, F=600):
    bits = rng.integers(0, 2, (F, NBITS), dtype=np.int8)
    return bpsk_reel(bits, snr, duree, tc, demi).mean()


def seuil(fonction, bas=-38.0, haut=-12.0, precision=0.25):
    """Recherche par dichotomie du SNR donnant 50 % de décodage."""
    while haut - bas > precision:
        m = (bas + haut) / 2
        if fonction(m) >= 0.5:
            haut = m
        else:
            bas = m
    return (bas + haut) / 2


FENETRES = [2, 4, 8, 16, 32, 64, 128, None]   # None = toute la trame


def meilleure_fenetre(duree, tc, snr_test):
    scores = [taux(snr_test, duree, tc, w, 400) for w in FENETRES]
    return FENETRES[int(np.argmax(scores))]


def taux_fsk(snr, duree, F=600):
    """8-FSK type FT8 avec la même part de synchro que FT8 (21 / 79)."""
    bits = rng.integers(0, 2, (F, NBITS), dtype=np.int8)
    llr = fsk8_noncoherent(coder(bits), snr, duree * 58 / 79)
    return np.mean(np.all(viterbi(llr, NBITS) == bits, axis=1))


if __name__ == "__main__":
    SCENARIOS = [
        ("GPSDO, tropo stable        (Tc = 1000 s)", 1000.0),
        ("bon TCXO                   (Tc = 30 s)  ", 30.0),
        ("oscillateur moyen          (Tc = 3 s)   ", 3.0),
        ("très instable / scatter    (Tc = 0,5 s) ", 0.5),
    ]
    for duree in (10.4, 60.0):
        print(f"\n=== Trame de {duree:g} s — seuil de décodage (50 %), "
              f"SNR dans 2500 Hz ===")
        ref_fsk = seuil(lambda s: taux_fsk(s, duree))
        print(f"8-FSK non cohérent type FT8 (synchro comprise) : "
              f"{ref_fsk:6.1f} dB   <- référence")
        for nom, tc in SCENARIOS:
            w = meilleure_fenetre(duree, tc, ref_fsk - 3)
            s = seuil(lambda x: taux(x, duree, tc, w))
            fen = "trame" if w is None else f"±{w}"
            print(f"BPSK cohérent, {nom} : {s:6.1f} dB   "
                  f"(gain {ref_fsk - s:+.1f} dB, fenêtre {fen})")
