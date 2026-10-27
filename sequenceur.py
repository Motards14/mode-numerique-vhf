# -*- coding: utf-8 -*-
"""
Séquenceur automatique des QSO — F4GOP

Déroulement d'un QSO (comme FT8) :

    Station qui lance appel (CQ)      Station qui répond
    -------------------------------   -------------------------------
    CQ F4GOP IN98QR
                                      F4GOP G4XYZ IO91WM   (locator)
    G4XYZ F4GOP -15        (report)
                                      F4GOP G4XYZ R-12     (R-report)
    G4XYZ F4GOP RR73       -> QSO enregistré
                                      F4GOP G4XYZ 73       -> QSO enregistré

Le séquenceur ne regarde que les messages qui nous sont adressés et qui
viennent du correspondant en cours. Sans réponse après un certain nombre
d'émissions, il abandonne.
"""
import time

REPOS, CQ, APPEL, REPORT, RREPORT, RR73, FIN73 = (
    "repos", "cq", "appel", "report", "r-report", "rr73", "73")

LIBELLES = {
    REPOS: "aucun QSO en cours",
    CQ: "appel CQ",
    APPEL: "j'appelle {dx}",
    REPORT: "report envoyé à {dx}",
    RREPORT: "R-report envoyé à {dx}",
    RR73: "RR73 envoyé à {dx}",
    FIN73: "73 envoyé à {dx}",
}


def _est_locator(t):
    t = t.upper()
    return (len(t) in (4, 6) and "A" <= t[0] <= "R" and "A" <= t[1] <= "R"
            and t[2:4].isdigit()
            and (len(t) == 4 or all("A" <= c <= "X" for c in t[4:])))


def _est_report(t):
    return len(t) >= 2 and t[0] in "+-" and t[1:].isdigit()


def _est_rreport(t):
    return t.startswith("R") and _est_report(t[1:])


def _borne(snr):
    return max(-50, min(49, int(snr)))


class Sequenceur:
    def __init__(self, moi, locator, max_repetitions=6, max_cq=40):
        self.moi = moi.strip().upper()
        self.locator = locator.strip().upper()
        self.max_rep = max_repetitions
        self.max_cq = max_cq
        self.cq_apres_qso = False
        self.qsos_finis = []           # fiches à enregistrer dans le journal
        self._raz(REPOS)

    # ------------------------------------------------------------ état
    def _raz(self, etat):
        self.etat = etat
        self.dx = None
        self.dx_loc = ""
        self.rep_envoye = None
        self.rep_recu = None
        self.debut = None
        self.enregistre = False
        self.repetitions = 0
        self.message = None
        if etat == CQ:
            self.message = f"CQ {self.moi} {self.locator}"

    def _changer(self, etat, message):
        if etat != self.etat:
            self.repetitions = 0
        self.etat = etat
        self.message = message
        if self.debut is None and self.dx:
            self.debut = time.time()
        return True

    def libelle(self):
        return LIBELLES[self.etat].format(dx=self.dx or "")

    def actif(self):
        return self.etat != REPOS

    # ------------------------------------------------------------ commandes
    def lancer_cq(self):
        self._raz(CQ)
        return self.message

    def arreter(self):
        self._raz(REPOS)

    def repondre_a(self, dx, snr, dx_loc=""):
        """On appelle une station (qui faisait CQ) : on envoie notre locator."""
        self._raz(APPEL)
        self.dx = dx.upper()
        self.dx_loc = dx_loc
        self.rep_envoye = _borne(snr)
        self.debut = time.time()
        self.message = f"{self.dx} {self.moi} {self.locator}"
        return self.message

    def reprendre(self, texte, snr):
        """Double-clic sur un message qui nous est adressé : on reprend le
        QSO à l'étape correspondante."""
        mots = texte.upper().split()
        if len(mots) < 2 or mots[0] != self.moi:
            return None
        fin = mots[2] if len(mots) > 2 else ""
        self._raz(CQ if _est_locator(fin) or not fin else APPEL)
        self.dx = mots[1]
        self.debut = time.time()
        self.traiter([{"texte": texte, "snr": snr}])
        return self.message

    # ------------------------------------------------------------ réception
    def traiter(self, decodages):
        """Après chaque période de réception. Renvoie True si le message à
        émettre a changé (lire alors self.message ; None = arrêter)."""
        pour_moi = []
        for d in decodages:
            mots = d["texte"].upper().split()
            if len(mots) >= 2 and mots[0] == self.moi:
                pour_moi.append((d["snr"], mots[1],
                                 mots[2] if len(mots) > 2 else ""))
        if not pour_moi or self.etat == REPOS:
            return False
        if self.etat == CQ:
            # plusieurs réponses à notre CQ : on prend la plus forte
            pour_moi.sort(reverse=True)
            snr, dx, fin = pour_moi[0]
            if _est_locator(fin) or not fin:
                self.dx, self.dx_loc = dx, fin
                self.rep_envoye = _borne(snr)
                return self._changer(REPORT, f"{dx} {self.moi} "
                                             f"{self.rep_envoye:+03d}")
            if _est_report(fin):                  # il a sauté le locator
                self.dx, self.rep_recu = dx, fin
                self.rep_envoye = _borne(snr)
                return self._changer(RREPORT, f"{dx} {self.moi} "
                                              f"R{self.rep_envoye:+03d}")
            return False
        msgs = [(s, f) for s, dx, f in pour_moi if dx == self.dx]
        if not msgs:
            return False
        snr, fin = msgs[0]
        if self.etat == APPEL:
            if _est_report(fin):
                self.rep_recu = fin
                self.rep_envoye = _borne(snr)
                return self._changer(RREPORT, f"{self.dx} {self.moi} "
                                              f"R{self.rep_envoye:+03d}")
            if _est_rreport(fin):
                self.rep_recu = fin[1:]
                return self._changer(RR73, f"{self.dx} {self.moi} RR73")
            if fin in ("RR73", "RRR"):
                return self._changer(FIN73, f"{self.dx} {self.moi} 73")
        elif self.etat == REPORT:
            if _est_rreport(fin):
                self.rep_recu = fin[1:]
                return self._changer(RR73, f"{self.dx} {self.moi} RR73")
            if fin in ("RR73", "RRR", "73"):
                self.rep_recu = self.rep_recu or ""
                return self._changer(FIN73, f"{self.dx} {self.moi} 73")
        elif self.etat == RREPORT:
            if fin in ("RR73", "RRR"):
                return self._changer(FIN73, f"{self.dx} {self.moi} 73")
            if fin == "73":
                self._terminer()
                return True
        elif self.etat == RR73:
            if fin == "73":
                self._terminer()
                return True
        elif self.etat == FIN73:
            if fin in ("RR73", "RRR"):            # il n'a pas eu notre 73
                self.repetitions = 0
        return False

    # ------------------------------------------------------------ émission
    def apres_emission(self):
        """Après chaque émission. Renvoie le prochain message à émettre, ou
        None s'il faut arrêter d'émettre. Les QSO terminés sont ajoutés à
        self.qsos_finis (à récupérer avec prendre_qsos)."""
        self.repetitions += 1
        if self.etat in (RR73, FIN73):
            self._enregistrer()
        if self.etat == FIN73:
            return self._terminer()          # le 73 final n'est envoyé qu'une fois
        limite = self.max_cq if self.etat == CQ else self.max_rep
        if self.etat != REPOS and self.repetitions >= limite:
            self._raz(REPOS)
        return self.message

    def prendre_qsos(self):
        q, self.qsos_finis = self.qsos_finis, []
        return q

    def _enregistrer(self):
        if self.dx and not self.enregistre:
            self.qsos_finis.append(self._fiche())
            self.enregistre = True

    def _terminer(self):
        self._enregistrer()
        self._raz(CQ if self.cq_apres_qso else REPOS)
        return self.message

    def _fiche(self):
        return {
            "call": self.dx,
            "grid": self.dx_loc if _est_locator(self.dx_loc) else "",
            "rst_sent": f"{self.rep_envoye:+03d}"
            if self.rep_envoye is not None else "",
            "rst_rcvd": self.rep_recu or "",
            "debut": self.debut or time.time(),
            "fin": time.time(),
        }
