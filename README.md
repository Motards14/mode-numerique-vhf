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

**Étape 3b — Réception (fait)**
- `decodeur.py` : recherche des signaux sans rien connaître d'avance
  (fréquence 200–2800 Hz, décalage d'horloge −0,5 à +1,5 s) en
  additionnant les pilotes de façon cohérente, puis démodulation fine
  et décodage de tous les candidats en un seul passage. Le CRC 14 bits
  élimine les faux décodages.
- `station.py` : **programme complet** émission + réception —
  waterfall (clic = fréquence d'émission), liste des messages (en
  rouge ceux qui te sont adressés, en vert les CQ), double-clic pour
  répondre (locator, report, R-report, RR73, 73 selon l'étape du QSO).
- `tests/test_decodeur.py` : test sur périodes synthétiques
  (résultats dans `tests/resultats_decodeur.txt`).

| Sous-mode | Décodage à 50 %  | Temps de décodage | Faux décodages (bruit seul) |
|-----------|------------------|-------------------|-----------------------------|
| R15       | ≈ −23,5 dB       | 0,6 à 1,1 s       | 0 sur 30 périodes           |
| R60       | ≈ −30 dB         | 1,8 à 4 s         |                             |

Le décodage démarre dès la fin du signal le plus tardif possible
(14,85 s en R15, 57,5 s en R60), et l'émission peut partir jusqu'à
1,2 s après le début de période : on a le temps de répondre.

**Étape 3c — QSO automatique, journal, .exe (fait)**
- `sequenceur.py` : déroulement automatique des QSO (CQ → locator →
  report → R-report → RR73 → 73), reprise si un message est perdu,
  abandon après 6 émissions sans réponse
  (`tests/test_sequenceur.py`).
- `journal_adif.py` : chaque QSO est enregistré dans
  `Documents\F4GOP-VHF\journal.adi` (bande et fréquence lues sur
  l'IC-9700). Ce mode étant nouveau, il est noté MODE=MFSK,
  SUBMODE=F4GOP-VHF : certains logiciels ou LoTW peuvent refuser ce
  sous-mode inconnu.
- Test de bout en bout : deux stations complètes ont fait un QSO entier
  entre elles, avec de vrais signaux bruités à −18 dB, et l'ont
  chacune enregistré.
- `.github/workflows/exe-windows.yml` : GitHub construit
  **F4GOP-VHF.exe** sur Windows à chaque nouvelle version et le publie
  dans les **Releases**.

## Utiliser le programme (Windows)

**Le plus simple** : télécharger **F4GOP-VHF.exe** dans la rubrique
*Releases* du dépôt (colonne de droite) et double-cliquer. Rien à
installer.

Pour un QSO :
1. Choisir le port CI-V, la carte son de sortie et l'entrée son
   (« USB Audio CODEC »), le sous-mode R15 ou R60.
2. Cocher « Séquençage automatique ».
3. Soit **Lancer CQ**, soit **double-cliquer** sur un CQ reçu : le QSO
   se déroule tout seul et s'enregistre dans le journal.

Depuis les sources :
```
pip install -r requirements.txt
python station.py          # émission + réception
```
(`emetteur.py` seul reste disponible pour des essais d'émission.)

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
