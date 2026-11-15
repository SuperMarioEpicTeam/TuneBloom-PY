# TuneBloom-Py

Réécriture en Python de [TuneBloom](https://github.com/) (éditeur d'archives sonores Wii U **BFSAR**).
Interface web locale qui reproduit la disposition du TuneBloom d'origine (mêmes polices Space Mono + Lucide, mêmes panneaux).
Aucun compilateur, aucune bibliothèque graphique : Python 3.9+ et un navigateur. `numpy` uniquement pour jouer les séquences.

## Lancer
    python -m tunebloom                      # ouvre l'interface dans le navigateur
    python -m tunebloom gui archive.bfsar
Le serveur reste local (127.0.0.1) et s'arrête quand l'onglet est fermé. File > Open ouvre un navigateur de fichiers.
Pour les jeux à BFGRP externes (SM3DW) : menu en ligne de commande `--grp x.bfgrp`; streams `stream/*.bfstm` à côté du BFSAR.

## Interface (copie de l'original)
Panneau Project (All Sounds, Stream/Wave/Sequence Sounds, Sound Sets, Banks, Wave Archives, Groups, Players, Wave/Sequence/Bank Files),
liste avec recherche (Ctrl+F), panneau Properties, éditeur de **banque** (instruments, régions sur clavier, ADSHR),
éditeur de **séquence** (MML désassemblé, syntaxe de l'original, labels), lecteur en bas.
Double-clic sur une banque ou une séquence = ouvre l'éditeur.

## Ligne de commande
    python -m tunebloom list archive.bfsar [--grp x.bfgrp]
    python -m tunebloom extract archive.bfsar sortie/ --wav
    python -m tunebloom sounds archive.bfsar sortie/ [--grp x.bfgrp]          # WAV de tous les sons Wave/Stream
    python -m tunebloom wav2bfwav son.wav son.bfwav --enc dspadpcm
    python -m tunebloom replace-wave archive.bfsar NOM_DU_SON nouveau.wav -o sortie.bfsar

## État réel (validé sur SM3DW et NSMBU)
**Vérifié sur de vrais fichiers** : lecture BFSAR/BFGRP/BFWAR/BFWSD/BFBNK/BFSEQ (84 banques, 77 séquences, 3 320 vagues sans erreur) ;
décodage BFWAV ; encodeur DSP-ADPCM identique octet pour octet au C++ ; reconstruction BFWAR/BFGRP identique octet pour octet ;
remplacement d'un son par un WAV (BFSAR de 270 Mo relu correctement) ; édition du volume / remote filter d'un son.

**Non vérifié** : décodage BFSTM (aucun .bfstm fourni) ; séquenceur (rendu fonctionnel mais approximatif : pas de LFO, portamento, filtres ;
hauteur et niveaux non validés à l'oreille) ; comportement en jeu d'un BFSAR modifié.

**Pas porté** : édition de la plupart des propriétés (champs grisés), éditeur de banque/séquence en écriture, compilateur MML,
import WAV → BFSTM, création de projet (File > New), System Window, lecture de séquence en temps réel avec suivi de lignes/pistes.

## Exécutables (GitHub Actions)
Poussez le dépôt : l'onglet **Actions** construit Windows / Linux / macOS (Intel + ARM) via PyInstaller (`--add-data` des fichiers web inclus).
En local : `pip install pyinstaller numpy` puis
`pyinstaller --onefile --windowed --name TuneBloom-Py --add-data "tunebloom/web:tunebloom/web" run_tunebloom.py` (Windows : `;` au lieu de `:`).

## Crédits
Encodeur DSP-ADPCM et écrivain BFWAV : « TuneBloom-Python » (MIT, `LICENSE-nwlib.txt`). Polices Space Mono (OFL) et Lucide (ISC) issues du dépôt TuneBloom.
