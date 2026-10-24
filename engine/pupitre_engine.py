"""
Point d'entrée unique du moteur, pour l'exécutable autonome (PyInstaller) de la version installable.
Usage : pupitre-engine <omr|preprocess|merge|render> [arguments de l'étape]
En développement, on peut toujours lancer directement python3 omr.py, render.py…
"""
import runpy, sys

STEPS = ("omr", "preprocess", "merge", "render")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in STEPS:
        sys.exit(f"Usage : pupitre-engine <{'|'.join(STEPS)}> …")
    step = sys.argv[1]
    sys.argv = [step] + sys.argv[2:]
    runpy.run_module(step, run_name="__main__")


if __name__ == "__main__":
    main()
