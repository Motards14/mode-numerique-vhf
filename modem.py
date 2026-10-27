# -*- coding: utf-8 -*-
"""
Modulateur / démodulateur — F4GOP

Modulation : MSK cohérente (écrite sous forme d'OQPSK à impulsions
demi-sinus). Deux avantages :
  - même performance que le BPSK cohérent des simulations (chaque bit
    est vu séparément sur la voie I ou la voie Q) ;
  - ENVELOPPE CONSTANTE, comme FT8 : l'émetteur peut sortir toute sa
    puissance, sans risque d'écrêtage ni de distorsion.

Trame : 91 bits -> code convolutif K=11 -> 202 bits -> + 1 pilote tous
les 4 bits -> 272 bits émis.

Sous-modes (périodes émission/réception, comme Q65) :
  R15 : période 15 s, émission 12,75 s, 21,3 bits/s, ~32 Hz de large
  R60 : période 60 s, émission 55,25 s,  4,9 bits/s,  ~8 Hz de large
L'émission commence 0,5 s après le début de la période (comme FT8).
"""
import numpy as np
from convolutif import Convolutif
from message import coder_message, decoder_message, NB_TOTAL

FS = 48000                 # fréquence d'échantillonnage (carte son IC-9700)
PAS_PILOTE = 4
DEBUT_TX = 0.5             # secondes après le début de la période
SOUS_MODES = {
    #       période (s), échantillons par bit
    "R15": (15, 2250),
    "R60": (60, 9750),
}

CODE = Convolutif(11)
NCODE = CODE.longueur(NB_TOTAL)                       # 202
NSYM = -(-NCODE // (PAS_PILOTE - 1)) * PAS_PILOTE     # 272
_est_pilote = (np.arange(NSYM) % PAS_PILOTE) == 0
IDX_DATA = np.flatnonzero(~_est_pilote)[:NCODE]
# les places libres en fin de trame (2 ici) servent aussi de pilotes
IDX_PIL = np.sort(np.concatenate([np.flatnonzero(_est_pilote),
                                  np.flatnonzero(~_est_pilote)[NCODE:]]))
SEQ_PIL = 1 - 2 * np.random.default_rng(7).integers(0, 2, IDX_PIL.size)
# pilotes régulièrement espacés (pour la recherche de fréquence par FFT)
_REG = np.isin(IDX_PIL, np.flatnonzero(_est_pilote))


def duree_tx(sous_mode):
    return (NSYM + 1) * SOUS_MODES[sous_mode][1] / FS


def bits_trame(texte):
    """Texte -> 272 valeurs ±1 (pilotes + données codées)."""
    info = np.array(coder_message(texte), dtype=np.int8)[None, :]
    s = np.zeros(NSYM)
    s[IDX_PIL] = SEQ_PIL
    s[IDX_DATA] = 1.0 - 2 * CODE.coder(info)[0]
    return s


def _impulsion(spb):
    t = (np.arange(2 * spb) + 0.5) / (2 * spb)
    return np.sin(np.pi * t)                       # demi-sinus sur 2 bits


def bande_de_base(symboles, spb):
    """OQPSK demi-sinus = MSK : signal complexe d'enveloppe constante."""
    n = len(symboles)
    x = np.zeros((n + 1) * spb, dtype=complex)
    p = _impulsion(spb)
    voie = np.where(np.arange(n) % 2 == 0, 1.0, 1j)  # I, Q, I, Q...
    for k, b in enumerate(symboles):
        x[k * spb:(k + 2) * spb] += b * voie[k] * p
    return x


def moduler(texte, sous_mode="R15", f_audio=1500.0, niveau=0.5):
    """Texte -> signal audio (float32, FS Hz) prêt à envoyer à la carte son."""
    spb = SOUS_MODES[sous_mode][1]
    x = bande_de_base(bits_trame(texte), spb)
    t = np.arange(x.size) / FS
    return (niveau * np.real(x * np.exp(2j * np.pi * f_audio * t))).astype(
        np.float32)


# ------------------------------------------------------------------
# Démodulation cohérente quand le début du signal et la fréquence audio
# sont connus approximativement (la recherche complète dans le
# waterfall sera faite côté réception).
# ------------------------------------------------------------------
def _correler(audio, sous_mode, f_audio, decalage):
    spb = SOUS_MODES[sous_mode][1]
    n = audio.size
    t = np.arange(n) / FS
    bb = audio * np.exp(-2j * np.pi * f_audio * t)
    p = _impulsion(spb)
    voie = np.where(np.arange(NSYM) % 2 == 0, 1.0, 1j)
    r = np.zeros(NSYM, dtype=complex)
    for k in range(NSYM):
        a = decalage + k * spb
        seg = bb[a:a + 2 * spb]
        if seg.size == 2 * spb:
            r[k] = np.dot(seg, p) * np.conj(voie[k])
    return r


def _moyenne_glissante(z, demi):
    c = np.concatenate([[0], np.cumsum(z)])
    k = np.arange(z.size)
    return c[np.minimum(k + demi + 1, z.size)] - c[np.maximum(k - demi, 0)]


def demoduler(audio, sous_mode="R15", f_audio=1500.0, decalage=0, demi=32):
    """Signal audio -> texte décodé (ou None). Deux passes comme dans
    simulateur_phase.py : pilotes, puis bits décodés comme pilotes."""
    spb = SOUS_MODES[sous_mode][1]
    tb = spb / FS
    r = _correler(audio, sous_mode, f_audio, decalage)
    k = np.arange(NSYM)
    # fréquence résiduelle par FFT sur les pilotes
    nfft = 1 << 14
    zp = r[IDX_PIL[_REG]] * SEQ_PIL[_REG]
    f = np.fft.fftfreq(nfft, PAS_PILOTE * tb)
    fh = f[np.argmax(np.abs(np.fft.fft(zp, nfft)))]
    ref = np.zeros(NSYM)
    ref[IDX_PIL] = SEQ_PIL
    bruit = None
    for passe in range(2):
        rr = r * np.exp(-2j * np.pi * fh * k * tb)
        c = _moyenne_glissante(rr * ref, demi)
        y = (rr * np.exp(-1j * np.angle(c))).real
        if bruit is None:
            # niveau de bruit estimé sur la voie en quadrature
            bruit = max(np.var((rr * np.exp(-1j * np.angle(c))).imag[IDX_PIL]),
                        1e-30)
        amp = np.mean(y[IDX_PIL] * SEQ_PIL)
        llr = 2 * max(amp, 1e-12) * y[IDX_DATA] / bruit
        dec = CODE.decoder(llr[None, :])
        if passe == 0:
            ref[IDX_DATA] = 1.0 - 2 * CODE.coder(dec)[0]
            zz = r * ref
            f2 = np.fft.fftfreq(nfft, tb)
            spec = np.abs(np.fft.fft(zz, nfft))
            spec[np.abs(f2 - fh) > 0.5 / (PAS_PILOTE * tb)] = 0
            fh = f2[np.argmax(spec)]
    return decoder_message(dec[0])
