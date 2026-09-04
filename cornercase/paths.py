"""Where everything lives, relative to the repo root.

Importing this module also puts Carlamayo and CARLA's PythonAPI on sys.path:
Carlamayo's `module.*` is imported by the driving code, and its PID controller
imports `agents.navigation`, which ships inside the CARLA server package rather
than the carla wheel.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CARLA_ROOT = os.path.join(ROOT, "carla", "CARLA_0.9.16")
# OpenDRIVE road networks shipped with the server; Scenic reads them directly
MAPS = os.path.join(CARLA_ROOT, "CarlaUE4/Content/Carla/Maps/OpenDrive")
CKPT_ROOT = os.path.join(ROOT, "checkpoints")
CARLAMAYO = os.path.join(ROOT, "third_party", "Carlamayo")
SCENARIOS = os.path.join(ROOT, "scenarios", "curated")
OUTPUTS = os.path.join(ROOT, "outputs")
RUNS = os.path.join(OUTPUTS, "runs")        # batch runs: videos + results_*.jsonl
SITE = os.path.join(OUTPUTS, "site")        # generated web pages, served by live_server
LIVE = os.path.join(OUTPUTS, "live")        # live job queue: jobs/ status/ out/

for _p in (os.path.join(CARLA_ROOT, "PythonAPI", "carla"), CARLAMAYO):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def scenario_file(stem):
    return os.path.join(SCENARIOS, stem + ".scenic")


def map_file(town):
    return os.path.join(MAPS, town + ".xodr")
