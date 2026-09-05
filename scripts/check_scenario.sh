#!/usr/bin/env bash
# Check that a scenario builds the scene it describes, before any model drives it.
#   scripts/check_scenario.sh <scenario id>          e.g. curated_10
# 1. geometric pre-filter over a few seeds (no simulator): is the hazard there,
#    ahead of the ego, and close enough to matter?
# 2. CARLA preview with the scenario's own scripted behaviours (no Alpamayo):
#    a contact sheet of bird's-eye + chase frames, plus a per-tick trace of
#    where every other actor is relative to the ego.
set -euo pipefail
cd "$(dirname "$0")/.."
ID=$1
F=scenarios/curated/$ID.scenic
mkdir -p outputs/previews
.venv/bin/python cornercase/scenario_validate.py "$F" --seeds 42,7,123 --port "${CARLA_PORT:-2000}" || true
.venv/bin/python cornercase/scenario_preview.py "$F" --out "outputs/previews/$ID.jpg" \
  --port "${CARLA_PORT:-2000}"
