# -*- coding: utf-8 -*-
"""
Simulateur F4GOP - comparaison de modulations pour un mode numérique VHF/UHF
Mesure le seuil de décodage (50 % de messages décodés) en dB dans 2500 Hz,
comme les chiffres annoncés pour FT8 / Q65.

Même message (91 bits = 77 bits utiles + CRC, comme FT8) et même code
correcteur pour tous les modes : on compare uniquement les modulations.
Le code utilisé ici (convolutif K=7) est plus faible que le LDPC de FT8 ;
ce qui compte, c'est l'écart entre les modes.
"""
import numpy as np
from scipy.special import i0e, logsumexp

rng = np.random.default_rng(1)
NBITS = 91          # bits du message
K = 7               # longueur de contrainte du code convolutif
G = (0o171, 0o133)  # polynômes standard (taux 1/2)
NST = 1 << (K - 1)  # 64 états

# ---------- Code convolutif ----------
def parite(x):
    return bin(x).count("1") & 1

OUT = np.zeros((NST, 2, 2), dtype=np.int8)   # bits de sortie [état, entrée, 2]
NEXT = np.zeros((NST, 2), dtype=np.int64)
for s in range(NST):
    for u in range(2):
        reg = (u << (K - 1)) | s
        OUT[s, u] = [parite(reg & g) for g in G]
        NEXT[s, u] = reg >> 1

# prédécesseurs de chaque état
PREV = np.zeros((NST, 2), dtype=np.int64)
PIN = np.zeros(NST, dtype=np.int64)
for ns in range(NST):
    u = ns >> (K - 2)
    PIN[ns] = u
    PREV[ns] = [s for s in range(NST) if NEXT[s, u] == ns]

def coder(bits):
    """bits: (F, N) -> bits codés (F, 2*(N+K-1)), treillis terminé."""
    F, N = bits.shape
    b = np.concatenate([bits, np.zeros((F, K - 1), dtype=np.int8)], axis=1)
    s = np.zeros(F, dtype=np.int64)
    out = np.zeros((F, 2 * b.shape[1]), dtype=np.int8)
    for t in range(b.shape[1]):
        out[:, 2 * t:2 * t + 2] = OUT[s, b[:, t]]
        s = NEXT[s, b[:, t]]
    return out

def viterbi(llr, n):
    """llr: (F, 2*(n+K-1)), positif = bit 0. Renvoie (F, n)."""
    F = llr.shape[0]
    T = n + K - 1
    sgn = 1 - 2 * OUT.astype(np.float64)          # +1 si bit 0, -1 si bit 1
    pm = np.full((F, NST), -1e18); pm[:, 0] = 0.0
    dec = np.zeros((F, T, NST), dtype=np.int8)
    for t in range(T):
        l = llr[:, 2 * t:2 * t + 2]                 # (F,2)
        bm = np.einsum("fk,suk->fsu", l, sgn)       # (F,64,2)
        cand = pm[:, PREV] + bm[:, PREV, PIN[None, :].repeat(2, 0).T]
        k = np.argmax(cand, axis=2)
        pm = np.take_along_axis(cand, k[..., None], 2)[..., 0]
        dec[:, t] = k
    s = np.zeros(F, dtype=np.int64)                 # treillis terminé -> état 0
    bits = np.zeros((F, T), dtype=np.int8)
    for t in range(T - 1, -1, -1):
        bits[:, t] = PIN[s]
        s = PREV[s, dec[np.arange(F), t, s]]
    return bits[:, :n]

# ---------- Modulations ----------
def snr_vers_esn0(snr_db, ts):
    """SNR dans 2500 Hz -> Es/N0 linéaire pour une durée de symbole ts."""
    return 10 ** (snr_db / 10) * 2500 * ts

def bpsk_coherent(cb, snr_db, duree):
    F, n = cb.shape
    es = snr_vers_esn0(snr_db, duree / n)
    x = 1.0 - 2 * cb
    y = np.sqrt(es) * x + rng.normal(0, np.sqrt(0.5), (F, n))
    return 4 * np.sqrt(es) * y                       # LLR (N0 = 1)

GRAY8 = np.array([0, 1, 3, 2, 6, 7, 5, 4])           # mapping Gray 8 tons
BITS8 = np.array([[(g >> (2 - i)) & 1 for i in range(3)] for g in range(8)])
TON_DE = np.argsort(GRAY8)                           # valeur -> ton

def fsk8_noncoherent(cb, snr_db, duree):
    """8-FSK non cohérent façon FT8, avec LLR exactes (log I0)."""
    F, n = cb.shape
    pad = (-n) % 3
    c = np.concatenate([cb, np.zeros((F, pad), dtype=np.int8)], 1)
    ns = c.shape[1] // 3
    val = c[:, 0::3] * 4 + c[:, 1::3] * 2 + c[:, 2::3]
    ton = TON_DE[val]                                 # (F, ns)
    es = snr_vers_esn0(snr_db, duree / ns)
    r = (rng.normal(0, np.sqrt(0.5), (F, ns, 8))
         + 1j * rng.normal(0, np.sqrt(0.5), (F, ns, 8)))
    phi = np.exp(1j * rng.uniform(0, 2 * np.pi, (F, ns)))
    np.put_along_axis(r, ton[..., None],
                      np.take_along_axis(r, ton[..., None], 2) + np.sqrt(es) * phi[..., None], 2)
    a = 2 * np.sqrt(es) * np.abs(r)
    m = np.log(i0e(a)) + a                           # métrique par ton
    mv = m[..., TON_DE]                               # métrique par valeur
    llr = np.zeros((F, ns, 3))
    for i in range(3):
        b = BITS8[:, i]
        llr[..., i] = logsumexp(mv[..., b == 0], -1) - logsumexp(mv[..., b == 1], -1)
    return llr.reshape(F, -1)[:, :n]

# ---------- Mesure du seuil ----------
def taux_decodage(mod, duree, snr_db, F=300):
    bits = rng.integers(0, 2, (F, NBITS), dtype=np.int8)
    llr = mod(coder(bits), snr_db, duree)
    return np.mean(np.all(viterbi(llr, NBITS) == bits, axis=1))

def seuil(mod, duree, grille):
    prec = None
    for snr in grille:
        p = taux_decodage(mod, duree, snr)
        if p >= 0.5:
            if prec is None:
                return snr
            s0, p0 = prec                               # interpolation linéaire
            return s0 + (0.5 - p0) / (p - p0) * (snr - s0)
        prec = (snr, p)
    return float("nan")

if __name__ == "__main__":
    grille = np.arange(-36, -10, 0.5)
    modes = [
        ("8-FSK non cohérent (type FT8), 10,4 s", fsk8_noncoherent, 10.4),
        ("BPSK cohérent idéal,           10,4 s", bpsk_coherent, 10.4),
        ("8-FSK non cohérent,            60 s  ", fsk8_noncoherent, 60.0),
        ("BPSK cohérent idéal,           60 s  ", bpsk_coherent, 60.0),
    ]
    print("Seuil de décodage (50 %), SNR dans 2500 Hz")
    print("-" * 52)
    for nom, mod, d in modes:
        print(f"{nom} : {seuil(mod, d, grille):6.1f} dB")
