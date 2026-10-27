# -*- coding: utf-8 -*-
"""
Code correcteur LDPC — F4GOP
  - construction de la matrice de parité par PEG (Progressive Edge Growth),
    qui évite les petites boucles qui gênent le décodage
  - codage systématique (les 91 bits du message apparaissent tels quels)
  - décodage par propagation de croyance (somme-produit), vectorisé :
    des centaines de trames décodées en même temps
"""
import numpy as np
import scipy.sparse as sp


def construire_peg(n, m, degres_var, graine=1):
    """Matrice de parité m x n par Progressive Edge Growth."""
    rng = np.random.default_rng(graine)
    var_chk = [[] for _ in range(n)]
    chk_var = [[] for _ in range(m)]
    ordre = np.argsort(degres_var, kind="stable")      # petits degrés d'abord
    for v in ordre:
        for e in range(degres_var[v]):
            if e == 0:
                candidats = list(range(m))
            else:
                # parcours en largeur depuis v : on cherche les checks
                # les plus éloignés (ou non atteints)
                vus_c = set(var_chk[v])
                front_c = set(var_chk[v])
                vus_v = {v}
                while True:
                    front_v = {u for c in front_c for u in chk_var[c]} - vus_v
                    vus_v |= front_v
                    nouv_c = {c for u in front_v for c in var_chk[u]} - vus_c
                    if not nouv_c or len(vus_c | nouv_c) == m:
                        reste = [c for c in range(m) if c not in vus_c]
                        candidats = reste if reste else [
                            c for c in range(m) if c not in var_chk[v]]
                        break
                    vus_c |= nouv_c
                    front_c = nouv_c
            deg = np.array([len(chk_var[c]) for c in candidats])
            meilleurs = [c for c, d in zip(candidats, deg) if d == deg.min()]
            c = meilleurs[rng.integers(len(meilleurs))]
            var_chk[v].append(c)
            chk_var[c].append(v)
    H = np.zeros((m, n), dtype=np.uint8)
    for v in range(n):
        H[var_chk[v], v] = 1
    return H


def generatrice(H):
    """Matrice génératrice systématique (k x n) et positions des bits info."""
    m, n = H.shape
    A = H.copy() % 2
    pivots = []
    r = 0
    for c in range(n):
        p = np.flatnonzero(A[r:, c])
        if p.size == 0:
            continue
        p = p[0] + r
        A[[r, p]] = A[[p, r]]
        autres = np.flatnonzero(A[:, c])
        autres = autres[autres != r]
        A[autres] ^= A[r]
        pivots.append(c)
        r += 1
        if r == m:
            break
    libres = [c for c in range(n) if c not in pivots]
    k = len(libres)
    G = np.zeros((k, n), dtype=np.uint8)
    for i, f in enumerate(libres):
        G[i, f] = 1
        for j, pc in enumerate(pivots):
            G[i, pc] = A[j, f]
    assert not ((G.astype(int) @ H.T.astype(int)) % 2).any()
    return G, np.array(libres)


class LDPC:
    def __init__(self, n=194, k=91, degre=3, graine=1, iterations=60):
        m = n - k
        degs = np.full(n, degre)
        self.H = construire_peg(n, m, degs, graine)
        G, libres = generatrice(self.H)
        # si H n'est pas de rang plein, on garde k positions libres
        # (les autres sont fixées à 0 : code « raccourci »)
        self.G = G[:k]
        self.info = libres[:k]
        self.n, self.k, self.iterations = n, k, iterations
        chk, var = np.nonzero(self.H)
        self.e_chk, self.e_var = chk, var
        E = chk.size
        self.S_var = sp.csr_matrix((np.ones(E), (var, np.arange(E))),
                                   shape=(n, E))
        self.S_chk = sp.csr_matrix((np.ones(E), (chk, np.arange(E))),
                                   shape=(m, E))

    def coder(self, bits):
        return ((bits.astype(np.int64) @ self.G) % 2).astype(np.int8)

    def decoder(self, llr, n_info=None):
        """llr : (F, n), positif = bit 0. Renvoie les bits info (F, k)."""
        F = llr.shape[0]
        llr = np.clip(llr, -40, 40)
        c2v = np.zeros((F, self.e_var.size))
        fini = np.zeros(F, bool)
        dec = (llr < 0).astype(np.int8)
        for _ in range(self.iterations):
            total = llr + (self.S_var @ c2v.T).T
            v2c = total[:, self.e_var] - c2v
            t = np.tanh(np.clip(v2c, -40, 40) / 2)
            a = np.maximum(np.abs(t), 1e-15)
            lg = np.log(a)
            neg = (t < 0).astype(float)
            som = (self.S_chk @ lg.T).T[:, self.e_chk] - lg
            par = (self.S_chk @ neg.T).T[:, self.e_chk] - neg
            prod = np.exp(som) * (1 - 2 * (np.round(par) % 2))
            nouveau = 2 * np.arctanh(np.clip(prod, -0.999999, 0.999999))
            c2v = np.where(fini[:, None], c2v, nouveau)
            total = llr + (self.S_var @ c2v.T).T
            dec = (total < 0).astype(np.int8)
            synd = (self.S_chk @ dec[:, self.e_var].T).T % 2
            fini = ~synd.any(1)
            if fini.all():
                break
        return dec[:, self.info]


def limite_theorique_esn0(n, k):
    """Es/N0 (dB) où un code (n, k) optimal en BPSK décode 50 % des trames.
    Approximation normale (Polyanskiy-Poor-Verdú) pour le canal BPSK-AWGN."""
    x, w = np.polynomial.hermite_e.hermegauss(80)
    w = w / w.sum()

    def cap_disp(esn0):
        mu = 4 * esn0                      # LLR ~ N(mu, 2 mu) pour bit 0
        L = mu + np.sqrt(2 * mu) * x
        i = 1 - np.logaddexp(0, -L) / np.log(2)    # information en bits
        C = (w * i).sum()
        V = (w * (i - C) ** 2).sum()
        return C, V

    from scipy.optimize import brentq

    def f(db):
        C, V = cap_disp(10 ** (db / 10))
        # 50 % d'erreur : Q^-1(0.5) = 0
        return n * C + 0.5 * np.log2(n) - k

    return brentq(f, -15, 10)
