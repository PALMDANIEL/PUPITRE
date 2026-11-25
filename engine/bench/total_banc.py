"""Total des notes justes d'un banc lu localement (run_bench.py), pondéré par le nombre de notes, par condition."""
import collections, json, pathlib, sys

root = pathlib.Path(sys.argv[1])
res = json.loads((root / "_resultats.json").read_text(encoding="utf-8"))
groups = collections.defaultdict(lambda: [0.0, 0])
for case, r in res.items():
    tf = root / case / "truth.json"
    if not tf.exists():
        continue
    truth = json.loads(tf.read_text(encoding="utf-8"))
    names = [n for n in truth if not n.startswith("_")]
    total = sum(len(truth[n]) for n in names)
    good = 0.0 if "error" in r else sum((r["acc"].get(n) or [0])[0] * len(truth[n]) for n in names)
    cond = case.rsplit("-", 1)[-1]
    for k in (cond, "TOTAL"):
        groups[k][0] += good; groups[k][1] += total
for k, (g, t) in sorted(groups.items()):
    print(f"{k:12s} {100 * g / max(t, 1):5.1f} %  ({t} notes)")
