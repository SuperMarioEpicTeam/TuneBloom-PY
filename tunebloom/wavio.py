"""Import WAV (PCM8/PCM16, mono/stéréo) -> BFWAV via l'encodeur vérifié contre le C++ d'origine."""
import sys, wave
from array import array
from .nwlib import build_bfwav

ENCODINGS = {"pcm8": 0, "pcm16": 1, "dspadpcm": 2}


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        n, sw, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(frames)
    if n not in (1, 2):
        raise ValueError("TuneBloom gère 1 ou 2 canaux")
    if sw == 2:
        a = array("h"); a.frombytes(raw)
        if sys.byteorder == "big":
            a.byteswap()
        chans = [list(a[c::n]) for c in range(n)]
    elif sw == 1:                                   # WAV 8 bits = non signé
        chans = [[(b - 128) << 8 for b in raw[c::n]] for c in range(n)]
    else:
        raise ValueError("Seuls les WAV PCM 8 et 16 bits sont pris en charge")
    return chans, rate


def wav_to_bfwav(path, encoding="dspadpcm", loop_start=None, endian=">"):
    chans, rate = read_wav(path)
    enc = ENCODINGS[encoding]
    if enc == 0:                                    # build_bfwav attend du PCM8 signé (-128..127)
        chans = [[v >> 8 for v in c] for c in chans]
    return build_bfwav(chans, rate, enc, loop_enabled=loop_start is not None,
                       loop_start=loop_start or 0, loop_end=len(chans[0]), endian=endian)
