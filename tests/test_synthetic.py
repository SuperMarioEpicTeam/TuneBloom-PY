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
