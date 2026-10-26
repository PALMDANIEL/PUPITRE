"""
Voix chantées (essai) : chaque note est chantée sur sa syllabe, à sa hauteur et pour sa durée exactes.

1. Une voix de synthèse libre (Piper : SIWIS pour les voix de femme, UPMC « Pierre » pour les voix d'homme)
   prononce la syllabe.
2. Praat (parselmouth) la transforme en note chantée : la consonne d'attaque garde sa durée naturelle,
   la voyelle est tenue jusqu'au bout de la note, la hauteur devient celle de la partition, avec un vibrato léger.
3. Les syllabes sont posées sur le temps (la consonne juste avant, comme le fait un chanteur) et mélangées.

Langues : français, latin d'église, anglais (prononcé à la française), mooré et dioula (orthographe convertie
en sons français : l'accent reste, les mots sont reconnaissables). Sans paroles, la voix chante « a ».
"""
from __future__ import annotations

import functools
import os
import pathlib
import re
import unicodedata

import numpy as np

RATE = 44100
VOICES = {  # fichier Piper, numéro de locuteur
    "femme": ("fr_FR-siwis-medium", None),
    "homme": ("fr_FR-upmc-medium", 1),
}
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/{path}"
VOICE_PATHS = {"fr_FR-siwis-medium": "siwis/medium/fr_FR-siwis-medium", "fr_FR-upmc-medium": "upmc/medium/fr_FR-upmc-medium"}


def voice_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VOIX_DIR") or pathlib.Path.home() / "pupitre" / "voix")


def missing_voices() -> list[str]:
    d = voice_dir()
    return [name for name, _ in VOICES.values() if not (d / f"{name}.onnx").exists() or not (d / f"{name}.onnx.json").exists()]


def _espeak_data() -> pathlib.Path:
    """Données de prononciation espeak-ng livrées avec Piper (aussi dans le moteur autonome PyInstaller)."""
    import importlib.util
    import sys
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(pathlib.Path(sys._MEIPASS) / "piper" / "espeak-ng-data")
    spec = importlib.util.find_spec("piper")  # sans importer piper (voir plus bas)
    if spec and spec.origin:
        candidates.append(pathlib.Path(spec.origin).parent / "espeak-ng-data")
    data = next((c for c in candidates if (c / "phontab").exists()), candidates[-1] if candidates else pathlib.Path("espeak-ng-data"))
    # espeak-ng refuse les chemins longs (installation dans un dossier profond) : copie unique dans un dossier court
    if len(str(data)) > 100 and (data / "phontab").exists():
        short = pathlib.Path.home() / ".pupitre-espeak" / "espeak-ng-data"
        if not (short / "phontab").exists() or (short / "phontab").stat().st_size != (data / "phontab").stat().st_size:
            import shutil
            shutil.rmtree(short, ignore_errors=True)
            shutil.copytree(data, short)
        data = short
    return data


# espeak-ng lit ESPEAK_DATA_PATH au chargement de Piper : à régler avant tout import de piper
os.environ.setdefault("ESPEAK_DATA_PATH", str(_espeak_data()))


@functools.lru_cache(maxsize=None)
def _voice(kind: str):
    from piper import PiperVoice
    name, _ = VOICES[kind]
    d = voice_dir()
    return PiperVoice.load(d / f"{name}.onnx", config_path=d / f"{name}.onnx.json", espeak_data_dir=_espeak_data())


# --- Prononciation ----------------------------------------------------------------------------------------------

def _strip_tones(text: str) -> str:
    """Retire les accents de ton (mooré, dioula) mais garde le tilde de nasale."""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn" and ch != "̃":
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


_MOORE_DIOULA = [
    ("ã", "an"), ("ẽ", "in"), ("ĩ", "in"), ("õ", "on"), ("ũ", "oun"),
    ("ɲ", "gn"), ("ny", "gn"), ("ŋ", "ng"), ("ʋ", "v"), ("ɩ", "i"), ("ɛ", "è"), ("ɔ", "o"),
    ("c", "tch"), ("j", "dj"), ("u", "ou"), ("w", "ou"),
]


def moore_dioula_to_french(syl: str) -> str:
    s = _strip_tones(syl.lower())
    for a, b in _MOORE_DIOULA:
        s = s.replace(a, b)
    s = re.sub(r"(?<![aeiouèé])e(?![nm])", "é", s)          # e : toujours « é »
    s = re.sub(r"([aeiouéèo])\1+", r"\1", s)                  # voyelle longue : tenue par la note
    s = re.sub(r"g(?=[eéèi])", "gu", s)                       # g toujours dur
    s = re.sub(r"(?<=[aeiouéèo])s(?=[aeiouéèo])", "ss", s)    # s toujours sourd
    return s


def latin_to_french(syl: str) -> str:
    """Latin d'église (prononciation romaine) écrit à la française."""
    s = syl.lower().replace("æ", "e").replace("œ", "e").replace("ae", "e").replace("oe", "e")
    s = re.sub(r"c(?=[eéiy])", "tch", s)
    s = re.sub(r"g(?=[eéiy])", "dj", s)
    s = s.replace("gn", "gni").replace("qu", "kou").replace("ch", "k").replace("ph", "f").replace("th", "t")
    s = re.sub(r"^h", "", s).replace("j", "i").replace("y", "i")
    s = re.sub(r"ti(?=[aeiou])", "tsi", s)
    s = s.replace("u", "ou")
    s = re.sub(r"e(?![a-z])", "é", s)
    s = re.sub(r"e(?=[a-z])", "è", s)
    s = re.sub(r"(?<=[aeiouéè])s(?=[aeiouéè])", "ss", s)
    return s


def pronounce(syl: str, lang: str) -> str:
    syl = re.sub(r"[^\ẁ-ͯ'’ʋɩɛɔŋɲ-]", "", syl).strip("-'’")
    if not syl:
        return "a"
    if lang == "la":
        return latin_to_french(syl)
    if lang in ("mos", "dyu"):
        return moore_dioula_to_french(syl)
    return syl.lower()


# --- Une syllabe chantée --------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=4096)
def _spoken(kind: str, text: str) -> tuple[np.ndarray, int]:
    """Syllabe prononcée par la voix (mise en cache : les mêmes syllabes reviennent souvent)."""
    from piper import SynthesisConfig
    voice = _voice(kind)
    cfg = SynthesisConfig(speaker_id=VOICES[kind][1], length_scale=1.15, noise_scale=0.5, noise_w_scale=0.6)
    chunks = [c.audio_float_array for c in voice.synthesize(text, cfg)]
    audio = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)
    return audio.astype(np.float64), voice.config.sample_rate


def _trim(audio: np.ndarray, rate: int) -> np.ndarray:
    """Retire les silences avant et après la syllabe."""
    win = max(1, rate // 100)
    env = np.convolve(np.abs(audio), np.ones(win) / win, mode="same")
    idx = np.where(env > max(env.max() * 0.04, 1e-4))[0]
    return audio[idx[0]: idx[-1] + 1] if len(idx) else audio


def _resample(y: np.ndarray, src: int, dst: int = RATE) -> np.ndarray:
    if src == dst or len(y) < 2:
        return y
    n = int(round(len(y) * dst / src))
    return np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y)


def _sustain(region: np.ndarray, period: int, length: int) -> np.ndarray:
    """Tient une voyelle : grains de quelques périodes, pris à des multiples exacts de la période (pas de saccade)."""
    k = max(1, int(round(0.035 * 22050 / period)))
    grain = 2 * k * period
    if len(region) < grain + period:
        reps = int(np.ceil(length / max(len(region), 1))) + 1
        return np.tile(region, reps)[:length]
    hop = grain // 2
    win = np.hanning(grain)
    out = np.zeros(length + grain)
    starts = np.arange(0, len(region) - grain, period)
    rng = np.random.default_rng(len(region) + period)
    for pos in range(0, length, hop):
        st = int(rng.choice(starts))
        out[pos: pos + grain] += region[st: st + grain] * win
    return out[:length]


def _vibrato(y: np.ndarray, rate: int, after: float = 0.3) -> np.ndarray:
    """Vibrato naturel (environ ±25 cents, 5,4 Hz) par une ligne à retard modulée, qui s'installe progressivement."""
    n = len(y)
    t = np.arange(n) / rate
    depth = np.clip((t - after) / 0.4, 0, 1) * 0.00045
    d = depth * np.sin(2 * np.pi * 5.4 * t) * rate
    return np.interp(np.clip(np.arange(n) - d - 0.00045 * rate, 0, n - 1), np.arange(n), y)


def sing_syllable(kind: str, text: str, freq: float, seconds: float, vibrato: bool = True) -> tuple[np.ndarray, float]:
    """Renvoie l'audio (44,1 kHz) et la durée de la consonne d'attaque, à placer juste avant le temps."""
    import parselmouth
    from parselmouth.praat import call

    audio, rate = _spoken(kind, text)
    audio = _trim(audio, rate)
    snd = parselmouth.Sound(audio, sampling_frequency=rate)
    floor, ceiling = (75, 400) if kind == "homme" else (120, 600)
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=floor, pitch_ceiling=ceiling)
    voiced = np.where(pitch.selected_array["frequency"] > 0)[0]
    total = snd.duration
    if len(voiced) < 3:  # rien de voisé : on chante quand même la syllabe telle quelle
        v0, v1 = total * 0.3, total * 0.8
    else:
        v0, v1 = float(pitch.xs()[voiced[0]]), float(pitch.xs()[voiced[-1]])

    # 1. hauteur de la note (Praat, sans changer la durée), petite montée vers la note au début de la voyelle
    manip = call(snd, "To Manipulation", 0.01, floor, ceiling)
    tier = call("Create PitchTier", "hauteur", 0, total)
    call(tier, "Add point", 0, freq * 2 ** (-35 / 1200))
    call(tier, "Add point", v0, freq * 2 ** (-35 / 1200))
    call(tier, "Add point", min(v0 + 0.06, v1), freq)
    call(tier, "Add point", total, freq)
    call([manip, tier], "Replace pitch tier")
    out = call(manip, "Get resynthesis (overlap-add)")
    y = np.asarray(out.values[0], dtype=np.float64)
    sr = int(out.sampling_frequency)
    i0, i1 = int(v0 * sr), max(int(v1 * sr), int(v0 * sr) + 1)
    i1 = min(i1, len(y))
    onset, nucleus, coda = y[:i0], y[i0:i1], y[i1:]
    coda = coda[: int(0.14 * sr)]

    # 2. la voyelle dure jusqu'à la consonne finale
    need = max(int((seconds - len(coda) / sr) * sr), int(0.05 * sr))
    if need <= len(nucleus):
        vowel = nucleus[:need].copy()
    else:
        period = max(2, int(round(sr / freq)))
        q = len(nucleus) // 4
        head = nucleus[: max(q, 1)]
        region = nucleus[q: len(nucleus) - q] if len(nucleus) - 2 * q > period * 3 else nucleus
        vowel = np.concatenate([head, _sustain(region, period, need - len(head))])
        xf = min(int(0.012 * sr), len(head) // 2, len(vowel) - len(head))
        if xf > 4:  # jonction douce entre l'attaque naturelle et la tenue
            a = len(head) - xf
            vowel[a: a + xf] = nucleus[a: a + xf] * np.linspace(1, 0, xf) + vowel[a: a + xf] * np.linspace(0, 1, xf)
    if vibrato:
        vowel = _vibrato(vowel, sr)
    # léger souffle de fin de note
    rel = min(int(0.06 * sr), len(vowel) // 3)
    if rel > 0:
        vowel[-rel:] *= np.linspace(1, 0.35 if len(coda) else 0.0, rel)
    full = np.concatenate([onset, vowel, coda])
    full = _resample(full, sr)
    fade = min(len(full) // 4, int(0.012 * RATE))
    if fade > 0:
        full[:fade] *= np.linspace(0, 1, fade)
        full[-fade:] *= np.linspace(1, 0, fade)
    return full.astype(np.float32), len(onset) / sr


# --- Une voix entière -----------------------------------------------------------------------------------------

def syllables_from_text(text: str) -> list[str]:
    """« Sain-te Ma-ri-e _ ma-ter » → ['Sain', 'te', 'Ma', 'ri', 'e', '_', 'ma', 'ter'] ; « _ » prolonge la syllabe précédente."""
    out = []
    for word in text.replace("\n", " ").split():
        out.extend(p for p in re.split(r"-+", word) if p)
    return out


def note_syllables(notes, lyrics_text: str | None) -> list[str | None]:
    """Syllabe de chaque note : texte saisi s'il existe, sinon paroles de la partition ; None = mélisme (on tient)."""
    if lyrics_text and lyrics_text.strip():
        sylls = syllables_from_text(lyrics_text)
        out, k = [], 0
        for _ in notes:
            if k < len(sylls):
                s = sylls[k]; k += 1
                out.append(None if s == "_" else s)
            else:
                out.append(None)
        return out
    out = []
    for n in notes:
        lyr = n.lyrics[0].text if getattr(n, "lyrics", None) and n.lyrics[0].text else None
        out.append(lyr)
    return out


def sing_part(part, qpm: float, kind: str, lang: str = "fr", lyrics_text: str | None = None) -> np.ndarray:
    notes = list(part.stripTies().flatten().notes)
    sec = 60.0 / qpm
    sylls = note_syllables(notes, lyrics_text)
    has_words = any(sylls)
    end = (float(notes[-1].offset + notes[-1].quarterLength) * sec + 1.5) if notes else 1.0
    buf = np.zeros(int(end * RATE) + RATE, np.float32)
    last_vowel = "a"
    prev_end = -1.0
    for n, syl in zip(notes, sylls):
        start, dur = float(n.offset) * sec, float(n.quarterLength) * sec
        midi = max(p.midi for p in n.pitches)
        freq = 440.0 * 2 ** ((midi - 69) / 12)
        if syl is None:
            # mélisme ou note sans parole : on tient la voyelle de la syllabe précédente (ou « a » sans paroles)
            text = last_vowel if has_words and start - prev_end < 0.05 else "a" if not has_words else last_vowel
        else:
            text = pronounce(syl, lang)
            vowels = re.findall(r"[aeiouyéèêàâîôûœ]+n?", text)
            last_vowel = vowels[-1] if vowels else "a"
        y, onset = sing_syllable(kind, text, freq, dur * 0.97)
        i = int(max(0.0, start - onset) * RATE)
        j = min(len(buf), i + len(y))
        buf[i:j] += y[: j - i]
        prev_end = start + dur
    peak = float(np.max(np.abs(buf))) or 1.0
    return (buf / peak * 0.8).astype(np.float32)


def chorus(mono: np.ndarray) -> np.ndarray:
    """Effet de petit ensemble : deux copies légèrement décalées et désaccordées (sans resynthèse)."""
    n = len(mono)
    t = np.arange(n) / RATE
    out = mono.copy()
    for delay_ms, rate_hz, depth_ms, gain in ((17, 0.31, 2.2, 0.55), (29, 0.23, 2.8, 0.45)):
        d = (delay_ms + depth_ms * np.sin(2 * np.pi * rate_hz * t)) * RATE / 1000
        idx = np.clip(np.arange(n) - d, 0, n - 1)
        out += gain * np.interp(idx, np.arange(n), mono).astype(np.float32)
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.8).astype(np.float32)
