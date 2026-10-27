# -*- coding: utf-8 -*-
"""
Décodeur — F4GOP

Reçoit l'audio d'une période complète (depuis le début de la période UTC)
et renvoie la liste des messages décodés, avec pour chacun :
  dt   : décalage en secondes par rapport à l'instant prévu (0,5 s)
  f    : fréquence audio en Hz
  snr  : rapport signal/bruit dans 2500 Hz (comme FT8)
  texte: le message

Méthode :
  1. passage en signal complexe à 8 kHz ;
  2. « spectrogramme » avec la fenêtre demi-sinus de la modulation :
     chaque case donne la corrélation d'un bit à une fréquence ;
  3. pour chaque instant de départ possible (±1 s autour de 0,5 s) et
     chaque fréquence, on additionne les 68 pilotes de façon cohérente
     (FFT) : un vrai signal ressort nettement du bruit ;
  4. les meilleurs candidats sont démodulés finement (temps, fréquence,
     phase) puis décodés ; le CRC 14 bits élimine les faux décodages.
"""
import numpy as np

from modem import (SOUS_MODES, NSYM, IDX_DATA, IDX_PIL, SEQ_PIL, _REG,
                   PAS_PILOTE, CODE, DEBUT_TX, FS)
from message import decoder_message

DECIM = 6
FS2 = FS // DECIM                          # 8000 Hz
F_MIN, F_MAX = 200.0, 2800.0
PLAGE_DT = (-0.5, 1.5)                     # tolérance d'horloge (s)
SEUIL_DETECTION = 11.0                     # dB au-dessus du bruit (pilotes)
MAX_CANDIDATS = 25

_VOIE = np.where(np.arange(NSYM) % 2 == 0, 1.0, 1j)
_PIL_REG = IDX_PIL[_REG]                   # pilotes réguliers (1 bit sur 4)
_SEQ_REG = SEQ_PIL[_REG]


def _parametres(sous_mode):
    spb = SOUS_MODES[sous_mode][1] // DECIM          # échantillons / bit
    pas = spb // 3 if sous_mode == "R15" else spb // 5   # pas de recherche
    nfft = 1 << int(np.ceil(np.log2(2 * spb * 2.5)))
    return spb, pas, nfft


def _impulsion(spb):
    t = (np.arange(2 * spb) + 0.5) / (2 * spb)
    return np.sin(np.pi * t)


def preparer(audio):
    """Audio 48 kHz réel -> signal analytique complexe à 8 kHz.
    Fait en une seule FFT : on garde les fréquences positives sous 4 kHz
    (filtre parfait, sans repliement) et on revient au temps à 8 kHz."""
    x = np.asarray(audio, dtype=float)
    m = x.size // DECIM
    X = np.fft.rfft(x[:m * DECIM])
    Z = np.zeros(m, dtype=complex)
    h = m // 2
    Z[0] = X[0]
    Z[1:h] = 2 * X[1:h]
    return np.fft.ifft(Z) / DECIM


def _spectrogramme(x, spb, pas, nfft):
    """Corrélations demi-sinus à toutes les positions et fréquences,
    avec la phase rapportée au temps absolu."""
    p = _impulsion(spb)
    n_trames = (x.size - 2 * spb) // pas + 1
    f = np.fft.fftfreq(nfft, 1 / FS2)
    garde = np.flatnonzero((f >= F_MIN) & (f <= F_MAX))
    out = np.empty((n_trames, garde.size), dtype=np.complex64)
    debuts = np.arange(n_trames) * pas
    for a in range(0, n_trames, 256):
        d = debuts[a:a + 256]
        seg = x[d[:, None] + np.arange(2 * spb)] * p
        X = np.fft.fft(seg, nfft, axis=1)[:, garde]
        # phase en temps absolu : e^{-j 2 pi f t_debut}
        X *= np.exp(-2j * np.pi * np.outer(d / FS2, f[garde]))
        out[a:a + 256] = X
    return out, f[garde]


def _rechercher(S, freqs, sous_mode, spb, pas):
    """Renvoie les candidats (score_dB, i0, f) triés par score."""
    pas_bit = spb // pas if spb % pas == 0 else None
    tb = spb / FS2
    i_min = max(0, int(round((DEBUT_TX + PLAGE_DT[0]) * FS2 / pas)))
    i_max = int(round((DEBUT_TX + PLAGE_DT[1]) * FS2 / pas))
    # position (en trames) de chaque pilote régulier pour un départ i0
    offs = np.round(_PIL_REG * spb / pas).astype(int)
    i_max = min(i_max, S.shape[0] - 1 - offs[-1])
    if i_max < i_min:
        return []
    bruit = np.median(np.abs(S) ** 2) / np.log(2)
    if not np.isfinite(bruit) or bruit <= 0:
        return []                          # silence (carte son coupée)
    nf = 128
    best = np.zeros(S.shape[1])
    best_i = np.zeros(S.shape[1], dtype=int)
    best_nu = np.zeros(S.shape[1])
    nu = np.fft.fftfreq(nf, PAS_PILOTE * tb)
    for a in range(i_min, i_max + 1, 8):
        i0 = np.arange(a, min(a + 8, i_max + 1))
        G = S[i0[:, None] + offs[None, :], :] * _SEQ_REG[None, :, None]
        P = np.abs(np.fft.fft(G, nf, axis=1)) ** 2       # (n_i0, nf, nbins)
        k = np.argmax(P, axis=1)
        m = np.take_along_axis(P, k[:, None, :], 1)[:, 0, :]
        j = np.argmax(m, axis=0)
        mm = m[j, np.arange(m.shape[1])]
        mieux = mm > best
        best[mieux] = mm[mieux]
        best_i[mieux] = i0[j[mieux]]
        best_nu[mieux] = nu[k[j[mieux], np.arange(m.shape[1])[mieux]]]
    score = 10 * np.log10(best / (bruit * len(offs)) + 1e-12)
    # garder les maxima locaux en fréquence, séparés d'une demi-largeur
    largeur = 1.2 / tb
    cands = []
    for b in np.argsort(score)[::-1]:
        if score[b] < SEUIL_DETECTION or len(cands) >= MAX_CANDIDATS:
            break
        fc = freqs[b] + best_nu[b]
        if all(abs(fc - c[2]) > largeur / 2 for c in cands):
            cands.append((score[b], best_i[b] * pas, fc))
    return cands


def _correlations(x, debut, f, spb, decalages=(0,)):
    """r_k pour les 272 bits, pour chaque décalage de départ (échantillons).
    Le signal est ramené en bande de base une seule fois, puis découpé en
    blocs d'un bit : chaque corrélation demi-sinus = 2 blocs consécutifs."""
    p = _impulsion(spb)
    p1, p2 = p[:spb], p[spb:]
    dmin, dmax = int(min(decalages)), int(max(decalages))
    a = debut + dmin
    n = (NSYM + 1) * spb + (dmax - dmin)
    if a < 0 or a + n > x.size:
        return [None] * len(decalages)
    # oscillateur local : exp calculé sur un seul bloc, puis produit
    # extérieur (beaucoup plus rapide qu'un exp sur tout le signal)
    nb = -(-n // spb)
    interne = np.exp(-2j * np.pi * f * np.arange(spb) / FS2)
    blocs = np.exp(-2j * np.pi * f * (a + np.arange(nb) * spb) / FS2)
    m = x[a:a + n] * np.outer(blocs, interne).ravel()[:n]
    res = []
    for d in decalages:
        o = int(d) - dmin
        B = m[o:o + (NSYM + 1) * spb].reshape(NSYM + 1, spb)
        res.append((B[:-1] @ p1 + B[1:] @ p2) * np.conj(_VOIE))
    return res


def _moyenne_glissante(z, demi):
    c = np.concatenate([[0], np.cumsum(z)])
    k = np.arange(z.size)
    return c[np.minimum(k + demi + 1, z.size)] - c[np.maximum(k - demi, 0)]


def _metrique_pilotes(r, tb):
    z = r[_PIL_REG] * _SEQ_REG
    nf = 512
    P = np.abs(np.fft.fft(z, nf)) ** 2
    k = np.argmax(P)
    return P[k], np.fft.fftfreq(nf, PAS_PILOTE * tb)[k]


def _decoder_lot(llr):
    return CODE.decoder(np.asarray(llr))


def _demoduler_lot(x, cands, spb, pas, carnet, demi=32):
    """Démodule tous les candidats ensemble (Viterbi en un seul passage)."""
    tb = spb / FS2
    k = np.arange(NSYM)
    retenus = []
    for score, debut, f in cands:
        # les pilotes étant espacés de 4 bits, une fréquence et ses
        # « fantômes » à ±1/(4 Tb) donnent le même résultat sur les pilotes
        # de la recherche grossière : on teste les trois exactement.
        alias = 1.0 / (PAS_PILOTE * tb)
        essais = []
        for fa in (f - alias, f, f + alias):
            r = _correlations(x, debut, fa, spb)[0]
            if r is not None:
                essais.append((_metrique_pilotes(r, tb)[0], fa))
        if not essais:
            continue
        f = max(essais)[1]
        meilleur = None
        decs = np.unique(np.round(np.linspace(-pas / 2, pas / 2, 5)))
        for d, r in zip(decs, _correlations(x, debut, f, spb, decs)):
            if r is None:
                continue
            m, nu = _metrique_pilotes(r, tb)
            if meilleur is None or m > meilleur[0]:
                meilleur = (m, debut + int(d), f, nu, r)
        if meilleur:
            retenus.append(meilleur[1:])
    if not retenus:
        return []
    n = len(retenus)
    refs = np.zeros((n, NSYM))
    refs[:, IDX_PIL] = SEQ_PIL
    fh = np.array([c[2] for c in retenus])
    R = np.array([c[3] for c in retenus])
    resultats = [None] * n
    a_faire = np.arange(n)
    for passe in range(2):
        Y = np.zeros((a_faire.size, NSYM))
        for j, i in enumerate(a_faire):
            rr = R[i] * np.exp(-2j * np.pi * fh[i] * k * tb)
            c = _moyenne_glissante(rr * refs[i], demi)
            Y[j] = (rr * np.exp(-1j * np.angle(c))).real
        dec = _decoder_lot(Y[:, IDX_DATA])
        echecs = []
        for j, i in enumerate(a_faire):
            texte = decoder_message(dec[j], carnet)
            if texte is not None:
                refs[i, IDX_DATA] = 1.0 - 2 * CODE.coder(dec[j:j + 1])[0]
                y = Y[j]
                amp = np.mean(y * refs[i])
                var = np.var(y - amp * refs[i])
                es_n0 = amp ** 2 / (2 * var) if var > 0 else 1e6
                snr = 10 * np.log10(es_n0 / (2500 * tb) + 1e-12)
                resultats[i] = {
                    "dt": retenus[i][0] / FS2 - DEBUT_TX,
                    "f": retenus[i][1] + fh[i],
                    "snr": int(round(snr)),
                    "texte": texte,
                }
            elif passe == 0:
                # 2e passe : les bits décodés (même faux) servent de
                # pilotes pour affiner fréquence et phase
                refs[i, IDX_DATA] = 1.0 - 2 * CODE.coder(dec[j:j + 1])[0]
                nfft = 1 << 14
                spec = np.abs(np.fft.fft(R[i] * refs[i], nfft))
                ff = np.fft.fftfreq(nfft, tb)
                spec[np.abs(ff - fh[i]) > 0.5 / (PAS_PILOTE * tb)] = 0
                fh[i] = ff[np.argmax(spec)]
                echecs.append(i)
        a_faire = np.array(echecs, dtype=int)
        if a_faire.size == 0:
            break
    return [r for r in resultats if r]


def decoder_periode(audio, sous_mode="R15", carnet=None):
    """audio : échantillons 48 kHz depuis le début de la période UTC."""
    spb, pas, nfft = _parametres(sous_mode)
    x = preparer(audio)
    S, freqs = _spectrogramme(x, spb, pas, nfft)
    cands = _rechercher(S, freqs, sous_mode, spb, pas)
    resultats = []
    vus = set()
    for res in _demoduler_lot(x, cands, spb, pas, carnet):
        if res["texte"] not in vus:
            vus.add(res["texte"])
            resultats.append(res)
    return sorted(resultats, key=lambda r: r["f"])
