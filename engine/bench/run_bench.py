"""
Banc d'essai : passe chaque cas dans la vraie chaîne (omr.py puis la séparation des voix de render.py)
et compare aux notes attendues.
Usage : <python du moteur> run_bench.py <dossier_corpus> [filtre] [--reuse] [-j 2]
  --reuse : ne relance pas Audiveris si partition.* existe déjà (pour itérer sur la séparation des voix).
Pour une vraie partition sans truth.json, on affiche seulement le nombre de voix et les tessitures.
"""
import argparse, concurrent.futures as cf, json, pathlib, subprocess, sys, time

ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
import render  # noqa: E402
from music21 import converter  # noqa: E402

NAMES = ["Soprano", "Alto", "Ténor", "Basse"]
# tessitures plausibles (MIDI) : au-delà, c'est presque toujours une erreur de lecture
RANGES = {"Soprano": (57, 84), "Alto": (52, 77), "Ténor": (45, 72), "Basse": (36, 64)}


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def score_voice(got, want):
    if not want:
        return None
    exact = max(0.0, 1 - lev(got, want) / len(want))
    pc = max(0.0, 1 - lev([g % 12 for g in got], [w % 12 for w in want]) / len(want))
    return exact, pc


def read_voices(partition):
    sc = converter.parse(str(partition))
    voices = render.extract_voices(sc, trust_names=False)
    return [[int(p.midi) for n in v.recurse().notes for p in [max(n.pitches, key=lambda q: q.ps)]] for v in voices]


def run_case(case: pathlib.Path, reuse: bool):
    src = next(p for p in case.iterdir() if p.name.startswith("source."))
    part = next((p for p in case.glob("partition.*")), None)
    t0 = time.time()
    if not (reuse and part):
        r = subprocess.run([sys.executable, str(ENGINE / "omr.py"), str(src), str(case)], capture_output=True, text=True)
        if r.returncode:
            return case.name, {"error": (r.stderr.strip().splitlines() or ["?"])[-1][:160]}
        part = next((p for p in case.glob("partition.*")), None)
    try:
        voices = read_voices(part)
    except Exception as e:  # noqa: BLE001
        return case.name, {"error": f"séparation : {e}"[:160]}
    res = {"voices": len(voices), "secs": round(time.time() - t0)}
    truth_file = case / "truth.json"
    names = NAMES if len(voices) == 4 else [f"V{i+1}" for i in range(len(voices))]
    res["ranges"] = {names[i]: (min(v), max(v)) for i, v in enumerate(voices) if v}
    if truth_file.exists():
        truth = json.loads(truth_file.read_text())
        res["acc"] = {}
        for i, name in enumerate(NAMES):
            got = voices[i] if i < len(voices) and len(voices) == 4 else []
            res["acc"][name] = score_voice(got, truth[name])
    return case.name, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus"); ap.add_argument("filter", nargs="?", default="")
    ap.add_argument("--reuse", action="store_true"); ap.add_argument("-j", type=int, default=2)
    a = ap.parse_args()
    cases = sorted(p for p in pathlib.Path(a.corpus).iterdir()
                   if p.is_dir() and not p.name.startswith("_") and a.filter in p.name)
    results = {}
    with cf.ThreadPoolExecutor(a.j) as ex:
        for name, res in ex.map(lambda c: run_case(c, a.reuse), cases):
            results[name] = res
            if "error" in res:
                print(f"{name:34} ÉCHEC  {res['error']}", flush=True)
                continue
            line = f"{name:34} {res['voices']} voix"
            if "acc" in res:
                line += "  " + "  ".join(f"{n[0]}:{'—' if v is None else f'{v[0]:.0%}/{v[1]:.0%}'}" for n, v in res["acc"].items())
            else:
                line += "  " + "  ".join(f"{n}:{lo}-{hi}" for n, (lo, hi) in res["ranges"].items())
            print(line, flush=True)
    scored = [r for r in results.values() if "acc" in r]
    if scored:
        allv = [v[0] for r in scored for v in r["acc"].values() if v]
        four = sum(1 for r in scored if r.get("voices") == 4)
        print(f"\nCas notés : {len(scored)}/{len(results)} · 4 voix : {four}/{len(scored)} · justesse moyenne (note exacte) : {sum(allv)/max(len(allv),1):.0%}")
    (pathlib.Path(a.corpus) / "_resultats.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
