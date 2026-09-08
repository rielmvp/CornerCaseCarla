#!/usr/bin/env bash
# Drive the curated corner cases with both Alpamayo versions and record what happened.
#   scripts/run_corner_cases.sh [comma-separated scenario ids]
# Default: the five cases the studio offers. Needs a CARLA server on $CARLA_PORT
# (scripts/start_carla.sh). Writes outputs/runs/: three videos per run, a per-step
# trace, and results_r1.jsonl / results_v15.jsonl with collisions and timings.
# Re-running resumes: scenarios already in the results file are skipped.
set -euo pipefail
cd "$(dirname "$0")/.."
SCEN=${1:-curated_08,curated_01,curated_05,curated_09,curated_10}
PORT=${CARLA_PORT:-2000}
export CUDA_VISIBLE_DEVICES=${GPU:-0}
for VER in 1 1.5; do
  .venv/bin/python cornercase/alpamayo_runner.py --scenarios "$SCEN" --version "$VER" \
    --port "$PORT" --steps "${STEPS:-100}" --seed 42 ${EXTRA_ARGS:-}
done
.venv/bin/python - <<'PY'
import json, os, sys
sys.path.insert(0, "cornercase"); import paths
for tag in ("r1", "v15"):
    f = os.path.join(paths.RUNS, f"results_{tag}.jsonl")
    if not os.path.exists(f): continue
    rows = {}
    for l in open(f):
        if l.startswith("{"): r = json.loads(l); rows[r["id"]] = r
    for sid, r in rows.items():
        print(f"{tag:4} {sid:16} {r.get('status'):8} collisions={r.get('collisions')} "
              f"first@{r.get('first_collision_frame')} with={r.get('first_collision_with')}")
PY
