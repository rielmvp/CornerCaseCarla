#!/usr/bin/env bash
# AutoVLA env: Python 3.9, per its environment.yml.  -> envs/autovla
set -euxo pipefail
cd "$(dirname "$0")/.."
P=${ENV_ROOT:-envs}/autovla
conda create -y -p "$P" python=3.9 "numpy=1.23.4"
"$P/bin/python" -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121
"$P/bin/python" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.device_count())"
