# -*- coding: utf-8 -*-
"""
Codage des messages — F4GOP
Chaque message tient dans 77 bits, plus un CRC de 14 bits = 91 bits.

Type 0 — standard (comme FT8) :
    « CQ F4GOP IN98 », « F4ABC F4GOP -12 », « F4GOP F4ABC R-08 »,
    « F4ABC F4GOP RR73 », « F4ABC F4GOP 73 », « F4ABC F4GOP RRR »
    indicatif 1 (28 bits) + indicatif 2 (28) + R (1) + locator/report (15)
Type 1 — texte libre, 13 caractères max (A-Z 0-9 espace + - . / ?)
Type 2 — locator 6 caractères, très utile en VHF/UHF :
    « CQ F4GOP IN98QR », « F4ABC F4GOP IN98QR »
    1er indicatif sous forme abrégée (hash 21 bits) : la station appelée
    le reconnaît puisque c'est le sien ; les autres le retrouvent s'ils
    l'ont déjà décodé.

Limite actuelle : indicatifs « standard » de 6 caractères max
(pas encore de /P ni de préfixe F/ON4ABC).
"""
import hashlib

A37 = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
A36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
A10 = "0123456789"
A27 = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TEXTE = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./?"
JETONS = ["CQ", "QRZ", "DE"]
NB_PAYLOAD = 77
NB_TOTAL = 91

# champ 15 bits : locators 4 car., puis reports et mots spéciaux
NB_GRID4 = 18 * 18 * 10 * 10                    # 32400
REPORT_MIN, REPORT_MAX = -50, 49
G_RRR = NB_GRID4 + 100
G_RR73, G_73, G_VIDE = G_RRR + 1, G_RRR + 2, G_RRR + 3


class ErreurMessage(ValueError):
    pass


# ---------------- indicatifs ----------------
def _normaliser(indicatif):
    c = indicatif.strip().upper()
    if not 3 <= len(c) <= 6:
        raise ErreurMessage(f"indicatif « {indicatif} » : 3 à 6 caractères")
    if len(c) >= 3 and c[2].isdigit():
        pass
    elif c[1].isdigit():
        c = " " + c                              # ex. F4GOP -> " F4GOP"
    else:
        raise ErreurMessage(f"indicatif « {indicatif} » non standard")
    c = c.ljust(6)
    if len(c) > 6:
        raise ErreurMessage(f"indicatif « {indicatif} » trop long")
    return c


def coder_indicatif(indicatif):
    """Indicatif ou jeton (CQ, QRZ, DE) -> entier 28 bits."""
    s = indicatif.strip().upper()
    if s in JETONS:
        return JETONS.index(s)
    c = _normaliser(s)
    try:
        n = A37.index(c[0])
        n = n * 36 + A36.index(c[1])
        n = n * 10 + A10.index(c[2])
        for ch in c[3:]:
            n = n * 27 + A27.index(ch)
    except ValueError:
        raise ErreurMessage(f"indicatif « {indicatif} » : caractère invalide")
    return n + len(JETONS)


def decoder_indicatif(n):
    if n < len(JETONS):
        return JETONS[n]
    n -= len(JETONS)
    car = []
    for _ in range(3):
        n, r = divmod(n, 27)
        car.append(A27[r])
    n, r = divmod(n, 10)
    car.append(A10[r])
    n, r = divmod(n, 36)
    car.append(A36[r])
    car.append(A37[n])
    return "".join(reversed(car)).strip()


def hash21(indicatif):
    """Forme abrégée d'un indicatif sur 21 bits (0..2 réservés aux jetons)."""
    s = indicatif.strip().upper()
    if s in JETONS:
        return JETONS.index(s)
    h = int.from_bytes(hashlib.sha1(s.encode()).digest()[:4], "big")
    return len(JETONS) + h % ((1 << 21) - len(JETONS))


# ---------------- locators ----------------
def _est_grid4(g):
    g = g.upper()
    return (len(g) == 4 and "A" <= g[0] <= "R" and "A" <= g[1] <= "R"
            and g[2].isdigit() and g[3].isdigit())


def _est_grid6(g):
    g = g.upper()
    return _est_grid4(g[:4]) and len(g) == 6 and all(
        "A" <= ch <= "X" for ch in g[4:])


def _grid4(g):
    g = g.upper()
    return ((ord(g[0]) - 65) * 18 + ord(g[1]) - 65) * 100 + int(g[2:4])


def _grid4_txt(n):
    a, r = divmod(n, 100)
    l1, l2 = divmod(a, 18)
    return f"{chr(65 + l1)}{chr(65 + l2)}{r:02d}"


def _report(tok):
    """'-12', '+05', 'R-08' -> (R, valeur) ou None."""
    r = tok.startswith("R") and len(tok) > 1 and tok[1] in "+-"
    t = tok[1:] if r else tok
    if len(t) >= 2 and t[0] in "+-" and t[1:].isdigit():
        v = int(t)
        if REPORT_MIN <= v <= REPORT_MAX:
            return r, v
    return None


# ---------------- assemblage ----------------
def _bits(valeur, n):
    return [(valeur >> (n - 1 - i)) & 1 for i in range(n)]


def _entier(bits):
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def crc14(bits):
    """CRC 14 bits (polynôme 0x2757, celui de FT8)."""
    reg = 0
    for b in list(bits) + [0] * 14:
        reg = (reg << 1) | int(b)
        if reg & (1 << 14):
            reg ^= 0x2757 | (1 << 14)
    return reg & 0x3FFF


def coder_message(texte):
    """Texte -> liste de 91 bits (77 bits utiles + CRC)."""
    tok = texte.strip().upper().split()
    payload = None
    if 2 <= len(tok) <= 3:
        try:
            if len(tok) == 3 and _est_grid6(tok[2]):
                payload = (_bits(2, 3) + _bits(hash21(tok[0]), 21)
                           + _bits(coder_indicatif(tok[1]), 28)
                           + _bits(_grid4(tok[2][:4]) * 576
                                   + (ord(tok[2][4]) - 65) * 24
                                   + ord(tok[2][5]) - 65, 25))
            else:
                c1 = coder_indicatif(tok[0])
                c2 = coder_indicatif(tok[1])
                r, g = 0, G_VIDE
                if len(tok) == 3:
                    t = tok[2]
                    rep = _report(t)
                    if rep:
                        r, g = int(rep[0]), NB_GRID4 + rep[1] - REPORT_MIN
                    elif t in ("RRR", "RR73", "73"):
                        g = {"RRR": G_RRR, "RR73": G_RR73, "73": G_73}[t]
                    elif t.startswith("R") and _est_grid4(t[1:]):
                        r, g = 1, _grid4(t[1:])
                    elif _est_grid4(t):
                        g = _grid4(t)
                    else:
                        raise ErreurMessage("3e mot non reconnu")
                payload = (_bits(0, 3) + _bits(c1, 28) + _bits(c2, 28)
                           + [r] + _bits(g, 15) + [0, 0])
        except ErreurMessage:
            payload = None
    if payload is None:
        t = " ".join(tok)
        if len(t) > 13 or any(ch not in TEXTE for ch in t):
            raise ErreurMessage(
                "message non reconnu : texte libre limité à 13 caractères "
                "(A-Z 0-9 espace + - . / ?)")
        n = 0
        for ch in t.rjust(13):
            n = n * 42 + TEXTE.index(ch)
        payload = _bits(1, 3) + _bits(n, 71) + [0, 0, 0]
    assert len(payload) == NB_PAYLOAD
    return payload + _bits(crc14(payload), 14)


def decoder_message(bits, carnet=None):
    """91 bits -> texte, ou None si le CRC est faux.
    carnet : dict {hash21: indicatif} pour retrouver les indicatifs abrégés."""
    bits = [int(b) for b in bits]
    payload, crc = bits[:NB_PAYLOAD], _entier(bits[NB_PAYLOAD:])
    if crc14(payload) != crc:
        return None
    typ = _entier(payload[:3])
    if typ == 0:
        c1 = decoder_indicatif(_entier(payload[3:31]))
        c2 = decoder_indicatif(_entier(payload[31:59]))
        r, g = payload[59], _entier(payload[60:75])
        if g < NB_GRID4:
            fin = ("R" if r else "") + _grid4_txt(g)
        elif g < G_RRR:
            fin = ("R" if r else "") + f"{g - NB_GRID4 + REPORT_MIN:+03d}"
        else:
            fin = {G_RRR: "RRR", G_RR73: "RR73", G_73: "73"}.get(g, "")
        return " ".join(x for x in (c1, c2, fin) if x)
    if typ == 1:
        n = _entier(payload[3:74])
        car = []
        for _ in range(13):
            n, r = divmod(n, 42)
            car.append(TEXTE[r])
        return "".join(reversed(car)).strip()
    if typ == 2:
        h = _entier(payload[3:24])
        c1 = JETONS[h] if h < len(JETONS) else (carnet or {}).get(h, "<...>")
        c2 = decoder_indicatif(_entier(payload[24:52]))
        n = _entier(payload[52:77])
        g4, sub = divmod(n, 576)
        s1, s2 = divmod(sub, 24)
        return f"{c1} {c2} {_grid4_txt(g4)}{chr(65 + s1)}{chr(65 + s2)}"
    return None
