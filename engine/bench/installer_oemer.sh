#!/bin/sh
# Banc d'essai : oemer (MIT) installé à part dans le conteneur (seulement pour un essai « [env: PUPITRE_OEMER=1] ») ;
# en cas d'échec, la fin du journal est publiée en annotation (lisible sans compte GitHub).
set -e
LOG=/tmp/oemer-install.log
{
  python3 -m venv /tmp/oemer
  /tmp/oemer/bin/pip install --no-deps oemer==0.1.5
  # versions essayées sur le Mac (onnxruntime plus récent : modèles refusés à l'ouverture de session)
  /tmp/oemer/bin/pip install onnxruntime==1.23.2 opencv-python-headless==4.14.0.94 numpy==2.5.4 scipy==1.18.1 \
    scikit-learn==1.9.1 pillow==13.0.0 matplotlib==3.11.2
  C=$(/tmp/oemer/bin/python3 -c "import oemer, os; print(os.path.dirname(oemer.__file__))")/checkpoints
  curl -fsSL -o "$C/unet_big/model.onnx" https://github.com/BreezeWhite/oemer/releases/download/checkpoints/1st_model.onnx
  curl -fsSL -o "$C/seg_net/model.onnx" https://github.com/BreezeWhite/oemer/releases/download/checkpoints/2nd_model.onnx
  ls -la "$C/unet_big" "$C/seg_net"
} > "$LOG" 2>&1 || { echo "::error title=oemer non installé::$(tail -c 900 $LOG | tr '\n' '|')"; exit 1; }
echo "::notice title=oemer::installé"
