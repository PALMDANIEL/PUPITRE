"""
Annotations publiques d'un circuit GitHub (lisibles sans compte) : GitHub coupe chaque message à 4000 caractères environ,
on envoie donc le texte en plusieurs morceaux, coupés entre deux copies.
Usage : python3 annoter.py <titre> <fichier> [début de ligne d'une nouvelle copie, par exemple « === »,
ou « retrait » : une ligne en retrait continue la copie de la ligne d'avant]
"""
import sys

LIMIT, MAX = 3800, 8  # au plus 10 annotations par étape : 8 pour ce texte


def blocks(lines, sep):
    """Lignes regroupées par copie (une ligne = une copie si aucun séparateur n'est donné)."""
    out = []
    for line in lines:
        if sep == "retrait":
            new = not line[:1].isspace()
        else:
            new = not sep or line.startswith(sep)
        if not out or new:
            out.append(line)
        else:
            out[-1] += "\n" + line
    return out


def main(title, path, sep=""):
    text = open(path, encoding="utf-8", errors="replace").read().rstrip("\n")
    chunks = [""]
    for b in blocks(text.splitlines(), sep):
        b = b[:LIMIT]
        if chunks[-1] and len(chunks[-1]) + len(b) + 1 > LIMIT:
            chunks.append("")
        chunks[-1] += ("\n" if chunks[-1] else "") + b
    if len(chunks) > MAX:
        chunks = chunks[:MAX]
        chunks[-1] += "\n… (suite coupée)"
    for k, c in enumerate(chunks, 1):
        label = title if len(chunks) == 1 else f"{title} ({k}/{len(chunks)})"
        label = label.replace("%", "%25").replace(",", "%2C").replace(":", "%3A")
        body = c.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title={label}::{body}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
