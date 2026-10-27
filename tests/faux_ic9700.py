# -*- coding: utf-8 -*-
"""Faux Icom IC-9700 sur un port série virtuel (Linux) pour les tests."""
import os, threading, tty


class FauxIC9700:
    def __init__(self, muet=False, adresse=0xA2, freq=144174000):
        self.m, s = os.openpty()
        tty.setraw(self.m)
        self.port = os.ttyname(s)
        self.adresse, self.freq, self.muet = adresse, freq, muet
        self.journal = []
        self.ptt = False
        threading.Thread(target=self._boucle, daemon=True).start()

    def _repondre(self, octets):
        os.write(self.m, bytes([0xFE, 0xFE, 0xE0, self.adresse]) + bytes(octets) + b"\xFD")

    def _boucle(self):
        buf = b""
        while True:
            try:
                buf += os.read(self.m, 64)
            except OSError:
                return
            while b"\xFD" in buf:
                t, buf = buf.split(b"\xFD", 1)
                t = t[t.find(b"\xFE\xFE") + 2:]
                if self.muet or t[:2] != bytes([self.adresse, 0xE0]):
                    continue
                c = t[2:]
                if c[:1] == b"\x03":
                    f, bcd = self.freq, []
                    for _ in range(5):
                        f, r = divmod(f, 100)
                        bcd.append(((r // 10) << 4) | (r % 10))
                    self._repondre([0x03] + bcd)
                elif c[:1] == b"\x04":
                    self._repondre([0x04, 0x01, 0x01])
                elif c[:2] == b"\x1A\x06":
                    self._repondre([0x1A, 0x06, 0x01, 0x01])
                elif c[:2] == b"\x1C\x00":
                    self.ptt = bool(c[2])
                    self.journal.append("PTT " + ("ON" if c[2] else "OFF"))
                    self._repondre([0xFB])
                else:
                    self._repondre([0xFA])
