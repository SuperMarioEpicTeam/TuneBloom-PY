"""Export WAV et lecture (sans dépendance : winsound / afplay / paplay / aplay)."""
import os, subprocess, shutil, sys, tempfile, wave
from array import array


def write_wav(audio, path, channels=None):
    chans = audio.channels if channels is None else [audio.channels[i] for i in channels]
    n = len(chans)
    frames = min(len(c) for c in chans)
    inter = array("h", bytes(frames * n * 2))
    for i, c in enumerate(chans):
        inter[i::n] = c[:frames]
    if sys.byteorder == "big":
        inter.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(n)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes(inter.tobytes())


class Player:
    def __init__(self):
        self._proc = None
        self._tmp = None

    def play(self, audio):
        self.stop()
        fd, self._tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        write_wav(audio, self._tmp, channels=list(range(min(2, len(audio.channels)))))
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(self._tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        for cmd in (["afplay"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
            if shutil.which(cmd[0]):
                self._proc = subprocess.Popen(cmd + [self._tmp])
                return
        raise RuntimeError("Aucun lecteur audio trouvé (afplay/paplay/aplay/ffplay)")

    def stop(self):
        if sys.platform.startswith("win"):
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
