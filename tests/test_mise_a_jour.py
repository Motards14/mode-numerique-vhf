# -*- coding: utf-8 -*-
"""Test de la mise à jour automatique avec un faux serveur GitHub local.
Usage : xvfb-run -a python tests/test_mise_a_jour.py"""
import hashlib, http.server, json, os, sys, tempfile, threading, time

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, ".."))
os.environ["HOME"] = tempfile.mkdtemp()
dossier = tempfile.mkdtemp()
NOUVEL_EXE = b"MZ-faux-programme-version-9.9.0" * 50000
SHA = hashlib.sha256(NOUVEL_EXE).hexdigest()


class Serveur(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/latest":
            port = self.server.server_address[1]
            corps = json.dumps({"tag_name": "v9.9.0", "body": "- nouveautés de test",
                                "html_url": "http://exemple/v9.9.0",
                                "assets": [{"name": "F4GOP-VHF.exe", "size": len(NOUVEL_EXE),
                                            "digest": "sha256:" + SHA,
                                            "browser_download_url": f"http://127.0.0.1:{port}/exe"}]}).encode()
        else:
            corps = NOUVEL_EXE
        self.send_response(200)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Serveur)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["F4GOP_VHF_UPDATE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/latest"

import updater                                            # noqa: E402
updater.LATEST_URL = os.environ["F4GOP_VHF_UPDATE_URL"]
# on se fait passer pour l'exe installé
exe = os.path.join(dossier, "F4GOP-VHF.exe")
open(exe, "wb").write(b"ancienne version 2.1")
sys.frozen = True
sys.executable = exe
lances = []
import types                                              # noqa: E402
updater.subprocess = types.SimpleNamespace(Popen=lambda args, **kw: lances.append(args))
updater.WIN = True                                        # on simule Windows
updater.ASSET_NAME = "F4GOP-VHF.exe"

import f4gop_vhf as A                                     # noqa: E402
from tkinter import messagebox                            # noqa: E402
A.sd = None
A.FICHIER_REGLAGES = os.path.join(os.environ["HOME"], ".f4gop_vhf.json")
messagebox.askyesno = lambda *a, **k: True
app = A.Application()
app.geometry("1400x900+0+0")
etapes = []


def suivre():
    t = app.l_bandeau.cget("text")
    if t and (not etapes or etapes[-1] != t):
        etapes.append(t)
        if len(etapes) == 1:
            os.system("import -window root " + os.path.join(ICI, "..", "captures", "bandeau_maj.png"))
            app._clic_maj()
    app.after(100, suivre)


quitte = []
ancien_quitter = app.quitter
app.quitter = lambda: (quitte.append(1), ancien_quitter())
app.after(500, suivre)
app.after(20000, ancien_quitter)
app.mainloop()
for e in etapes:
    print("bandeau :", e)
contenu = open(exe, "rb").read()
print("exe remplacé par la nouvelle version :", contenu == NOUVEL_EXE)
print("ancien exe gardé en .old :", os.path.exists(exe + ".old"))
print("nouvelle version relancée :", lances)
print("programme fermé pour redémarrer :", bool(quitte))
