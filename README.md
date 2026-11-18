# TuneBloom-Py

Réécriture en Python de [TuneBloom](https://github.com/) (éditeur d'archives sonores Wii U **BFSAR**).
Interface web locale qui reproduit la disposition du TuneBloom d'origine (mêmes polices Space Mono + Lucide, mêmes panneaux).
Aucun compilateur, aucune bibliothèque graphique : Python 3.9+ et un navigateur. `numpy` uniquement pour jouer les séquences.

## Lancer
    python -m tunebloom                      # ouvre l'interface dans le navigateur
    python -m tunebloom gui archive.bfsar
Le serveur reste local (127.0.0.1) et s'arrête quand l'onglet est fermé. File > Open ouvre un navigateur de fichiers.
Jeux à BFGRP externes (SM3DW) : **File > Add BFGRP** (ou `--grp x.bfgrp` en ligne de commande), sinon sons/séquences/banques indisponibles ; streams `stream/*.bfstm` à placer à côté du BFSAR.
Clavier de l'éditeur de banque : cliquer une touche joue la note avec l'instrument sélectionné.

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
**Lecture** : BFSAR / BFGRP / BFWAR / BFWSD / BFBNK / BFSEQ / BFWAV ; décodage DSP-ADPCM, PCM16, PCM8 (84 banques, 109 séquences, 3 320 vagues sans erreur).

**Écriture, vérifiée sur de vrais fichiers**
- Compilateur MML : les **109 BFSEQ réels** (NSMBU + SM3DW) se recompilent à l'identique, octet pour octet. Édition dans l'interface
  (double-clic sur le code, bouton disquette ou Ctrl+S), erreurs avec numéro de ligne, offsets de départ des sons recalés
  (labels `Entry_XXXX` automatiques pour les départs sans label).
- Banques : valeur de chaque région modifiable (clé d'origine, volume, pan, pitch, key group, interpolation, ADSHR) ; sauvegarde puis relecture vérifiées.
- Sons : volume, remote filter, player, pitch (streams). Remplacement d'un son Wave par un WAV (encodeur DSP-ADPCM identique au C++).
- Reconstruction BFWAR / BFGRP identique octet pour octet ; BFSAR de 270 Mo relu après modification ; chemin rapide (écriture sur place) si la taille ne change pas.

**Non vérifié** : décodage BFSTM (aucun .bfstm fourni) ; séquenceur (rendu approximatif : pas de LFO, portamento, filtres ; hauteur/niveaux non validés à l'oreille) ;
comportement en jeu d'un BFSAR modifié.

**Pas encore porté** : renommer / ajouter / supprimer des éléments (exige la reconstruction de la table de chaînes et de l'arbre Patricia du BFSAR),
File > New (BFSAR créé de zéro), import WAV → BFSTM, édition des autres champs de son (pan, player param, 3D…), mutation des BFGRP externes,
lecture de séquence avec suivi des lignes/pistes en temps réel, System Window.

## Exécutables (GitHub Actions)
Poussez le dépôt : l'onglet **Actions** construit Windows / Linux / macOS (Intel + ARM) via PyInstaller (`--add-data` des fichiers web inclus).
En local : `pip install pyinstaller numpy` puis
`pyinstaller --onefile --windowed --name TuneBloom-Py --add-data "tunebloom/web:tunebloom/web" run_tunebloom.py` (Windows : `;` au lieu de `:`).

## Crédits
Encodeur DSP-ADPCM et écrivain BFWAV : « TuneBloom-Python » (MIT, `LICENSE-nwlib.txt`). Polices Space Mono (OFL) et Lucide (ISC) issues du dépôt TuneBloom.
