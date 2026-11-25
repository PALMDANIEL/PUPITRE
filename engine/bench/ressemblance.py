"""
Les copies fabriquées (make_recueils.py) font-elles les mêmes erreurs que les vrais recueils ? Pour chaque famille
d'erreurs repérable sans bonne réponse, sa fréquence sur les lectures des copies fabriquées et sur celles des vrais
chants. Une famille absente des copies fabriquées ne s'y corrigera pas : le générateur est alors à revoir.

  <python du moteur> ressemblance.py <lectures des copies fabriquées> [<lectures des vrais chants> [index.json]]
      lectures : dossiers de cas contenant partition.musicxml|mxl (et truth.json pour les copies fabriquées)
"""
import collections, json, pathlib, sys, warnings

warnings.filterwarnings("ignore")
ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
from music21 import clef, converter, meter, stream  # noqa: E402
import arbitre, render  # noqa: E402


def facts(part_file):
    """Ce que la lecture montre : indication de mesure lue, nombre de mesures, mesures de durée fausse, clé de fa
    apparue en cours de chant, nombre de voix rendues."""
    sc = arbitre.drop_chord_symbols(converter.parse(str(part_file)))
    parts = [list(p.getElementsByClass(stream.Measure)) for p in sc.parts]
    ts_read = any(sc.recurse().getElementsByClass(meter.TimeSignature))
    bad = tot = 0
    for ms in parts:
        ts = None
        for k, m in enumerate(ms):
            ts = m.timeSignature or ts
            if ts is None or k in (0, len(ms) - 1) or not m.notes:
                continue
            tot += 1
            bad += abs(float(sum(e.duration.quarterLength for e in m.notesAndRests)) - ts.barDuration.quarterLength) > 1e-6
    bass_mid = any(isinstance(c, clef.BassClef) for ms in parts for m in ms[1:] for c in m.getElementsByClass(clef.Clef))
    voices = len(render.extract_voices(sc, trust_names=False))
    return dict(ts=ts_read, measures=max((len(ms) for ms in parts), default=0), bad=bad, tot=tot,
                bass_mid=bass_mid, voices=voices)


def cases(root):
    for d in sorted(pathlib.Path(root).rglob("partition.*")):
        if d.suffix in (".musicxml", ".mxl") and d.stem == "partition":
            yield d.parent, d


def summary(rows, label):
    n = len(rows)
    if not n:
        print(f"{label} : aucune lecture")
        return
    pct = lambda k: f"{100 * k / n:5.1f} %"  # noqa: E731
    bad = sum(r["bad"] for r in rows); tot = sum(r["tot"] for r in rows)
    print(f"\n{label} ({n} chants)")
    print(f"  indication de mesure non lue        {pct(sum(not r['ts'] for r in rows))}")
    if all("want_measures" in r for r in rows):
        print(f"  moins de mesures que la gravure     {pct(sum(r['measures'] < r['want_measures'] for r in rows))}")
        print(f"  plus de mesures que la gravure      {pct(sum(r['measures'] > r['want_measures'] for r in rows))}")
    if all("page_measures" in r for r in rows):
        print(f"  moins de mesures que la page        {pct(sum(r['measures'] < r['page_measures'] for r in rows))}")
        print(f"  plus de mesures que la page         {pct(sum(r['measures'] > r['page_measures'] for r in rows))}")
    print(f"  mesures de durée fausse             {100 * bad / max(tot, 1):5.1f} % des mesures")
    print(f"  clé de fa apparue en cours de chant {pct(sum(r['bass_mid'] for r in rows))}")
    print(f"  voix rendues                        {dict(sorted(collections.Counter(r['voices'] for r in rows).items()))}")


def main():
    synth = sys.argv[1]
    rows = []
    for case, part in cases(synth):
        tf = case / "truth.json"
        if not tf.exists():
            continue
        truth = json.loads(tf.read_text(encoding="utf-8"))
        try:
            r = facts(part)
        except Exception as e:  # noqa: BLE001
            print(f"{case.name} : {type(e).__name__}", file=sys.stderr)
            continue
        r["want_measures"] = truth.get("_mesures", r["measures"])
        rows.append(r)
    summary(rows, "Copies fabriquées")
    if len(sys.argv) > 2:
        real = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))  # erreurs.json des vrais chants
        rr = []
        for r in real:
            if r.get("etat") != "lu":
                continue
            rr.append(dict(ts=r["mesures_vues"] > 0 or None, measures=r["mesures_lues"], bad=r["mesures_fausses"],
                           tot=r["mesures_vues"], bass_mid=None, voices=r["voix"], page_measures=r.get("mesures_image", 0)))
        # indication lue et clé de fa : pas dans erreurs.json, prises dans familles_rendu.json s'il est là
        fam = pathlib.Path(sys.argv[2]).parent / "_analyse" / "familles.json"
        if fam.exists():
            by = {x["dossier"]: x for x in json.loads(fam.read_text(encoding="utf-8"))}
            for r, src in zip(rr, [x for x in real if x.get("etat") == "lu"]):
                f = by.get(src["dossier"])
                if f:
                    r["ts"] = not f["no_ts"]
                    r["bass_mid"] = f["bass_mid"] > 0
        summary(rr, "Vrais chants des recueils")


if __name__ == "__main__":
    main()
