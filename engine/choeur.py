"""
Chœur réel (« aah », « ouh ») : chaque note est jouée par de vrais chanteurs enregistrés (3 à 10 par note),
issus de VocalSet via epic-choir (CC BY 4.0, voir choeur/LISEZ-MOI.txt).

Pour chaque note : l'enregistrement du pupitre le plus proche (au plus un demi-ton d'écart, ajusté sans artefact
par transformée de Fourier), attaque douce, enchaînement lié avec la note précédente, fin de note naturelle,
et boucle fondue pour les notes plus longues que l'enregistrement (6 s). Chaque enregistrement a été mesuré une fois (choeur/index.json) :
instant où le chœur est posé (juste, plein volume), et petit écart d'accord, compensé.
"""
from __future__ import annotations

import functools
import json
import os
import pathlib
import wave

import numpy as np

RATE = 44100
VOWELS = ("ah", "oo")


def pack_dir() -> pathlib.Path:
    import sys
    if os.environ.get("CHOEUR_DIR"):
        return pathlib.Path(os.environ["CHOEUR_DIR"])
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    return base / "choeur"


@functools.lru_cache(maxsize=None)
def _index() -> dict:
    return json.loads((pack_dir() / "index.json").read_text())


def available() -> bool:
    return (pack_dir() / "index.json").exists()


@functools.lru_cache(maxsize=128)
def _sample(name: str) -> np.ndarray:
    w = wave.open(str(pack_dir() / name))
    return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768


def _repitch(x: np.ndarray, semitones: float) -> np.ndarray:
    """Change la hauteur (et la durée) par rééchantillonnage à bande limitée : pas d'images, pas de sifflement."""
    if abs(semitones) < 1e-3:
        return x
    ratio = 2 ** (semitones / 12)
    n = int(round(len(x) / ratio))
    spec = np.fft.rfft(x)
    out = np.zeros(n // 2 + 1, dtype=complex)
    k = min(len(spec), len(out))
    out[:k] = spec[:k]
    if ratio > 1:  # plus aigu : on coupe ce qui dépasserait la moitié de la fréquence d'échantillonnage
        f = np.fft.rfftfreq(n, 1 / RATE)
        out *= 1 / np.sqrt(1 + (f / (0.47 * RATE)) ** 16)
    return np.fft.irfft(out, n) * (n / len(x))


def part_for(midis: list[int], hint: str | None = None) -> str:
    """Pupitre dont la tessiture couvre le mieux la voix (ou celui indiqué : soprano, alto, ténor, basse)."""
    if hint in ("S", "A", "T", "B"):
        return hint
    idx = _index()
    best, score = "A", -1.0
    for part, vowels in idx.items():
        lo = min(r["lo"] for r in vowels["ah"]); hi = max(r["hi"] for r in vowels["ah"])
        inside = np.mean([lo <= m <= hi for m in midis]) if midis else 0
        center = abs(np.median(midis) - (lo + hi) / 2) if midis else 0
        s = inside - 0.01 * center
        if s > score:
            best, score = part, s
    return best


def _region(part: str, vowel: str, midi: int) -> dict:
    regions = _index()[part][vowel]
    return min(regions, key=lambda r: abs(r["center"] - midi))


def _note(part: str, vowel: str, midi: int, seconds: float) -> np.ndarray:
    """Une note du pupitre, durée exacte, avec sa fin naturelle (0,35 s) au-delà."""
    r = _region(part, vowel, midi)
    # on part de l'instant où le chœur est posé (juste, plein volume) et on compense l'accord de l'enregistrement
    x = _sample(r["file"])[int(r.get("start", 0.0) * RATE):]
    x = _repitch(x, midi - r["center"] - r.get("tune", 0.0) / 100)
    need = int((seconds + 0.35) * RATE)
    if need > len(x):  # note plus longue que l'enregistrement : boucle fondue sur la partie stable
        a, b = int(1.5 * RATE), len(x) - int(0.6 * RATE)
        loop = x[a:b]
        xf = int(0.25 * RATE)
        out = x[:b].copy()
        fade_in, fade_out = np.linspace(0, 1, xf), np.linspace(1, 0, xf)
        while len(out) < need:
            seg = loop.copy()
            seg[:xf] = seg[:xf] * fade_in + out[-xf:] * fade_out
            out = np.concatenate([out[:-xf], seg])
        x = out.astype(np.float32)
    x = x[:need].copy()
    rel = int(0.35 * RATE)
    x[-rel:] *= np.linspace(1, 0, rel) ** 2
    return x


def sing_part(part_stream, qpm: float, vowel: str = "ah", hint: str | None = None) -> np.ndarray:
    """Une voix entière jouée par le pupitre réel, notes liées entre elles comme un vrai chœur."""
    vowel = vowel if vowel in VOWELS else "ah"
    notes = list(part_stream.stripTies().flatten().notes)
    sec = 60.0 / qpm
    midis = [max(p.midi for p in n.pitches) for n in notes]
    part = part_for(midis, hint)
    end = (float(notes[-1].offset + notes[-1].quarterLength) * sec + 2.0) if notes else 1.0
    buf = np.zeros(int(end * RATE) + RATE, np.float32)
    prev_end = -1.0
    for n, midi in zip(notes, midis):
        start, dur = float(n.offset) * sec, float(n.quarterLength) * sec
        legato = abs(start - prev_end) < 0.05
        x = _note(part, vowel, midi, dur)
        att = int((0.06 if legato else 0.035) * RATE)  # attaque courte et naturelle ; liée, elle fond avec la précédente
        x[:att] *= np.linspace(0, 1, att) ** (0.5 if legato else 1.0)
        i = int(max(0.0, start - (0.04 if legato else 0.0)) * RATE)
        j = min(len(buf), i + len(x))
        buf[i:j] += x[: j - i]
        prev_end = start + dur
    return buf
