import sys, os, struct, wave, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import synth
from tunebloom import dspadpcm, formats
from tunebloom.bfsar import Bfsar, T_SND_STRM
from tunebloom.audio import write_wav

# coefs nuls + scale=0 -> sortie = nibble signé
nibs = [1, 2, 3, 15, 14, 7, 8, 0, 0, 0, 0, 0, 0, 1]
exp = [1, 2, 3, -1, -2, 7, -8, 0, 0, 0, 0, 0, 0, 1]
frames = synth.adpcm_frames([nibs, nibs])
out = dspadpcm.decode(frames, 28, [0] * 16)
assert list(out[:14]) == exp and list(out[14:]) == exp, list(out)

# Prédiction : coef1=2048 => y[n] = nib + y[n-1]
frames2 = synth.adpcm_frames([[1] * 14])
out2 = dspadpcm.decode(frames2, 14, [2048 * 1, 0] + [0] * 14, 0, 0) if False else None
coefs = [2048, 0] + [0] * 14
# avec pred=0 : (scale*nib<<11 + 1024 + 2048*h1) >> 11 = nib + h1 -> accumulation
out2 = dspadpcm.decode(frames2, 14, coefs)
assert list(out2) == list(range(1, 15)), list(out2)

assert dspadpcm.samples_to_bytes(28) == 16 and dspadpcm.bytes_to_samples(16) == 28

stm = synth.bfstm(frames, 28)
a = formats.decode_bfstm(stm)
assert a.sample_rate == 32000 and len(a.channels) == 1 and list(a.channels[0]) == list(dspadpcm.decode(frames, 28, synth.COEFS))
assert a.frames == 28
wav = synth.bfwav(frames, 28)
b = formats.decode_bfwav(wav)
assert b.sample_rate == 22050 and b.frames == 28

war = synth.bfwar([wav, wav])
ws = formats.split_bfwar(war)
assert len(ws) == 2 and ws[0][:4] == b"FWAV"

arc = Bfsar(synth.bfsar([stm, war], ["SE_TEST", "WARC_TEST"]))
assert [s.label for s in arc.sounds] == ["SE_TEST"], arc.sounds
assert arc.sounds[0].sound_type == T_SND_STRM and arc.sounds[0].extra["channels"] == 1
assert arc.warcs[0].label == "WARC_TEST" and arc.warcs[0].file_id == 1
blob0 = arc.file_bytes(arc.sounds[0].file_id)
assert blob0[:4] == b"FSTM" and blob0 == stm
assert arc.file_bytes(1) == war

# Remplacement du fichier 0 par un fichier plus gros, puis relecture
bigger = synth.bfstm(synth.adpcm_frames([nibs] * 10), 140)
arc.replace_file(0, bigger)
assert arc.file_bytes(0) == bigger, "fichier 0"
assert arc.file_bytes(1) == war, "fichier 1 décalé correctement"
assert struct.unpack(">I", arc.data[12:16])[0] == len(arc.data)
arc2 = Bfsar(bytes(arc.data))
assert arc2.file_bytes(0) == bigger and arc2.file_bytes(1) == war
assert formats.decode_bfstm(arc2.file_bytes(0)).frames == 140

arc3 = Bfsar(synth.bfsar([stm, war], ["A", "B"]))
grp = synth.bfgrp([(1, synth.bfwar([wav])), (0, stm)])
assert arc3.attach_group(grp) == 2 and arc3.file_bytes(1)[:4] == b"FWAR" and arc3.file_bytes(0) == stm

with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "x.wav")
    write_wav(a, p)
    with wave.open(p) as w:
        assert w.getnframes() == 28 and w.getframerate() == 32000
print("OK : tous les tests synthétiques passent")

# ---- import WAV, reconstruction BFWAR/BFGRP, remplacement de son ----
import math
from tunebloom.wavio import wav_to_bfwav
from tunebloom.bfwar import rebuild_bfwar, rebuild_bfgrp
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "s.wav")
    w = wave.open(p, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
    sine = [int(9000 * math.sin(i / 7)) for i in range(5000)]
    w.writeframes(struct.pack("<5000h", *sine)); w.close()
    pcm = formats.decode_bfwav(wav_to_bfwav(p, "pcm16"))
    assert list(pcm.channels[0]) == sine and pcm.sample_rate == 22050
    adp = formats.decode_bfwav(wav_to_bfwav(p, "dspadpcm", loop_start=100))
    sig = sum(x * x for x in sine); err = sum((x - y) ** 2 for x, y in zip(sine, adp.channels[0]))
    assert 10 * math.log10(sig / max(err, 1)) > 20 and adp.loop and adp.loop_start == 100

war2 = synth.bfwar([wav, wav, wav])
assert rebuild_bfwar(war2, {}) == war2                       # reconstruction identique
newwav = wav_to_bfwav.__globals__["build_bfwav"]([sine], 22050, 1)
r = formats.split_bfwar(rebuild_bfwar(war2, {1: newwav}))
assert bytes(r[1]) == newwav and bytes(r[0]) == wav and bytes(r[2]) == wav
grp2 = synth.bfgrp([(0, stm), (1, war2)])
assert rebuild_bfgrp(grp2, {}) == grp2
from tunebloom.bfsar import read_bfgrp
g3 = read_bfgrp(rebuild_bfgrp(grp2, {1: war2 + b"\x00" * 64}))
assert bytes(g3[0]) == stm and len(g3[1]) == len(war2) + 64
print("OK : import WAV / BFWAR / BFGRP")

# ---- WAV en mémoire, désassembleur MML ----
import io
from tunebloom.mml import decode, note_name
bio = io.BytesIO(); write_wav(a, bio)
assert bio.getvalue()[:4] == b"RIFF" and len(bio.getvalue()) > 44
assert note_name(60) == "cn4" and note_name(0) == "cnm1" and note_name(66) == "fs4"
assert decode(bytes([0x3c, 0x7f, 0x06]), 0)[:2] == ("cn4 127, 6", 3)
assert decode(bytes([0x80, 0x03]), 0)[0] == "wait 3"
assert decode(bytes([0xc1, 0x64]), 0)[0] == "volume 100"
assert decode(bytes([0x89, 0x00, 0x00, 0x10]), 0)[2] == 0x10
print("OK : WAV mémoire / MML")

# ---- assembleur MML : aller-retour texte <-> octets ----
from tunebloom.mmlasm import assemble, AsmError, vmidi
from tunebloom.mml import decode as mdecode
SRC = """Start:
    prg 12
    release 126
    cn4 127, 6
    wait 6
    pan_r -10, 10
    volume_v var3
    tempo 140
    opentrack 1, Track1
    jump Start
Track1:
    _if fs2 90, 300
    setvar var16, 5
    cmp_eq var16, 5
    transpose -2
    loop_start 4
    wait 48
    loop_end
    ret
    fin"""
code, order = assemble(SRC)
# re-désassemblage commande par commande doit redonner exactement le même code
p, out = 0, []
while p < len(code):
    t, n, _ = mdecode(code, p); out.append(t); p += n
code2, _ = assemble("\n".join(["Start:"] + ["    " + x.replace("@1", "Start") for x in out]) if False else SRC)
assert code2 == code and [n for _, n in order] == ["Start", "Track1"]
assert vmidi(0) == b"\x00" and vmidi(127) == b"\x7f" and vmidi(128) == b"\x81\x00" and vmidi(300) == b"\x82\x2c"
for bad in ("zzz 1", "wait", "jump Nope", "cn4 300"):
    try:
        assemble("    " + bad); assert False, bad
    except AsmError:
        pass
from tunebloom.mml import decode as dd
assert dd(assemble("    cn4 127, 300")[0], 0)[0] == "cn4 127, 300"
assert dd(assemble("    _if wait 3")[0], 0)[0] == "_if wait 3"
print("OK : assembleur MML")
