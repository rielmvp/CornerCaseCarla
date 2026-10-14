#!/usr/bin/env bash
# Build the Python environment: one venv for Scenic, the CARLA client and Alpamayo.
#   scripts/setup_env.sh                 -> .venv (Python 3.12)
# Uses uv when available (fast, fetches Python 3.12 if missing), else python3.12 -m venv.
set -euo pipefail
cd "$(dirname "$0")/.."
git submodule update --init third_party/Carlamayo
git -C third_party/Carlamayo submodule update --init third_party/alpamayo1 third_party/alpamayo1.5
VENV=${VENV:-.venv}
if command -v uv >/dev/null; then
  uv venv --python 3.12 "$VENV"
  PIP=(uv pip install --python "$VENV/bin/python")
else
  python3.12 -m venv "$VENV"
  PIP=("$VENV/bin/python" -m pip install)
fi
"${PIP[@]}" -r requirements/alpamayo.txt
# The Alpamayo packages pin flash-attn and physical_ai_av, neither of which the
# CARLA path needs; install them without dependencies, the rest is pinned above.
"${PIP[@]}" --no-deps -e third_party/Carlamayo/third_party/alpamayo1 \
                      -e third_party/Carlamayo/third_party/alpamayo1.5
"$VENV/bin/python" -c "import carla, scenic, torch, transformers, alpamayo_r1, alpamayo1_5; \
print('ok: carla', carla.__file__.split('/')[-2], '| torch', torch.__version__, '| cuda', torch.cuda.is_available())"
