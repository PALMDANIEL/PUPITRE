"""
Rapport du banc d'essai (workflow banc.yml) : compare, copie par copie, le moteur de la branche et celui de la version
de référence. Usage : python3 rapport_banc.py <dossier des lectures>   (lecture-<moteur>-<part>/_resultats.json)
Écrit un résumé Markdown (en français) sur la sortie standard.
"""
import collections, json, pathlib, sys

NAMES = ["Soprano", "Alto", "Ténor", "Basse"]


def load(root):
    """{moteur: {copie: (notes justes, notes, 4 voix ?, échec)}}"""
    out = collections.defaultdict(dict)
    for d in sorted(pathlib.Path(root).glob("lecture-*")):
        moteur = d.name.split("-")[1]
        res_file = d / "_resultats.json"
        if not res_file.exists():
            continue
        for case, r in json.loads(res_file.read_text(encoding="utf-8")).items():
            tf = d / case / "truth.json"
            if not tf.exists():
                continue
            truth = json.loads(tf.read_text(encoding="utf-8"))
            total = sum(len(truth[n]) for n in NAMES)
            if "error" in r:
                out[moteur][case] = (0.0, total, False, r["error"])
                continue
            good = sum((r["acc"].get(n) or [0])[0] * len(truth[n]) for n in NAMES)
            out[moteur][case] = (good, total, r.get("voices") == 4, None)
    return out


def condition(case):
    """base-bwv269-fermee-net → (base, net) ; reels-bwv153.1-ouverte-floue → (reels, floue)."""
    corpus, rest = case.split("-", 1)
    return corpus, rest.rsplit("-", 1)[-1]


def main(root):
    data = load(root)
    ref, new = data.get("reference", {}), data.get("branche", {})
    cases = sorted(set(ref) & set(new))
    print("## Banc d'essai de lecture\n")
    print(f"{len(cases)} copies lues par les deux moteurs (référence : {len(ref)}, branche : {len(new)}).\n")
    print("| Corpus | Condition | Copies | Notes justes (référence) | Notes justes (branche) | Échecs réf. → branche |")
    print("|---|---|---|---|---|---|")
    groups = collections.defaultdict(list)
    for c in cases:
        groups[condition(c)].append(c)
    tot = [0.0, 0.0, 0]
    for (corpus, cond), cs in sorted(groups.items()):
        n = sum(ref[c][1] for c in cs)
        a, b = sum(ref[c][0] for c in cs), sum(new[c][0] for c in cs)
        fa, fb = sum(1 for c in cs if ref[c][3]), sum(1 for c in cs if new[c][3])
        tot[0] += a; tot[1] += b; tot[2] += n
        print(f"| {corpus} | {cond} | {len(cs)} | {a / n:.1%} | {b / n:.1%} | {fa} → {fb} |")
    if tot[2]:
        print(f"| **Total** | | {len(cases)} | **{tot[0] / tot[2]:.1%}** | **{tot[1] / tot[2]:.1%}** | |")
    worse = [(c, ref[c][0] / ref[c][1], new[c][0] / new[c][1]) for c in cases if new[c][0] < ref[c][0] - 0.02 * ref[c][1]]
    better = [c for c in cases if new[c][0] > ref[c][0] + 0.02 * ref[c][1]]
    print(f"\n**{len(better)} copies en progrès, {len(worse)} en recul** (écart de plus de 2 % des notes).\n")
    if worse:
        print("Reculs :\n")
        for c, x, y in sorted(worse, key=lambda t: t[2] - t[1]):
            print(f"- {c} : {x:.0%} → {y:.0%}" + (f" (échec : {new[c][3]})" if new[c][3] else ""))
    failed = [c for c in cases if new[c][3]]
    if failed:
        print("\nÉchecs de la branche :\n")
        for c in failed:
            print(f"- {c} : {new[c][3]}")


if __name__ == "__main__":
    main(sys.argv[1])
