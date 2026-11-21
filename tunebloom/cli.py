import argparse, os, re, sys

from .bfsar import Bfsar, ITEM_NAMES, SOUND_TYPE_NAMES, INVALID
from . import formats
from .audio import write_wav


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def _open(a):
    arc = Bfsar.open(a.bfsar)
    for g in getattr(a, "grp", None) or []:
        with open(g, "rb") as f:
            print(f"{g} : {arc.attach_group(f.read(), g)} fichiers")
    return arc


def cmd_list(a):
    arc = _open(a)
    print(f"BFSAR version 0x{arc.version:08X}, {'big' if arc.endian == '>' else 'little'} endian, {len(arc.files)} fichiers")
    for it in arc.all_items():
        extra = SOUND_TYPE_NAMES.get(it.sound_type, "") if it.kind == 1 else ""
        fid = "-" if it.file_id == INVALID else it.file_id
        print(f"{ITEM_NAMES[it.kind]:<12} #{it.index:<5} file={fid!s:<6} {extra:<9} {it.label}")


def cmd_extract(a):
    arc = _open(a)
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


def cmd_sounds(a):
    """Exporte en WAV tous les sons de type Wave (et streams disponibles), nommés comme dans le BFSAR."""
    arc = _open(a)
    os.makedirs(a.out, exist_ok=True)
    ok = fail = seq = 0
    for s in arc.sounds:
        try:
            if s.sound_type == 0x2202:
                blobs = arc.wave_blobs_for_sound(s)
                for k, b in enumerate(blobs):
                    suffix = "" if len(blobs) == 1 else f"_{k}"
                    write_wav(formats.decode_bfwav(b), os.path.join(a.out, safe(s.label) + suffix + ".wav"))
            elif s.sound_type == 0x2201:
                b = arc.file_bytes(s.file_id)
                if b is None:
                    raise ValueError("stream externe introuvable")
                write_wav(formats.decode_bfstm(b), os.path.join(a.out, safe(s.label) + ".wav"))
            else:
                seq += 1
                continue
            ok += 1
        except Exception as e:
            fail += 1
            if a.verbose:
                print(f"  ! {s.label}: {e}")
    print(f"{ok} sons exportés, {fail} indisponibles (données manquantes), {seq} séquences (lecture pas encore portée)")


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


def cmd_replace_wave(a):
    from .wavio import wav_to_bfwav
    arc = _open(a)
    matches = [x for x in arc.sounds if x.sound_type == 0x2202 and x.label == a.sound]
    if not matches:
        sys.exit(f"Son Wave introuvable : {a.sound}")
    bf = wav_to_bfwav(a.wav, a.enc, a.loop_start)
    arc.replace_wave(matches[0], bf)
    arc.save(a.out)
    print(f"{a.sound} remplacé ({len(bf)} octets de BFWAV, {a.enc}) -> {a.out}")


def cmd_wav2bfwav(a):
    from .wavio import wav_to_bfwav
    bf = wav_to_bfwav(a.wav, a.enc, a.loop_start)
    with open(a.out, "wb") as f:
        f.write(bf)
    print(f"{a.out} : {len(bf)} octets ({a.enc})")


def cmd_wav2bfstm(a):
    from .wavio import wav_to_bfstm
    data, ls = wav_to_bfstm(a.wav, a.loop_start)
    with open(a.out, "wb") as f:
        f.write(data)
    print(f"{a.out} : {len(data)} octets" + (f", boucle à l'échantillon {ls}" if a.loop_start is not None else ""))


def cmd_gui(a):
    from .server import main
    main(a.bfsar, port=getattr(a, "port", 0) or 0)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tunebloom", description="TuneBloom-Py : outil BFSAR (Wii U) en Python")
    sub = p.add_subparsers(dest="cmd")
    GRP = dict(nargs="*", metavar="BFGRP", help="BFGRP externes à charger (jeux comme SM3DW)")
    s = sub.add_parser("list", help="lister le contenu"); s.add_argument("bfsar"); s.add_argument("--grp", **GRP); s.set_defaults(f=cmd_list)
    s = sub.add_parser("extract", help="extraire tous les fichiers internes")
    s.add_argument("bfsar"); s.add_argument("out"); s.add_argument("--wav", action="store_true", help="convertir aussi en WAV"); s.add_argument("--grp", **GRP)
    s.set_defaults(f=cmd_extract)
    s = sub.add_parser("sounds", help="exporter les sons Wave/Stream en WAV, par nom")
    s.add_argument("bfsar"); s.add_argument("out"); s.add_argument("--grp", **GRP); s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(f=cmd_sounds)
    s = sub.add_parser("wav2bfwav", help="convertir un WAV en BFWAV (encodeur DSP-ADPCM identique au C++)")
    s.add_argument("wav"); s.add_argument("out"); s.add_argument("--enc", choices=["pcm8", "pcm16", "dspadpcm"], default="dspadpcm")
    s.add_argument("--loop-start", type=int, default=None); s.set_defaults(f=cmd_wav2bfwav)
    s = sub.add_parser("wav2bfstm", help="convertir un WAV en BFSTM (DSP-ADPCM, boucle optionnelle)")
    s.add_argument("wav"); s.add_argument("out"); s.add_argument("--loop-start", type=int, default=None); s.set_defaults(f=cmd_wav2bfstm)
    s = sub.add_parser("replace-wave", help="remplacer l'audio d'un son Wave par un WAV")
    s.add_argument("bfsar"); s.add_argument("sound"); s.add_argument("wav"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--enc", choices=["pcm8", "pcm16", "dspadpcm"], default="dspadpcm"); s.add_argument("--loop-start", type=int, default=None)
    s.add_argument("--grp", **GRP); s.set_defaults(f=cmd_replace_wave)
    s = sub.add_parser("wav", help="convertir un .bfstm/.bfwav en .wav"); s.add_argument("file"); s.add_argument("out")
    s.set_defaults(f=cmd_wav)
    s = sub.add_parser("replace", help="remplacer un fichier interne (par index) et sauvegarder")
    s.add_argument("bfsar"); s.add_argument("file_id", type=int); s.add_argument("new"); s.add_argument("-o", "--out", required=True)
    s.set_defaults(f=cmd_replace)
    s = sub.add_parser("gui", help="interface graphique (par défaut)"); s.add_argument("bfsar", nargs="?"); s.add_argument("--port", type=int, default=0); s.set_defaults(f=cmd_gui)
    a = p.parse_args(argv)
    if not a.cmd:
        return cmd_gui(argparse.Namespace(bfsar=None))
    a.f(a)
