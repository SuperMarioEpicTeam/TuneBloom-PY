import argparse, os, re, sys

from .bfsar import Bfsar, ITEM_NAMES, SOUND_TYPE_NAMES, INVALID
from . import formats
from .audio import write_wav


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def cmd_list(a):
    arc = Bfsar.open(a.bfsar)
    print(f"BFSAR version 0x{arc.version:08X}, {'big' if arc.endian == '>' else 'little'} endian, {len(arc.files)} fichiers")
    for it in arc.all_items():
        extra = SOUND_TYPE_NAMES.get(it.sound_type, "") if it.kind == 1 else ""
        fid = "-" if it.file_id == INVALID else it.file_id
        print(f"{ITEM_NAMES[it.kind]:<12} #{it.index:<5} file={fid!s:<6} {extra:<9} {it.label}")


def cmd_extract(a):
    arc = Bfsar.open(a.bfsar)
    os.makedirs(a.out, exist_ok=True)
    names = {}
    for it in arc.all_items():
        if it.file_id != INVALID:
            names.setdefault(it.file_id, f"{ITEM_NAMES[it.kind]}_{safe(it.label)}")
    n = skipped = 0
    for fe in arc.files:
        blob = arc.file_bytes(fe.index)
        if blob is None:
            skipped += 1
            continue
        base = names.get(fe.index, f"file_{fe.index}")
        ext = arc.extension_for(blob)
        with open(os.path.join(a.out, base + ext), "wb") as f:
            f.write(blob)
        n += 1
        if a.wav and ext in (".bfstm", ".bfwav"):
            try:
                write_wav(formats.decode_any(blob), os.path.join(a.out, base + ".wav"))
            except Exception as e:
                print(f"  ! WAV impossible pour {base}: {e}")
        if a.wav and ext == ".bfwar":
            for i, w in enumerate(formats.split_bfwar(blob)):
                if w:
                    try:
                        write_wav(formats.decode_bfwav(w), os.path.join(a.out, f"{base}_wave{i:04d}.wav"))
                    except Exception as e:
                        print(f"  ! WAV impossible pour {base} wave {i}: {e}")
    print(f"{n} fichiers extraits dans {a.out} ({skipped} ignorés : externes introuvables)")


def cmd_wav(a):
    with open(a.file, "rb") as f:
        audio = formats.decode_any(f.read())
    write_wav(audio, a.out)
    print(f"{a.out} : {audio.sample_rate} Hz, {len(audio.channels)} canal(aux), {audio.frames} échantillons")


def cmd_replace(a):
    arc = Bfsar.open(a.bfsar)
    with open(a.new, "rb") as f:
        arc.replace_file(a.file_id, f.read())
    arc.save(a.out)
    print(f"Fichier #{a.file_id} remplacé -> {a.out}")


def cmd_gui(a):
    from .gui import main
    main(a.bfsar)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tunebloom", description="TuneBloom-Py : outil BFSAR (Wii U) en Python")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("list", help="lister le contenu"); s.add_argument("bfsar"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("extract", help="extraire tous les fichiers internes")
    s.add_argument("bfsar"); s.add_argument("out"); s.add_argument("--wav", action="store_true", help="convertir aussi en WAV")
    s.set_defaults(f=cmd_extract)
    s = sub.add_parser("wav", help="convertir un .bfstm/.bfwav en .wav"); s.add_argument("file"); s.add_argument("out")
    s.set_defaults(f=cmd_wav)
    s = sub.add_parser("replace", help="remplacer un fichier interne (par index) et sauvegarder")
    s.add_argument("bfsar"); s.add_argument("file_id", type=int); s.add_argument("new"); s.add_argument("-o", "--out", required=True)
    s.set_defaults(f=cmd_replace)
    s = sub.add_parser("gui", help="interface graphique (par défaut)"); s.add_argument("bfsar", nargs="?"); s.set_defaults(f=cmd_gui)
    a = p.parse_args(argv)
    if not a.cmd:
        return cmd_gui(argparse.Namespace(bfsar=None))
    a.f(a)
