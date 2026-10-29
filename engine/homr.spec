# PyInstaller : homr, programme distinct (licence GNU AGPL v3, https://github.com/liebharc/homr), livré à côté de
# Pupitre comme Audiveris et appelé par lui sans modification. Lit les notes des copies usées.
#   python -c "import sys; sys.argv=['homr','--init']; from homr.main import main; main()"   (modèles, une fois)
#   pyinstaller --noconfirm engine/homr.spec   (depuis la racine du dépôt) → dossier pupitre-homr/
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
from homr.segmentation.config import segnet_path_onnx

here = os.path.abspath(SPECPATH)
if not os.path.exists(segnet_path_onnx):
    raise SystemExit("Modèles de homr absents : lancez d'abord homr --init")

no_tests = lambda n: '.tests' not in n and '.test_' not in n  # noqa: E731
datas = collect_data_files('homr') + collect_data_files('rapidocr_onnxruntime') + collect_data_files('onnxruntime')
datas += collect_data_files('musicxml', includes=['**/*.xsd', '**/*.xml', '**/*.json'])  # schéma lu au chargement
binaries = collect_dynamic_libs('onnxruntime') + collect_dynamic_libs('shapely') + collect_dynamic_libs('pyclipper')
hidden = collect_submodules('homr', filter=no_tests) + collect_submodules('musicxml', filter=no_tests)
hidden += collect_submodules('rapidocr_onnxruntime', filter=no_tests) + ['onnxruntime', 'shapely', 'pyclipper', 'yaml']

a = Analysis(
    [os.path.join(here, 'lire_homr.py')],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=['tkinter', 'matplotlib', 'IPython', 'jupyter', 'pytest', 'music21', 'onnxruntime.training'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pupitre-homr', console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='pupitre-homr', upx=False)
