"""BFWSD (Wave Sound Data) : fait le lien entre un son « Wave » et ses vagues dans les BFWAR."""
from .binio import Reader, detect_endian

T_WSD_INFO = 0x6800


def read_bfwsd(data):
    """Renvoie (wave_ids, sounds) :
    wave_ids = [(id_archive, index_vague)], sounds = [[indices dans wave_ids de chaque « note »]]."""
    if bytes(data[:4]) != b"FWSD":
        raise ValueError("Pas un BFWSD")
    r = Reader(data, detect_endian(data))
    info_off = None
    for i in range(r.u16(16)):
        b = 0x14 + 12 * i
        if r.u16(b) == T_WSD_INFO:
            info_off = r.s32(b + 4)
    if info_off is None:
        raise ValueError("Bloc INFO du BFWSD introuvable")
    body = info_off + 8
    wid = body + r.s32(body + 4)
    wave_ids = [(r.u32(wid + 4 + 8 * i), r.u32(wid + 8 + 8 * i)) for i in range(r.u32(wid))]
    rt = body + r.s32(body + 12)                     # table des WaveSoundData
    sounds = []
    for i in range(r.u32(rt)):
        wsd = rt + r.s32(rt + 4 + 8 * i + 4)
        nt = wsd + r.s32(wsd + 20)                   # table des NoteInfo
        notes = []
        for j in range(r.u32(nt)):
            note = nt + r.s32(nt + 4 + 8 * j + 4)
            notes.append(r.u32(note))                # waveIdTableIndex
        sounds.append(notes)
    return wave_ids, sounds
