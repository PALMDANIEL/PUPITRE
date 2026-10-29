"""
Lance homr (https://github.com/liebharc/homr, GNU AGPL v3) sur une image, sans modification : point d'entrée du
programme distinct pupitre-homr (engine/homr.spec), livré à côté de Pupitre comme Audiveris.
Usage : lire_homr <page.png>   → écrit <page>.musicxml à côté de l'image.
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    from homr.main import main
    sys.argv = ["homr", sys.argv[1]]
    main()
