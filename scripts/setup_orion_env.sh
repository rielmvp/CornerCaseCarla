#!/usr/bin/env bash
# ORION env: Python 3.8 + torch 2.4.1+cu118, per the ORION README.  -> envs/orion
set -euxo pipefail
cd "$(dirname "$0")/.."
P=${ENV_ROOT:-envs}/orion
conda create -y -p "$P" python=3.8
"$P/bin/python" -m pip install --no-cache-dir torch==2.4.1+cu118 torchvision==0.19.1+cu118 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu118
"$P/bin/python" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.device_count())"
