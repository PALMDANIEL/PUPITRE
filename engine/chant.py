"""
Voix chantées (essai) : chaque note est chantée sur sa syllabe, à sa hauteur et pour sa durée exactes.

1. Plusieurs chanteurs par pupitre, comme un vrai chœur : des voix de synthèse libres et différentes (Piper :
   SIWIS et deux locutrices de MLS pour les femmes, UPMC « Pierre » et deux locuteurs de MLS pour les hommes),
   jamais parfaitement ensemble (quelques millisecondes, quelques cents d'écart).
2. Praat (parselmouth) transforme chaque syllabe prononcée en note chantée : la consonne d'attaque garde sa durée
   naturelle, la voyelle est tenue jusqu'au bout de la note, à la hauteur de la partition.
3. Une hauteur vivante : petite montée vers la note, glissé d'une note à l'autre quand c'est lié, légère dérive,
   vibrato qui s'installe et varie d'une note et d'un chanteur à l'autre.
4. Des nuances (les aigus un peu plus forts, la voix qui s'ouvre sur les notes longues) et des respirations
   avant chaque phrase. Les syllabes sont posées sur le temps, la consonne juste avant, comme le fait un chanteur.

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
# Chanteurs de chaque pupitre : (modèle Piper, numéro de locuteur, désaccord propre en cents, volume).
# Le premier est la voix principale ; les locuteurs MLS ont été choisis parmi 125 pour la clarté de leur timbre.
SINGERS = {
    "femme": [("fr_FR-siwis-medium", None, 0, 1.0), ("fr_FR-mls-medium", 54, 7, 0.8), ("fr_FR-mls-medium", 14, -6, 0.72)],
    "homme": [("fr_FR-upmc-medium", 1, 0, 1.0), ("fr_FR-mls-medium", 28, -7, 0.8), ("fr_FR-mls-medium", 117, 6, 0.72)],
}
MODELS = sorted({m for group in SINGERS.values() for m, *_ in group})


def voice_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VOIX_DIR") or pathlib.Path.home() / "pupitre" / "voix")


def missing_voices() -> list[str]:
    d = voice_dir()
    return [name for name in MODELS if not (d / f"{name}.onnx").exists() or not (d / f"{name}.onnx.json").exists()]


def ensemble_size() -> int:
    """Chanteurs par pupitre : 3 sur l'ordinateur ; le serveur en ligne en met moins (limite de temps)."""
    try:
        return max(1, min(3, int(os.environ.get("CHANT_ENSEMBLE", "3"))))
    except ValueError:
        return 3


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
def _voice(name: str):
    from piper import PiperVoice
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

@functools.lru_cache(maxsize=8192)
def _spoken(model: str, speaker: int | None, text: str) -> tuple[np.ndarray, int]:
    """Syllabe prononcée par un chanteur (mise en cache : les mêmes syllabes reviennent souvent)."""
    from piper import SynthesisConfig
    voice = _voice(model)
    cfg = SynthesisConfig(speaker_id=speaker, length_scale=1.15, noise_scale=0.5, noise_w_scale=0.6)
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
    """
    Conversion de fréquence d'échantillonnage à bande limitée (FFT) : la voix de synthèse (22,05 kHz) ne contient
    rien au-dessus de 11 kHz, et il ne doit rien y apparaître. Une simple interpolation y créait des « images »
    entendues comme des sifflements métalliques (ton parasite vers 13 kHz).
    """
    if src == dst or len(y) < 2:
        return y
    n = int(round(len(y) * dst / src))
    spec = np.fft.rfft(y)
    f = np.fft.rfftfreq(len(y), 1 / src)
    spec *= 1 / np.sqrt(1 + (f / (0.47 * src)) ** 16)  # coupe douce juste sous 11 kHz : pas de sonnerie
    out = np.zeros(n // 2 + 1, dtype=complex)
    k = min(len(spec), len(out))
    out[:k] = spec[:k]
    return np.fft.irfft(out, n) * (n / len(y))


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


def _harmonic_clean(vowel: np.ndarray, sr: int, f0: float) -> np.ndarray:
    """
    Nettoyage du souffle : la voix de synthèse parlée porte un voile de bruit dans les aigus (62 % de l'énergie
    au-dessus de 2 kHz tombe entre les harmoniques), entendu comme un sifflement sur les voyelles tenues.
    La hauteur est ici exactement celle de la note : on garde les harmoniques et on atténue le reste (−26 dB
    au-dessus de 1 kHz, −18 dB en dessous, où cela retire aussi les sous-harmoniques d'une voix éraillée), par transformée de Fourier à court terme (fenêtres de Hann, reconstruction exacte).
    """
    n = len(vowel)
    win = 2048 if sr <= 24000 else 4096  # ~93 ms : la hauteur est fixe ici, on peut séparer finement
    if n < win:
        return vowel
    hop = win // 4
    w = np.hanning(win)
    pad = np.concatenate([np.zeros(win), vowel, np.zeros(win)])
    fr = np.fft.rfftfreq(win, 1 / sr)
    h = np.round(fr / f0)
    dist = np.abs(fr - h * f0)
    keep = np.clip(1 - (dist - max(8.0, 0.012 * f0)) / max(6.0, 0.01 * f0), 0, 1)  # 1 sur l'harmonique, 0 entre
    # sous 1 kHz : on retire aussi ce qui n'est pas une harmonique (sous-harmoniques de la tenue, voix éraillée),
    # un peu moins fort ; au-dessus : le souffle, à −26 dB
    floor = np.where(fr < 1000, 10 ** (-18 / 20), 10 ** (-26 / 20))
    mask = floor + (1 - floor) * keep
    mask[fr < 40] = 1.0
    out = np.zeros(len(pad)); norm = np.zeros(len(pad))
    for i in range(0, len(pad) - win, hop):
        spec = np.fft.rfft(pad[i:i + win] * w) * mask
        out[i:i + win] += np.fft.irfft(spec, win) * w
        norm[i:i + win] += w ** 2
    out = out / np.maximum(norm, 1e-6)
    return out[win: win + n]


def _fundamental_share(vowel: np.ndarray, sr: int, f0: float) -> float:
    spec = np.abs(np.fft.rfft(vowel * np.hanning(len(vowel)))) ** 2
    fr = np.fft.rfftfreq(len(vowel), 1 / sr)
    return float(spec[np.abs(fr - f0) < max(20, 0.05 * f0)].sum() / (spec[fr > 60].sum() + 1e-15))


def _enrich(vowel: np.ndarray, sr: int, f0: float, target: float = 0.6) -> np.ndarray:
    """
    Timbre « flûte » : quand la fondamentale écrase tout (voyelle « i », notes aiguës), le son devient pur et sifflé.
    On ajoute des harmoniques 2, 3 et 4 exactes (polynômes de Tchebychev sur l'onde normalisée), juste assez pour
    ramener la fondamentale autour de 60 % de l'énergie, comme dans une vraie voix chantée.
    """
    if len(vowel) < 256:
        return vowel
    share = _fundamental_share(vowel, sr, f0)
    if share <= target:
        return vowel
    k = max(4, int(sr / f0 * 2))
    env = np.sqrt(np.convolve(vowel ** 2, np.ones(k) / k, mode="same")) * np.sqrt(2) + 1e-9
    xn = np.clip(vowel / env, -1, 1)
    harm = 0.5 * (2 * xn ** 2 - 1) + 0.38 * (4 * xn ** 3 - 3 * xn) + 0.22 * (8 * xn ** 4 - 8 * xn ** 2 + 1)
    harm -= np.convolve(harm, np.ones(64) / 64, mode="same")  # pas de composante continue
    harm *= env
    best = vowel
    for amount in (0.25, 0.45, 0.7, 1.0, 1.4):  # dose la plus faible qui suffit
        best = vowel + amount * harm
        if _fundamental_share(best, sr, f0) <= target:
            break
    return best


def _smooth_noise(rng, n: int, rate: int, hz: float) -> np.ndarray:
    """Bruit lent (variations de quelques hertz), écart-type 1 : dérive naturelle de la hauteur."""
    k = max(2, int(n / rate * hz) + 2)
    pts = rng.standard_normal(k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)


def _express(vowel: np.ndarray, sr: int, rng, seconds: float, glide_cents: float) -> np.ndarray:
    """
    Hauteur vivante, appliquée à la voyelle déjà accordée (lecture à vitesse variable, cents par cents) :
    glissé depuis la note précédente (legato) ou petite montée vers la note, légère dérive, vibrato qui
    s'installe après un instant, dont la vitesse et l'ampleur varient.
    """
    n = len(vowel)
    t = np.arange(n) / sr
    cents = np.zeros(n)
    if glide_cents:
        cents += glide_cents * np.exp(-t / 0.045)                      # glissé d'une note à l'autre
        cents += -0.08 * glide_cents * (t / 0.09) * np.exp(1 - t / 0.09)  # léger dépassement, puis la note
    else:
        cents += -rng.uniform(20, 40) * np.exp(-t / 0.035)              # attaque un peu par en dessous
    cents += 3.0 * _smooth_noise(rng, n, sr, 3.0)                      # dérive : ±3 cents environ
    if seconds > 0.4:
        start = rng.uniform(0.2, 0.34)
        ramp = np.clip((t - start) / 0.4, 0, 1)
        rate = rng.uniform(5.1, 5.8) + 0.3 * _smooth_noise(rng, n, sr, 1.0)
        depth = rng.uniform(24, 40) * (1 + 0.12 * _smooth_noise(rng, n, sr, 1.5))
        cents += ramp * depth * np.sin(2 * np.pi * np.cumsum(rate) / sr + rng.uniform(0, 6.28))
    pos = np.cumsum(2 ** (cents / 1200)) - 1
    return np.interp(np.clip(pos, 0, n - 1), np.arange(n), vowel)


def sing_syllable(singer: tuple, text: str, freq: float, seconds: float, kind: str = "femme", *,
                  glide_from: float | None = None, swell: bool = True, rng=None) -> tuple[np.ndarray, float]:
    """Renvoie l'audio (44,1 kHz) et la durée de la consonne d'attaque, à placer juste avant le temps."""
    import parselmouth
    from parselmouth.praat import call

    rng = rng if rng is not None else np.random.default_rng(0)
    model, speaker = singer[0], singer[1]
    audio, rate = _spoken(model, speaker, text)
    audio = _trim(audio, rate)
    snd = parselmouth.Sound(audio, sampling_frequency=rate)
    floor, ceiling = (70, 400) if kind == "homme" else (110, 600)
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=floor, pitch_ceiling=ceiling)
    voiced = np.where(pitch.selected_array["frequency"] > 0)[0]
    total = snd.duration
    if len(voiced) < 3:  # rien de voisé : on chante quand même la syllabe telle quelle
        v0, v1 = total * 0.3, total * 0.8
    else:
        v0, v1 = float(pitch.xs()[voiced[0]]), float(pitch.xs()[voiced[-1]])

    # 1. hauteur exacte de la note (Praat, sans changer la durée)
    manip = call(snd, "To Manipulation", 0.01, floor, ceiling)
    tier = call("Create PitchTier", "hauteur", 0, total)
    call(tier, "Add point", 0, freq)
    call(tier, "Add point", total, freq)
    call([manip, tier], "Replace pitch tier")
    out = call(manip, "Get resynthesis (overlap-add)")
    sr = int(out.sampling_frequency)
    # la resynthèse laisse une composante continue, énorme quand la note est bien plus aiguë que la voix parlée :
    # on la retire avant de régler le niveau, sinon la note réelle sortirait beaucoup trop faible
    from mixage import highpass
    y = highpass(np.asarray(out.values[0], dtype=np.float64), 45 if kind == "homme" else 60, sr)
    i0, i1 = int(v0 * sr), max(int(v1 * sr), int(v0 * sr) + 1)
    i1 = min(i1, len(y))
    onset, nucleus, coda = y[:i0], y[i0:i1], y[i1:]
    # consonnes soufflées raccourcies : 90 ms au plus avant la voyelle (on garde la fin, qui mène à la voyelle),
    # 80 ms au plus en finale ; un chanteur ne laisse jamais traîner un « sss »
    if len(onset) > int(0.09 * sr):
        onset = onset[-int(0.09 * sr):].copy()
        fade_in = int(0.02 * sr)
        onset[:fade_in] *= np.linspace(0, 1, fade_in)
    coda = coda[: int(0.08 * sr)].copy()
    if len(coda) > 8:
        coda *= np.linspace(1, 0, len(coda)) ** 0.7

    # 2. la voyelle dure jusqu'à la consonne finale (un peu de marge pour la hauteur vivante)
    need = max(int((seconds - len(coda) / sr) * sr), int(0.05 * sr))
    longer = need + int(0.06 * sr)
    if longer <= len(nucleus):
        vowel = nucleus[:longer].copy()
    else:
        period = max(2, int(round(sr / freq)))
        q = len(nucleus) // 4
        head = nucleus[: max(q, 1)]
        region = nucleus[q: len(nucleus) - q] if len(nucleus) - 2 * q > period * 3 else nucleus
        vowel = np.concatenate([head, _sustain(region, period, longer - len(head))])
        xf = min(int(0.012 * sr), len(head) // 2, len(vowel) - len(head))
        if xf > 4:  # jonction douce entre l'attaque naturelle et la tenue
            a = len(head) - xf
            vowel[a: a + xf] = nucleus[a: a + xf] * np.linspace(1, 0, xf) + vowel[a: a + xf] * np.linspace(0, 1, xf)
    # voyelle propre (souffle retiré), timbre enrichi dans l'aigu, puis hauteur vivante
    vowel = _enrich(_harmonic_clean(vowel, sr, freq), sr, freq)
    glide = 1200 * np.log2(glide_from / freq) if glide_from else 0.0
    vowel = _express(vowel, sr, rng, seconds, glide)[:need]
    # niveau régulier : chaque voyelle au même niveau, quelle que soit la syllabe prononcée
    vrms = float(np.sqrt(np.mean(vowel ** 2))) or 1e-6
    k = 0.1 / vrms
    vowel = vowel * k
    if swell and seconds > 0.7:  # la voix s'ouvre sur les notes longues (+1,5 dB au milieu), puis se pose
        x = np.linspace(0, 1, len(vowel))
        vowel *= 1 + 0.19 * np.sin(np.pi * np.clip(x * 1.15, 0, 1)) ** 2
    # consonnes renforcées (+3,5 dB à l'attaque, +2 dB en finale) : ce sont elles qui rendent les mots compréhensibles ;
    # le renfort ne porte que sur le médium (en dessous de 4 kHz) : les « s » et « ch » n'en profitent pas
    peak = float(np.max(np.abs(vowel))) or 1.0
    onset = np.clip(_consonant(onset, sr, k, 1.5), -peak * 1.1, peak * 1.1)
    coda = np.clip(_consonant(coda, sr, k, 1.26), -peak * 1.1, peak * 1.1)
    # fin de note posée
    rel = min(int(0.07 * sr), len(vowel) // 3)
    if rel > 0:
        vowel[-rel:] *= np.linspace(1, 0.35 if len(coda) else 0.0, rel) ** 1.5
    full = np.concatenate([onset, vowel, coda])
    full = _resample(full, sr)
    fade = min(len(full) // 4, int(0.012 * RATE))
    if fade > 0:
        full[:fade] *= np.linspace(0, 1, fade)
        full[-fade:] *= np.linspace(1, 0, fade)
    return full.astype(np.float32), len(onset) / sr


def _boost_mid(x: np.ndarray, sr: int, k: float, boost: float) -> np.ndarray:
    """Gain k partout, plus un renfort sur la partie médium (sous 4 kHz) seulement."""
    if len(x) < 32:
        return x * k
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    spec *= 1 + (boost - 1) / (1 + (f / 2500) ** 4)
    # « s », « ch », « j », « f », « r » soufflé : les aigus des consonnes (> 3 kHz) baissés de 10 dB — ce sont eux
    # qui sifflent ; le médium, qui porte l'articulation, reste intact
    spec *= 1 - (1 - 10 ** (-10 / 20)) / (1 + (3000 / np.maximum(f, 1)) ** 6)
    return np.fft.irfft(spec, len(x)) * k


def _is_fricative(x: np.ndarray, sr: int) -> bool:
    """Consonne soufflée (« s », « ch », « j », « f », « z », « r » soufflé) : énergie centrée haut, au-dessus de 1,8 kHz."""
    if len(x) < 64:
        return False
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return float((spec * f).sum() / (spec.sum() + 1e-15)) > 1800


def _consonant(x: np.ndarray, sr: int, k: float, boost: float) -> np.ndarray:
    """
    Consonnes : les articulées (m, n, l, b, d, t…) reçoivent un renfort de clarté ; les soufflées, qui sifflent,
    n'en reçoivent aucun — aigus baissés de 12 dB dès 2,2 kHz et niveau plafonné à 8 dB sous la voyelle.
    """
    if not _is_fricative(x, sr):
        return _boost_mid(x, sr, k, boost)
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    spec *= 1 - (1 - 10 ** (-12 / 20)) / (1 + (2200 / np.maximum(f, 1)) ** 6)
    y = np.fft.irfft(spec, len(x)) * k
    cap = 0.1 * 10 ** (-8 / 20)  # la voyelle est à 0,1 (efficace) : la consonne soufflée reste 8 dB en dessous
    rms = float(np.sqrt(np.mean(y ** 2))) or 1e-9
    return y * min(1.0, cap / rms)


def in_tune(y: np.ndarray, onset: float, freq: float) -> bool:
    """Contrôle d'une note d'un chanteur d'accompagnement : bien voisée et juste (à un demi-ton près)."""
    import parselmouth
    seg = y[int((onset + 0.04) * RATE):].astype(np.float64)
    if len(seg) < int(0.06 * RATE):
        return False
    f0 = parselmouth.Sound(seg, sampling_frequency=RATE).to_pitch(
        time_step=0.01, pitch_floor=max(50, freq * 0.6), pitch_ceiling=min(1500, freq * 1.6)).selected_array["frequency"]
    on = f0[f0 > 0]
    return len(on) >= 0.5 * len(f0) and abs(1200 * np.log2(np.median(on) / freq)) < 100


def breath(seconds: float, rng) -> np.ndarray:
    """Inspiration avant une phrase : souffle filtré (zone 500–3 500 Hz), qui monte puis s'arrête net."""
    n = max(int(seconds * RATE), 64)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / RATE)
    # souffle centré vers 900 Hz, sans aigus : une inspiration, pas un sifflement
    spec *= np.exp(-0.5 * (np.log2(np.maximum(f, 1) / 900) / 0.9) ** 2) / np.sqrt(1 + (f / 2500) ** 6)
    y = np.fft.irfft(spec, n)
    x = np.linspace(0, 1, n)
    y *= np.sin(np.pi * x ** 0.7) ** 1.5
    return (y / (np.sqrt(np.mean(y ** 2)) or 1) * 0.006).astype(np.float32)


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


def sing_part(part, qpm: float, kind: str, lang: str = "fr", lyrics_text: str | None = None, singers: int | None = None) -> np.ndarray:
    """Une voix entière chantée par un petit groupe de chanteurs (3 sur l'ordinateur), comme un pupitre de chœur."""
    notes = list(part.stripTies().flatten().notes)
    sec = 60.0 / qpm
    sylls = note_syllables(notes, lyrics_text)
    has_words = any(sylls)
    end = (float(notes[-1].offset + notes[-1].quarterLength) * sec + 1.5) if notes else 1.0
    buf = np.zeros(int(end * RATE) + RATE, np.float32)
    group = SINGERS.get(kind, SINGERS["femme"])[: singers or ensemble_size()]
    midis = [max(p.midi for p in n.pitches) for n in notes]
    center = float(np.median(midis)) if midis else 60.0

    # syllabe prononcée pour chaque note (la même pour tout le pupitre)
    texts, last_vowel, prev_end = [], "a", -1.0
    for n, syl in zip(notes, sylls):
        start = float(n.offset) * sec
        if syl is None:  # mélisme ou note sans parole : on tient la voyelle précédente (« a » sans paroles)
            texts.append(last_vowel if has_words else "a")
        else:
            t = pronounce(syl, lang)
            vowels = re.findall(r"[aeiouyéèêàâîôûœ]+n?", t)
            last_vowel = vowels[-1] if vowels else "a"
            texts.append(t)
        prev_end = start + float(n.quarterLength) * sec

    for k, singer in enumerate(group):
        rng = np.random.default_rng(1000 * k + len(notes))
        lead = k == 0
        prev_end, prev_freq = -1.0, None
        for n, midi, text, syl in zip(notes, midis, texts, sylls):
            start, dur = float(n.offset) * sec, float(n.quarterLength) * sec
            # chaque chanteur a son propre accord et ne chante jamais exactement en même temps que les autres
            cents = singer[2] + (0 if lead else rng.normal(0, 3))
            freq = 440.0 * 2 ** ((midi - 69 + cents / 100) / 12)
            shift = rng.normal(0, 0.004 if lead else 0.011)
            gap = start - prev_end
            legato = prev_freq is not None and gap < 0.06 and abs(12 * np.log2(prev_freq / freq)) <= 7
            y, onset = sing_syllable(singer, text, freq, dur * 0.97, kind, glide_from=prev_freq if legato else None, rng=rng)
            if not lead and not in_tune(y, onset, freq):  # note mal formée : ce choriste se tait sur cette note
                prev_end, prev_freq = start + dur, freq
                continue
            # nuances : les aigus un peu plus forts (comme chez un vrai chanteur), à ±2 dB au plus
            y = y * singer[3] * 10 ** (float(np.clip(0.13 * (midi - center), -2, 2)) / 20)
            if lead and (prev_end < 0 or gap >= 0.3):  # respiration avant chaque phrase
                b = breath(min(0.34, max(0.18, (gap if prev_end >= 0 else 0.5) * 0.6)), rng)
                bi = int(max(0.0, start - onset - 0.05) * RATE) - len(b)
                if bi > 0:
                    buf[bi: bi + len(b)] += b
            i = int(max(0.0, start - onset + shift) * RATE)
            j = min(len(buf), i + len(y))
            buf[i:j] += y[: j - i]
            prev_end, prev_freq = start + dur, freq
    if len(group) == 1:
        buf = chorus(buf)
    return buf  # niveaux et égalisation : mixage.polish_voice


def chorus(mono: np.ndarray) -> np.ndarray:
    """Effet de petit ensemble : deux copies légèrement décalées et désaccordées (sans resynthèse)."""
    n = len(mono)
    t = np.arange(n) / RATE
    out = mono.copy()
    # copies discrètes : assez pour un son d'ensemble, pas au point de brouiller les consonnes
    for delay_ms, rate_hz, depth_ms, gain in ((17, 0.31, 2.2, 0.3), (29, 0.23, 2.8, 0.22)):
        d = (delay_ms + depth_ms * np.sin(2 * np.pi * rate_hz * t)) * RATE / 1000
        idx = np.clip(np.arange(n) - d, 0, n - 1)
        out += gain * np.interp(idx, np.arange(n), mono).astype(np.float32)
    return out.astype(np.float32)
