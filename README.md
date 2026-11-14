# TuneBloom-Py

A **partial** rewrite in pure Python (no dependencies, standard library only) of
[TuneBloom](https://github.com/) for Wii U sound archives (**BFSAR**).

## What works
- Reading BFSAR files: sounds, banks, wave archives (BFWAR), groups, players, file tables, and names.
- Extracting all internal files (`.bfstm`, `.bfwar`, `.bfseq`, `.bfbnk`, `.bfwsd`, `.bfgrp`, etc.).
- Decoding **BFSTM** and **BFWAV** (DSP-ADPCM, PCM16, PCM8) to WAV format, with playback in the interface.
- **Replacing** internal files (the BFSAR is rewritten, with offsets and sizes recalculated).
- Tkinter-based interface and command-line interface.

## What has NOT (yet) been ported
BFSEQ sequence editor, BFBNK bank editor, interpretation of BFWSD (wave sounds),
sequence playback/synthesis, importing WAV files to BFSTM/BFWAV (DSP-ADPCM encoder), editing properties
(volume, player, loops, etc.), and full BFSAR reconstruction from scratch (Patricia tree, etc.).
Tested only on synthetic files (`tests/`), not on actual BFSAR files.

## Usage (without compiling)
python -m tunebloom                       # graphical interface
python -m tunebloom list    archive.bfsar
python -m tunebloom extract archive.bfsar output/ --wav
python -m tunebloom wav     sound.bfstm sound.wav
python -m tunebloom replace archive.bfsar 3 new.bfstm -o modified_archive.bfsar

Requires Python 3.9+; Tkinter is needed for the interface (on Linux: `sudo apt install python3-tk`). Audio playback: Windows = `winsound`, macOS = `afplay`, Linux = `paplay`/`aplay`/`ffplay`.

## Creating executables
### Via GitHub (recommended: handles Windows, Linux, and macOS—Intel + ARM—all at once)
1. Create a GitHub repository and push this folder (`git init && git add . && git commit -m init && git push`).
2. Go to the **Actions** tab: the *Build TuneBloom-Py* workflow will start automatically (or click "Run workflow").
3. Download the executables from the *Artifacts* section at the bottom of the workflow run.
4. To publish a release: `git tag v0.1.0 && git push --tags` (ZIP files will be attached automatically).

### Locally (PyInstaller, ~10 MB, no Visual Studio required)
python -m pip install pyinstaller
pyinstaller --onefile --windowed --name TuneBloom-Py run_tunebloom.py
The result will be in the `dist/` directory. PyInstaller does not support cross-compilation; you must build separately for each OS.
macOS: Upon the first launch, right-click the file and select "Open" (as the binary is unsigned).
