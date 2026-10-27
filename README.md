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

**Prochaines étapes**
1. Estimation réelle de la phase (oscillateurs qui dérivent, GPSDO ou non)
2. Code correcteur LDPC moderne (+1 à 2 dB attendus)
3. Programme Windows : audio et CAT pour Kenwood TS-890 / TS-990,
   waterfall, séquençage automatique des QSO

## Lancer le simulateur

```
pip install numpy scipy
python simulateur.py
```
