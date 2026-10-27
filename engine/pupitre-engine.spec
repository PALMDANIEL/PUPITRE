# PyInstaller : moteur Pupitre autonome (dossier pupitre-engine/ avec l'exécutable et ses bibliothèques).
#   pyinstaller --noconfirm engine/pupitre-engine.spec   (depuis la racine du dépôt)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

here = os.path.abspath(SPECPATH)

# music21 : ses données sans le corpus (des centaines de partitions de démonstration inutiles ici)
datas = [d for d in collect_data_files('music21') if f'{os.sep}corpus{os.sep}' not in d[0]]
datas += collect_data_files('pypdfium2_raw') + collect_data_files('pypdfium2')
binaries = collect_dynamic_libs('pypdfium2_raw') + collect_dynamic_libs('tinysoundfont') + collect_dynamic_libs('lameenc')

hidden = ['omr', 'preprocess', 'merge', 'render', 'chant', 'mixage'] + collect_submodules('music21')
hidden += ['pillow_heif', 'tinysoundfont', 'lameenc', 'pypdfium2']

# Voix chantées (requirements-chant.txt) : Piper et ses données espeak-ng, onnxruntime, Praat (parselmouth).
# Les voix elles-mêmes (~140 Mo) ne sont pas embarquées : l'application les télécharge au premier usage.
try:
    import piper, onnxruntime, parselmouth  # noqa: F401
    datas += collect_data_files('piper') + collect_data_files('onnxruntime')
    binaries += collect_dynamic_libs('onnxruntime') + collect_dynamic_libs('piper') + collect_dynamic_libs('parselmouth')
    hidden += collect_submodules('piper', filter=lambda n: not n.startswith('piper.train')) + ['onnxruntime', 'parselmouth', 'pathvalidate']
except ImportError:
    print('Voix chantées non embarquées : installez engine/requirements-chant.txt')

a = Analysis(
    [os.path.join(here, 'pupitre_engine.py')],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=['tkinter', 'matplotlib', 'IPython', 'jupyter', 'pytest', 'sympy.testing', 'onnxruntime.training'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pupitre-engine', console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='pupitre-engine', upx=False)
