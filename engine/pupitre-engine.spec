# PyInstaller : moteur Pupitre autonome (dossier pupitre-engine/ avec l'exécutable et ses bibliothèques).
#   pyinstaller --noconfirm engine/pupitre-engine.spec   (depuis la racine du dépôt)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

here = os.path.abspath(SPECPATH)

# music21 : ses données sans le corpus (des centaines de partitions de démonstration inutiles ici)
datas = [d for d in collect_data_files('music21') if f'{os.sep}corpus{os.sep}' not in d[0]]
datas += collect_data_files('pypdfium2_raw') + collect_data_files('pypdfium2')
binaries = collect_dynamic_libs('pypdfium2_raw') + collect_dynamic_libs('tinysoundfont') + collect_dynamic_libs('lameenc')

hidden = ['omr', 'preprocess', 'merge', 'render'] + collect_submodules('music21')
hidden += ['pillow_heif', 'tinysoundfont', 'lameenc', 'pypdfium2']

a = Analysis(
    [os.path.join(here, 'pupitre_engine.py')],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=['tkinter', 'matplotlib', 'IPython', 'jupyter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pupitre-engine', console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='pupitre-engine', upx=False)
