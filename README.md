# TuneBloom-Py

Réécriture **partielle** en Python pur (aucune dépendance, bibliothèque standard uniquement) de
[TuneBloom](https://github.com/) pour les archives sonores Wii U **BFSAR**.

## Ce qui fonctionne
- Lecture du BFSAR : sons, banques, archives de vagues (BFWAR), groupes, players, table des fichiers, noms.
- Extraction de tous les fichiers internes (`.bfstm`, `.bfwar`, `.bfseq`, `.bfbnk`, `.bfwsd`, `.bfgrp`…).
- Décodage **BFSTM** et **BFWAV** (DSP-ADPCM, PCM16, PCM8) → WAV, et lecture dans l'interface.
- **Remplacement** d'un fichier interne (le BFSAR est réécrit, offsets/tailles recalculés).
- Interface Tkinter + ligne de commande.

## Ce qui n'est PAS (encore) porté
Éditeur de séquences BFSEQ, éditeur de banques BFBNK, interprétation des BFWSD (wave sounds),
lecture de séquences/synthèse, import WAV → BFSTM/BFWAV (encodeur DSP-ADPCM), édition des propriétés
(volume, player, boucles…) et réécriture complète du BFSAR depuis zéro (table Patricia, etc.).
Testé uniquement sur des fichiers synthétiques (`tests/`), pas sur de vrais BFSAR.

## Utilisation (sans compiler)
    python -m tunebloom                       # interface graphique
    python -m tunebloom list    archive.bfsar
    python -m tunebloom extract archive.bfsar sortie/ --wav
    python -m tunebloom wav     son.bfstm son.wav
    python -m tunebloom replace archive.bfsar 3 nouveau.bfstm -o archive_modifiee.bfsar

Python 3.9+ ; Tkinter requis pour l'interface (Linux : `sudo apt install python3-tk`).
Lecture audio : Windows = `winsound`, macOS = `afplay`, Linux = `paplay`/`aplay`/`ffplay`.

## Créer des exécutables
### Via GitHub (recommandé : Windows, Linux, macOS Intel + ARM d'un coup)
1. Créez un dépôt GitHub et poussez ce dossier (`git init && git add . && git commit -m init && git push`).
2. Onglet **Actions** : le workflow *Build TuneBloom-Py* se lance seul (ou « Run workflow »).
3. Téléchargez les exécutables dans *Artifacts* en bas de l'exécution.
4. Pour publier une release : `git tag v0.1.0 && git push --tags` (zips attachés automatiquement).

### En local (PyInstaller, ~10 Mo, pas de Visual Studio)
    python -m pip install pyinstaller
    pyinstaller --onefile --windowed --name TuneBloom-Py run_tunebloom.py
Résultat dans `dist/`. PyInstaller ne fait pas de cross-compilation : un build par OS.
macOS : au premier lancement, clic droit → Ouvrir (binaire non signé).
