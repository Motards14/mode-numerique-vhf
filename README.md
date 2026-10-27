# Mode numérique VHF/UHF — F4GOP

Projet de mode numérique pour la VHF/UHF, dans l'esprit de FT8 / Q65,
mais conçu pour décoder des signaux plus faibles grâce à la
**démodulation cohérente** (les trajets tropo VHF/UHF sont bien plus
stables en phase que les trajets HF).

Auteur : Denis F4GOP (IN98QR) — f4gop.denis@gmail.com

## État du projet

**Étape 0 — Simulateur (fait)**
`simulateur.py` compare les modulations à message égal (77 bits utiles
+ CRC, comme FT8) et à code correcteur égal. Seuils de décodage (50 %),
SNR dans 2500 Hz :

| Modulation                              | 10,4 s   | 60 s     |
|-----------------------------------------|----------|----------|
| 8-FSK non cohérent (principe FT8 / Q65) | −20,0 dB | −27,4 dB |
| BPSK cohérent (phase idéale)            | −23,9 dB | −31,5 dB |

Gain d'environ **4 dB** pour la démodulation cohérente, avec une phase
parfaitement connue.

**Étape 1 — Phase réelle (fait)**
`simulateur_phase.py` : le récepteur retrouve lui-même la fréquence et
la phase (pilotes 1 symbole sur 4, FFT, moyenne glissante, puis 2e passe
assistée par les bits décodés). La 8-FSK de référence paie la même part
de synchro que FT8 (21 symboles sur 79). Gain du BPSK cohérent :

| Stabilité (temps de cohérence Tc)   | Trame 10,4 s | Trame 60 s |
|-------------------------------------|--------------|------------|
| GPSDO, tropo stable (1000 s)        | +4,1 dB      | +4,1 dB    |
| bon TCXO (30 s)                     | +3,9 dB      | +3,9 dB    |
| oscillateur moyen (3 s)             | +3,5 dB      | +2,2 dB    |
| très instable / scatter (0,5 s)     | +2,0 dB      | −2,8 dB    |

Conclusion : la démodulation cohérente garde l'essentiel de son gain
dès que la phase est un peu stable. Quand elle bouge trop vite pour
une trame longue, elle devient moins bonne que la FSK : le programme
devra mesurer la stabilité du signal et basculer tout seul vers un
mode non cohérent dans ce cas.

Résultats détaillés : `resultats_phase.txt`.

**Étape 2 — Code correcteur (fait)**
- `ldpc.py` : LDPC (194, 91) construit par PEG, décodage somme-produit.
  À cette petite taille de message il fait *moins bien* que le code
  convolutif (FT8 doit lui ajouter un décodeur OSD très lourd). Gardé
  pour de futurs messages longs.
- `convolutif.py` : codes convolutifs K=7, 9, 11. Le **K=11** gagne
  environ 0,6 dB sur le K=7 et se place à **0,3 dB de la limite
  théorique** pour 91 bits (approximation normale, −24,8 dB en 10,4 s).

Résultats avec phase réelle et code K=11 (`resultats_K11.txt`), même
code pour la référence de type FT8 :

| Trame  | Type FT8 | IC-9700 TCXO interne | IC-9700 + GPSDO |
|--------|----------|----------------------|-----------------|
| 10,4 s | −18,9 dB | **−23,0 dB** (+4,1)  | −22,9 dB (+4,0) |
| 60 s   | −26,6 dB | **−30,2 dB** (+3,6)  | −30,6 dB (+4,0) |

**Étape 3a — Émission (fait)**
- `message.py` : messages sur 77 bits + CRC-14. Types : standard
  (« CQ F4GOP IN98 », « F4ABC F4GOP -12 », R-report, RRR, RR73, 73),
  **locator 6 caractères** (« CQ F4GOP IN98QR ») et texte libre
  (13 caractères).
- `modem.py` : modulation **MSK cohérente** (OQPSK demi-sinus) :
  mêmes performances que le BPSK des simulations, mais **enveloppe
  constante** comme FT8 → l'émetteur sort toute sa puissance.
  Code K=11, 1 pilote tous les 4 bits, 272 bits émis.

| Sous-mode | Période | Émission | Largeur | Seuil mesuré (boucle audio) |
|-----------|---------|----------|---------|-----------------------------|
| R15       | 15 s    | 12,8 s   | ~25 Hz  | ≈ −24 dB                    |
| R60       | 60 s    | 55,5 s   | ~6 Hz   | ≈ −30 dB                    |

- `radio.py` : PTT et lecture de fréquence de l'IC-9700 par CI-V.
- `emetteur.py` : fenêtre d'émission (station, port CI-V, carte son,
  sous-mode, période paire/impaire, boutons CQ / Locator / Report /
  R+report / RR73 / 73, arrêt immédiat, export WAV).
- `exemples/` : un CQ en WAV et son spectre.

![Spectre R15](exemples/spectre_R15.png)

**Prochaines étapes**
3b. Réception : recherche des signaux dans le waterfall, décodage
3c. Séquençage automatique des QSO, puis .exe Windows

## Utiliser l'émetteur (Windows)

```
pip install -r requirements.txt
python emetteur.py
```

Réglages de l'IC-9700 : mode **USB-D**, menu *Connectors* :
CI-V USB Port = *Unlink from [REMOTE]*, CI-V USB Baud Rate = 115200,
CI-V Address = A2h, DATA MOD = USB. L'horloge du PC doit être à
l'heure exacte (synchronisation Internet), comme pour FT8.

Premiers essais : bouton « Tester PTT » sur charge fictive, puis
niveau audio réglé pour que l'ALC ne bouge pas.

## Lancer le simulateur

```
pip install numpy scipy matplotlib
python simulateur.py
python simulateur_phase.py 11      # K = 7, 9 ou 11
```
