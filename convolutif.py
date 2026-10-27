# -*- coding: utf-8 -*-
"""
Codes convolutifs de longueur de contrainte K quelconque, taux 1/2,
treillis terminé, décodage de Viterbi à décisions souples (vectorisé).
K=7 est le code « classique » (sondes spatiales, WSPR) ; K=9 et K=11
sont plus puissants mais demandent plus de calcul au décodage
(256 et 1024 états — sans problème pour un PC actuel).
"""
import numpy as np

POLYNOMES = {7: (0o171, 0o133), 9: (0o753, 0o561), 11: (0o3345, 0o3613)}


def _parite(x):
    return bin(x).count("1") & 1


class Convolutif:
    def __init__(self, K=7):
        self.K = K
        g = POLYNOMES[K]
        self.nst = nst = 1 << (K - 1)
        self.out = np.zeros((nst, 2, 2), dtype=np.int8)
        self.next = np.zeros((nst, 2), dtype=np.int64)
        for s in range(nst):
            for u in range(2):
                reg = (u << (K - 1)) | s
                self.out[s, u] = [_parite(reg & p) for p in g]
                self.next[s, u] = reg >> 1
        self.pin = np.arange(nst) >> (K - 2)
        self.prev = np.zeros((nst, 2), dtype=np.int64)
        for ns in range(nst):
            u = self.pin[ns]
            self.prev[ns] = [s for s in range(nst) if self.next[s, u] == ns]
        sgn = 1 - 2 * self.out.astype(np.float64)       # (nst, 2, 2)
        self.sgn_prev = sgn[self.prev, self.pin[:, None]]  # (nst, 2, 2)

    def longueur(self, k):
        return 2 * (k + self.K - 1)

    def coder(self, bits):
        F, N = bits.shape
        b = np.concatenate([bits, np.zeros((F, self.K - 1), np.int8)], 1)
        s = np.zeros(F, dtype=np.int64)
        out = np.zeros((F, 2 * b.shape[1]), dtype=np.int8)
        for t in range(b.shape[1]):
            out[:, 2 * t:2 * t + 2] = self.out[s, b[:, t]]
            s = self.next[s, b[:, t]]
        return out

    def decoder(self, llr):
        F = llr.shape[0]
        T = llr.shape[1] // 2
        n = T - (self.K - 1)
        pm = np.full((F, self.nst), -1e18)
        pm[:, 0] = 0.0
        dec = np.zeros((T, F, self.nst), dtype=np.int8)
        for t in range(T):
            l = llr[:, 2 * t:2 * t + 2]
            bm = np.einsum("fk,spk->fsp", l, self.sgn_prev)   # (F,nst,2)
            cand = pm[:, self.prev] + bm
            k = np.argmax(cand, axis=2)
            pm = np.take_along_axis(cand, k[..., None], 2)[..., 0]
            dec[t] = k
        s = np.zeros(F, dtype=np.int64)
        bits = np.zeros((F, T), dtype=np.int8)
        ar = np.arange(F)
        for t in range(T - 1, -1, -1):
            bits[:, t] = self.pin[s]
            s = self.prev[s, dec[t, ar, s]]
        return bits[:, :n]
