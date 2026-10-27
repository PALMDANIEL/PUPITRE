"""
Traitement du son des voix chantées, comme un ingénieur du son au mixage :

- voix (mono) : coupe des graves inutiles, retrait du « boueux », mise en avant de la zone qui porte les paroles
  (2,5–3,5 kHz), adoucissement des aigus durs de la synthèse, compression douce pour égaliser les syllabes ;
- mixage (stéréo) : chaque voix au même niveau, légèrement répartie à gauche ou à droite pour bien distinguer
  les pupitres, petite salle (réverbération courte), volume final constant d'un chant à l'autre, sans saturation.

Tout se fait par FFT et opérations vectorisées (numpy seul) : rapide même sur un vieil ordinateur.
"""
from __future__ import annotations

import numpy as np

RATE = 44100

# Égalisation par type de voix : (passe-haut Hz, [(fréquence, gain dB, largeur en octaves)…], aigus Hz, gain dB)
EQ = {
    "femme": (110, [(300, -2.0, 0.8), (3000, 3.5, 0.9), (7500, -2.5, 0.5)], 11000, 1.0),
    "homme": (70, [(250, -2.0, 0.8), (2500, 3.0, 0.9), (6500, -2.0, 0.5)], 10000, 1.0),
}
TARGET_VOICE = -18.0   # niveau de travail d'une voix (dB, parties chantées)
TARGET_MASTER = -16.0  # niveau final d'un fichier (dB, parties chantées)
CEILING = 0.89         # crête maximale (−1 dB)


def db(x: float) -> float:
    return 20 * np.log10(max(float(x), 1e-9))


def active_rms(x: np.ndarray, frame: int = 2205) -> float:
    """Niveau des parties chantées seulement (les silences ne comptent pas), comme un loudness-mètre."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    n = len(mono) // frame
    if n == 0:
        return float(np.sqrt(np.mean(mono ** 2)) or 1e-9)
    r = np.sqrt(np.mean(mono[: n * frame].reshape(n, frame) ** 2, axis=1))
    gate = r.max() * 10 ** (-40 / 20)
    on = r[r > gate]
    return float(np.sqrt(np.mean(on ** 2))) if len(on) else 1e-9


def _moving(x: np.ndarray, width: int) -> np.ndarray:
    """Moyenne glissante centrée (somme cumulée) : lissage sans boucle Python."""
    width = max(1, int(width))
    c = np.cumsum(np.concatenate([[0.0], x]))
    half = width // 2
    idx = np.arange(len(x))
    lo, hi = np.clip(idx - half, 0, len(x)), np.clip(idx - half + width, 0, len(x))
    return (c[hi] - c[lo]) / np.maximum(hi - lo, 1)


def equalize(x: np.ndarray, kind: str) -> np.ndarray:
    """Égaliseur à phase nulle (FFT) : courbes douces, aucun artefact de filtre."""
    hp, bells, shelf_f, shelf_g = EQ.get(kind, EQ["femme"])
    n = len(x)
    if n < 64:
        return x
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / RATE)
    f[0] = 1.0
    gain_db = np.zeros_like(f)
    for f0, g, bw in bells:
        gain_db += g * np.exp(-0.5 * (np.log2(f / f0) / (bw / 2)) ** 2)
    gain_db += shelf_g / (1 + np.exp(-np.log2(f / shelf_f) * 6))
    mag = 10 ** (gain_db / 20) / np.sqrt(1 + (hp / f) ** 4)  # passe-haut 12 dB/octave
    mag[0] = 0.0
    return np.fft.irfft(spec * mag, n).astype(np.float32)


def highpass(x: np.ndarray, fc: float, rate: int = RATE) -> np.ndarray:
    """Passe-haut à phase nulle (24 dB/octave) : retire composante continue et grondements inaudibles."""
    n = len(x)
    if n < 64:
        return x - float(np.mean(x))
    f = np.fft.rfftfreq(n, 1 / rate)
    f[0] = 1e-3
    return np.fft.irfft(np.fft.rfft(x) / np.sqrt(1 + (fc / f) ** 8), n)


def compress(x: np.ndarray, threshold_db: float = -24.0, ratio: float = 3.0, knee_db: float = 6.0) -> np.ndarray:
    """Compresseur doux (genou souple), détection RMS 12 ms, gain lissé 40 ms : égalise syllabes et notes."""
    env = np.sqrt(_moving(x.astype(np.float64) ** 2, 0.012 * RATE)) + 1e-9
    level = 20 * np.log10(env)
    over = level - threshold_db
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                           (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    gain = 10 ** (-_moving(gr, 0.04 * RATE) / 20)
    return (x * gain).astype(np.float32)


def level_to(x: np.ndarray, target_db: float) -> np.ndarray:
    return (x * 10 ** ((target_db - db(active_rms(x))) / 20)).astype(np.float32)


def polish_voice(x: np.ndarray, kind: str) -> np.ndarray:
    """Une voix chantée prête à mixer : égalisée, compressée, au niveau de travail."""
    x = level_to(x, TARGET_VOICE)
    x = equalize(x, kind)
    x = compress(level_to(x, TARGET_VOICE), threshold_db=TARGET_VOICE - 4)
    return level_to(x, TARGET_VOICE)


_IR = None


def _impulse() -> np.ndarray:
    """Petite salle (chapelle de taille modeste) : 18 ms de pré-délai, déclin 0,9 s, queue adoucie, stéréo décorrélée."""
    global _IR
    if _IR is None:
        rng = np.random.default_rng(7)
        n = int(1.1 * RATE)
        t = np.arange(n) / RATE
        decay = np.exp(-6.9 * t / 0.9)
        ir = np.zeros((n, 2), np.float64)
        for ch in range(2):
            noise = rng.standard_normal(n)
            spec = np.fft.rfft(noise)
            fr = np.fft.rfftfreq(n, 1 / RATE)
            spec *= 1 / np.sqrt(1 + (fr / 5000) ** 2) / np.sqrt(1 + (200 / np.maximum(fr, 1)) ** 2)
            ir[:, ch] = np.fft.irfft(spec, n) * decay
        pre = int(0.018 * RATE)
        ir = np.concatenate([np.zeros((pre, 2)), ir])[:n]
        for d, g in ((0.011, 0.35), (0.023, 0.25), (0.031, 0.2)):  # premières réflexions
            k = int(d * RATE)
            ir[k, 0] += g; ir[int(k * 1.13), 1] += g
        _IR = ir / np.sqrt(np.sum(ir ** 2, axis=0, keepdims=True))
    return _IR


def reverb(stereo: np.ndarray, wet: float = 0.16) -> np.ndarray:
    ir = _impulse()
    n = len(stereo) + len(ir)
    size = 1 << int(np.ceil(np.log2(n)))
    out = np.empty((len(stereo), 2), np.float32)
    for ch in range(2):
        y = np.fft.irfft(np.fft.rfft(stereo[:, ch], size) * np.fft.rfft(ir[:, ch], size), size)[: len(stereo)]
        out[:, ch] = stereo[:, ch] + wet * y * 0.35
    return out


def limit(x: np.ndarray, ceiling: float = CEILING) -> np.ndarray:
    """Limiteur doux : rien ne dépasse −1 dB, sans écrêtage dur."""
    knee = ceiling * 0.8
    a = np.abs(x)
    over = a > knee
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (ceiling - knee) * np.tanh((a[over] - knee) / (ceiling - knee)))
    return y


def pan_positions(n: int) -> list[float]:
    """Soprano et ténor un peu à gauche, alto et basse un peu à droite (comme un chœur en demi-cercle)."""
    return {1: [0.0], 2: [-0.25, 0.25], 3: [-0.3, 0.0, 0.3], 4: [-0.35, 0.35, -0.2, 0.2]}.get(n, list(np.linspace(-0.35, 0.35, n)))


def mix_stereo(tracks: list[tuple[np.ndarray, float, float]]) -> np.ndarray:
    """(voix mono, gain, position −1…+1) → stéréo, loi de panoramique à puissance constante."""
    n = max(len(t) for t, _, _ in tracks)
    out = np.zeros((n, 2), np.float32)
    for t, g, p in tracks:
        ang = (p + 1) * np.pi / 4
        out[: len(t), 0] += t * g * np.cos(ang)
        out[: len(t), 1] += t * g * np.sin(ang)
    return out


def master(stereo: np.ndarray) -> np.ndarray:
    """Fichier final : salle, volume constant (−16 dB sur les parties chantées), limiteur."""
    x = reverb(stereo)
    x = level_to(x, TARGET_MASTER)
    return limit(x)
