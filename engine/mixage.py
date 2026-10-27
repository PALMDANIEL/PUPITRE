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
    "femme": (110, [(300, -2.0, 0.8), (2800, 2.5, 0.9), (7000, -3.5, 0.7)], 9500, -6.0),
    "homme": (70, [(250, -2.0, 0.8), (2500, 2.5, 0.9), (6500, -3.0, 0.7)], 9000, -6.0),
}
TARGET_VOICE = -18.0   # niveau de travail d'une voix (dB, parties chantées)
TARGET_MASTER = -16.0  # niveau final d'un fichier (dB, parties chantées)
CEILING = 0.89         # crête maximale (−1 dB)


def fast_len(n: int) -> int:
    """Plus petite longueur ≥ n qui ne se décompose qu'en 2, 3 et 5 : la transformée de Fourier y est très rapide
    (une longueur avec un grand facteur premier peut la rendre des dizaines de fois plus lente)."""
    best = 1 << max(0, (n - 1).bit_length())
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def apply_curve(x: np.ndarray, gain, rate: int = RATE) -> np.ndarray:
    """Filtre à phase nulle : gain(f) appliqué au spectre (longueur rapide, puis on recoupe à la longueur d'origine)."""
    n = len(x)
    if n < 64:
        return x
    size = fast_len(n + 2048)  # un peu de marge : rien ne revient en boucle du bout vers le début
    f = np.fft.rfftfreq(size, 1 / rate)
    f[0] = 1e-3
    return np.fft.irfft(np.fft.rfft(x, size) * gain(f), size)[:n]


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

    def curve(f):
        gain_db = np.zeros_like(f)
        for f0, g, bw in bells:
            gain_db += g * np.exp(-0.5 * (np.log2(f / f0) / (bw / 2)) ** 2)
        gain_db += shelf_g / (1 + np.exp(-np.log2(f / shelf_f) * 6))
        return 10 ** (gain_db / 20) / np.sqrt(1 + (hp / f) ** 4)  # passe-haut 12 dB/octave
    return apply_curve(x, curve).astype(np.float32)


def highpass(x: np.ndarray, fc: float, rate: int = RATE) -> np.ndarray:
    """Passe-haut à phase nulle (24 dB/octave) : retire composante continue et grondements inaudibles."""
    if len(x) < 64:
        return x - float(np.mean(x))
    return apply_curve(x, lambda f: 1 / np.sqrt(1 + (fc / f) ** 8), rate)


def lowpass(x: np.ndarray, fc: float) -> np.ndarray:
    """Passe-bas à phase nulle, pente douce (pas de sonnerie)."""
    return apply_curve(x, lambda f: 1 / np.sqrt(1 + (f / fc) ** 12)).astype(np.float32)


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


def deess(x: np.ndarray, split: float = 4500.0, margin_db: float = -4.0) -> np.ndarray:
    """
    Dé-esseur : quand les aigus (au-dessus de 4,5 kHz, la zone des « s » et « ch ») dépassent le médium de plus
    que la marge, on les ramène à la marge ; le reste du son n'est pas touché.
    """
    n = len(x)
    if n < 1024:
        return x
    hi = apply_curve(x, lambda f: 1 / np.sqrt(1 + (split / np.maximum(f, 1)) ** 8))
    lo = x - hi
    e_hi = np.sqrt(_moving(hi ** 2, 0.008 * RATE)) + 1e-9
    e_lo = np.sqrt(_moving(lo ** 2, 0.008 * RATE)) + 1e-9
    excess = 20 * np.log10(e_hi / e_lo) - margin_db
    # plafond absolu : un « sss » seul (sans médium à comparer) ne dépasse jamais −12 dB sous le niveau de la voix
    ceiling = active_rms(x) * 10 ** (-12 / 20)
    excess = np.maximum(excess, 20 * np.log10(e_hi / ceiling))
    gain = 10 ** (-np.clip(_moving(np.maximum(excess, 0), 0.012 * RATE), 0, 24) / 20)
    return (lo + hi * gain).astype(np.float32)


def polish_voice(x: np.ndarray, kind: str) -> np.ndarray:
    """Une voix chantée prête à mixer : sifflantes maîtrisées, égalisée, compressée, au niveau de travail."""
    x = level_to(x, TARGET_VOICE)
    x = deess(x)
    x = equalize(x, kind)
    x = compress(level_to(x, TARGET_VOICE), threshold_db=TARGET_VOICE - 4)
    x = deess(x, margin_db=-6.0)  # second passage : la compression a pu remonter quelques « s »
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


def master(stereo: np.ndarray, wet: float = 0.16) -> np.ndarray:
    """Fichier final des voix chantées et du chœur réel : salle, volume perçu −14 LUFS, limiteur."""
    x = reverb(stereo, wet) if wet > 0 else stereo
    x = np.stack([lowpass(x[:, c], 10500) for c in range(x.shape[1])], axis=1)  # rien d'utile au-dessus de 11 kHz
    return finish(x)


# --- Audibilité : volume perçu commun, basses audibles sur téléphone, clarté -------------------------------------

TARGET_LUFS = -14.0  # volume perçu de référence (plateformes d'écoute, téléphones)


def lufs(x: np.ndarray) -> float:
    """Volume perçu intégré (pondération K et double fenêtrage de la norme UIT-R BS.1770), en LUFS."""
    st = x if x.ndim == 2 else x[:, None]
    n = len(st)
    if n < RATE // 2:
        return -70.0
    k = lambda f: 10 ** ((4.0 / (1 + (1500 / f) ** 2)) / 20) / np.sqrt(1 + (38 / f) ** 4)
    y = np.stack([apply_curve(st[:, c], k) for c in range(st.shape[1])], axis=1)
    blk, hop = int(0.4 * RATE), int(0.1 * RATE)
    c = np.concatenate([[0.0], np.cumsum((y ** 2).sum(axis=1))])
    starts = np.arange(0, n - blk, hop)
    e = (c[starts + blk] - c[starts]) / blk + 1e-15
    loud = -0.691 + 10 * np.log10(e)
    gated = e[loud > -70]
    if not len(gated):
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    final = e[loud > max(-70, rel)]
    return float(-0.691 + 10 * np.log10(np.mean(final)))


def phone_bass(x: np.ndarray, amount: float) -> np.ndarray:
    """
    Voix graves audibles sur un petit haut-parleur (téléphone), qui ne restitue presque rien sous 300 Hz :
    on renforce les harmoniques naturelles de la note (300 Hz – 1 kHz, jusqu'à +6 dB) et on allège l'extrême grave
    (jusqu'à −3 dB sous 140 Hz). L'oreille reconstitue la note à partir de ses harmoniques. Aucune harmonique
    fabriquée : rien ne peut s'annuler avec celles de l'instrument. amount : 0 (rien) à 1 (basse).
    """
    if amount <= 0 or len(x) < 1024:
        return x
    return apply_curve(x, lambda f: 10 ** (phone_bass_db(f, amount) / 20)).astype(np.float32)


def phone_bass_db(f: np.ndarray, amount: float) -> np.ndarray:
    return amount * (6.0 * np.exp(-0.5 * (np.log2(f / 560) / 0.8) ** 2) - 3.0 / (1 + (f / 140) ** 4))


def bass_amount(midis, top: float = 67) -> float:
    """Dose de renfort des harmoniques selon la tessiture : pleine pour une basse, forte pour un ténor, rien en haut.
    top : note médiane à partir de laquelle on ne renforce plus (plus haut pour le piano, au son très « fondamental »)."""
    if not len(midis):
        return 0.0
    m = float(np.median(midis))
    return float(np.clip((top - m) / 10, 0, 1))


SYNTH_EQ = {  # Chœur synthé et Piano (TinySoundFont) : clarté et place pour les voix
    "choeur": [(120, -2.0, 1.2), (300, -1.5, 0.8), (2800, 3.5, 1.0)],
    "piano": [(110, -3.0, 1.2), (350, -1.5, 0.8), (3000, 3.0, 1.0), (7500, 1.5, 0.8)],
}


def bells_db(f: np.ndarray, bells) -> np.ndarray:
    g = np.zeros_like(f)
    for f0, gain, bw in bells:
        g += gain * np.exp(-0.5 * (np.log2(f / f0) / (bw / 2)) ** 2)
    return g


def eq_bells(x: np.ndarray, bells) -> np.ndarray:
    return apply_curve(x, lambda f: 10 ** (bells_db(f, bells) / 20)).astype(np.float32)


def finish(stereo: np.ndarray, kind: str | None = None, midis=None) -> np.ndarray:
    """Fichier final de toute sonorité : égalisation propre à la sonorité, basses audibles, −14 LUFS, limiteur."""
    x = stereo if stereo.ndim == 2 else np.stack([stereo, stereo], axis=1)
    x = x.astype(np.float32)
    if kind in SYNTH_EQ:
        amt = 0.8 if midis is None else bass_amount(midis, top=73 if kind == "piano" else 67)

        def curve(f):  # égalisation, voix graves audibles, et (chœur) aigus de synthèse coupés : en une seule passe
            g = 10 ** ((bells_db(f, SYNTH_EQ[kind]) + phone_bass_db(f, amt)) / 20)
            return g / np.sqrt(1 + (f / 9000) ** 12) if kind == "choeur" else g
        x = np.stack([apply_curve(x[:, c], curve) for c in range(2)], axis=1).astype(np.float32)
    gain = 10 ** ((TARGET_LUFS - lufs(x)) / 20)
    return limit(x * gain)
