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
    python -m tunebloom wav2bfstm son.wav son.bfstm [--loop-start N]
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

**BFSTM** (vérifié sur `STM_RC_BGM_BEACH.bfstm` de SM3DW) : décodage (durée 67,981 s = celle de TuneBloom, 4 canaux, boucle), lecture avec marqueurs de boucle, **reconstruction identique octet pour octet** du fichier de 5 Mo, import WAV → BFSTM (`wav2bfstm`, boucle optionnelle ; disposition v3.0.0).
- Menu clic droit **Replace / Export** sur les sons (comme l'original).

**Édition structurelle (validée sur SM3DW et NSMBU)**
- Bloc de chaînes + arbre Patricia reconstruits **à l'identique octet pour octet** sur les 3 archives réelles (BgmData, SeData, NSMBU 270 Mo).
- **Renommer** (sons, jeux de sons, banques, archives, groupes, players), **dupliquer** un son, **ajouter un son Stream** (File > Add Stream Sound…, clic droit > Rename / Duplicate).
  Audit sur archives réelles : seuls les éléments voulus changent, aucun fichier altéré, tous les noms retrouvés par l'arbre, blocs alignés ; relecture du fichier sauvegardé OK.
- **Ajouter un son Séquence** (File > Add Sequence Sound…) : nouveau label + code MML ajouté au BFSEQ du son modèle, son créé avec ses banques ; édition ensuite dans l'éditeur MML.
  **Ajouter un son Wave** (File > Add Wave Sound…) : la vague (WAV encodé en DSP-ADPCM) est ajoutée au BFWAR du modèle, une entrée est créée dans son BFWSD, puis le son (y compris quand tout est dans un BFGRP imbriqué).
  Vérifié sur NSMBU : relecture après sauvegarde OK (le nouveau son Wave rejoue le WAV d'origine), 120 sons Wave existants tirés au hasard strictement identiques, BFWSD (49/49) et BFWAR reconstruits à l'identique.
- **Supprimer un son** (clic droit > Delete) : renumérotation des sons suivants, des plages des jeux de sons, des noms et de l'arbre de recherche ; audité sur les 3 archives (le fichier audio reste dans l'archive, inutilisé).
- **BFGRP externes** (SM3DW) : on peut y écrire (banques, séquences, sons Wave) ; ils sont réécrits à leur emplacement d'origine à la sauvegarde. Un fichier présent en plusieurs copies (BFSAR + BFGRP interne/externe) est mis à jour partout.
- **Champs de son** lus pour de vrai et modifiables sur place : pan mode/courbe, priorité, acteur, envois (stream), volume, remote filter, player, pitch (quand la valeur est stockée dans le fichier).
- **Édition des BFWAR / vagues** (Wave Files, Wave Archives) : infos (fréquence, canaux, durée, encodage, boucle, taille, instruments et wave sounds qui l'utilisent), **Replace** par un WAV, **Export** WAV/BFWAV, **Edit loop** (paramètres ADPCM de boucle recalculés, formule vérifiée sur les fichiers réels), **Add Wave** à une archive. Testé sur NSMBU (3 155 vagues) avec sauvegarde et relecture.
- Un son ajouté écrit son BFSTM dans `stream/` à côté du BFSAR (pensez à copier ce dossier avec le BFSAR).

**Séquenceur (lecture)** : portamento, LFO (vibrato/trémolo, approximation de la vitesse), legato (tie), loops/appels/variables, tempo variable, **suivi de lecture** dans l'éditeur MML (Follow / Trail / choix de la piste, comme l'original). 25 musiques de NSMBU rendues sans erreur. **Justesse de hauteur validée objectivement** sur des vagues tonales de NSMBU (fréquence rendue = fréquence de la vague à la clé d'origine ; +12 touches = ×2,000) ; non applicable aux bruits/impacts.

**Non vérifié** : BFSTM d'autres versions (ex. 4.x avec région) ; séquenceur (rendu approximatif : pas de LFO, portamento, filtres ; hauteur/niveaux non validés à l'oreille) ;
comportement en jeu d'un BFSAR modifié.

**Pas encore porté** : supprimer autre chose que des sons ; ajouter/renommer des éléments qui n'ont pas de nom stocké ;
File > New (créer un BFSAR de zéro) ; paramètres 3D des sons ; ajouter un son quand l'archive n'en contient aucun du même type (modèle requis) ;
lecture de séquence avec suivi des lignes/pistes en temps réel ; filtres passe-bas, sweep pitch, rampes `_t`, précision des valeurs LFO/portamento du séquenceur ; System Window.

## Exécutables (GitHub Actions)
Poussez le dépôt : l'onglet **Actions** construit Windows / Linux / macOS (Intel + ARM) via PyInstaller (`--add-data` des fichiers web inclus).
En local : `pip install pyinstaller numpy` puis
`pyinstaller --onefile --windowed --name TuneBloom-Py --add-data "tunebloom/web:tunebloom/web" run_tunebloom.py` (Windows : `;` au lieu de `:`).

## Crédits
Encodeur DSP-ADPCM et écrivain BFWAV : « TuneBloom-Python » (MIT, `LICENSE-nwlib.txt`). Polices Space Mono (OFL) et Lucide (ISC) issues du dépôt TuneBloom.
