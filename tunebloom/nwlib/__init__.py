"""Modules repris de « TuneBloom-Python » (licence MIT, voir LICENSE-nwlib.txt) :
encodeur DSP-ADPCM (vérifié octet pour octet contre src/dsp/encode.cpp d'origine) et écrivain BFWAV."""
from .dsp_encode import encode_dsp_adpcm
from .wave_writer import build_bfwav
