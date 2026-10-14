#!/usr/bin/env bash
# Fetch the Alpamayo checkpoints and the processors they load.
#   scripts/download_models.sh            -> checkpoints/ (or $CKPT_ROOT) + the HF cache
#
# All of these are gated on Hugging Face: accept the license on each model page
# with your account, then `hf auth login` (or set HF_TOKEN) before running this.
#   nvidia/Alpamayo-R1-10B, nvidia/Alpamayo-1.5-10B   ~21 GB each
#   nvidia/Cosmos-Reason2-8B                          processor of Alpamayo 1.5
#   Qwen/Qwen3-VL-2B-Instruct                         processor of Alpamayo R1 (public)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
unset HF_HUB_OFFLINE
CKPT=${CKPT_ROOT:-checkpoints}
HF=.venv/bin/hf
for m in Alpamayo-R1-10B Alpamayo-1.5-10B; do
  "$HF" download "nvidia/$m" --local-dir "$CKPT/$m"
done
# processors are loaded by repo id, so they only need to be in the cache
"$HF" download nvidia/Cosmos-Reason2-8B --exclude "*.safetensors"
"$HF" download Qwen/Qwen3-VL-2B-Instruct --exclude "*.safetensors"
echo "done: $(du -sh "$CKPT" | cut -f1) in $CKPT"
