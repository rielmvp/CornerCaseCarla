"""Where everything lives. Every script imports this instead of hardcoding paths.

Each setting is read from the environment, then from a .env file at the repo root
(copy config.example.env), then falls back to the default below. Relative paths are
taken from the repo root, so scripts work from any working directory.

Importing this module also puts Carlamayo and CARLA's PythonAPI on sys.path:
Carlamayo's `module.*` is imported by the driving code, and its PID controller
imports `agents.navigation`, which ships inside the CARLA server package rather
than the carla wheel.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path=os.path.join(ROOT, ".env")):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.split(" #", 1)[0].strip().strip("'\"")     # drop inline comments, as bash does
        os.environ.setdefault(k, v)


_load_dotenv()


def _path(name, default):
    p = os.path.expanduser(os.environ.get(name) or default)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


CARLA_ROOT = _path("CARLA_ROOT", "carla/CARLA_0.9.16")
# OpenDRIVE road networks shipped with the server; Scenic reads them directly
MAPS = _path("CARLA_MAPS", os.path.join(CARLA_ROOT, "CarlaUE4/Content/Carla/Maps/OpenDrive"))
CKPT_ROOT = _path("CKPT_ROOT", "checkpoints")
CARLAMAYO = os.path.join(ROOT, "third_party", "Carlamayo")
SCENARIOS = _path("SCENARIO_DIR", "scenarios/curated")
OUTPUTS = _path("OUTPUT_DIR", "outputs")
RUNS = os.path.join(OUTPUTS, "runs")        # batch runs: videos + results_*.jsonl
SITE = os.path.join(OUTPUTS, "site")        # generated web pages, served by live_server
LIVE = os.path.join(OUTPUTS, "live")        # live studio job queue: jobs/ status/ out/

for _p in (os.path.join(CARLA_ROOT, "PythonAPI", "carla"), CARLAMAYO):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def scenario_file(stem):
    return os.path.join(SCENARIOS, stem + ".scenic")


def map_file(town):
    return os.path.join(MAPS, town + ".xodr")
