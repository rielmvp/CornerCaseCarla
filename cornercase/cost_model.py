"""What it costs to run Alpamayo over the corpus, from measured runs only.

Usage: cost_model.py [results_dir ...]

Everything here is extrapolated from wall-clock and inference timings actually
recorded in results_*.jsonl. Nothing is a vendor figure. The GPUs are shared with
other users, so "GPU-hours" means occupancy of one 22 GB model slot, not a
reserved card.
"""
import json, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
DIRS = sys.argv[1:] or [paths.RUNS]
N_CORPUS = 135          # scenarios that compile and simulate
LOAD_S = {"r1": 63, "v15": 66}

rows = defaultdict(list)
for d in DIRS:
    for tag in ("r1", "v15"):
        f = os.path.join(d, f"results_{tag}.jsonl")
        if not os.path.exists(f):
            continue
        for line in open(f):
            if line.startswith("{"):
                r = json.loads(line)
                if r.get("status") in ("ok", "partial") and r.get("inference_calls"):
                    rows[tag].append(r)

if not any(rows.values()):
    print("no completed runs found in: " + ", ".join(DIRS))
    sys.exit(0)

print(f"{'model':<8}{'runs':>6}{'steps':>7}{'inf/run':>9}{'s/inf':>8}"
      f"{'wall/run':>10}{'inf share':>11}")
print("-" * 59)
per = {}
for tag, rs in rows.items():
    if not rs:
        continue
    n = len(rs)
    steps = sum(r.get("frames", 0) for r in rs) / n
    calls = sum(r["inference_calls"] for r in rs) / n
    sinf = sum(r["inference_mean_s"] for r in rs) / n
    wall = sum(r["wall_s"] for r in rs) / n
    per[tag] = (wall, sinf, calls)
    print(f"{tag:<8}{n:>6}{steps:>7.0f}{calls:>9.0f}{sinf:>8.2f}"
          f"{wall:>10.1f}s{100*sinf*calls/wall:>10.0f}%")

print(f"\nfull corpus, {N_CORPUS} scenarios")
print(f"{'':<8}{'GPU-hours':>12}{'wall @1':>10}{'wall @2':>10}{'wall @4':>10}")
print("-" * 50)
grand = 0.0
for tag, (wall, sinf, calls) in per.items():
    h = (LOAD_S.get(tag, 65) + N_CORPUS * wall) / 3600
    grand += h
    print(f"{tag:<8}{h:>12.1f}{h:>9.1f}h{h/2:>9.1f}h{h/4:>9.1f}h")
if len(per) > 1:
    print(f"{'both':<8}{grand:>12.1f}{grand:>9.1f}h{grand/2:>9.1f}h{grand/4:>9.1f}h")
print("  workers = parallel (CARLA server + resident model) pairs; each needs")
print("  22.2 GB of VRAM, and the cards here are shared with other users.")

infh = sum(N_CORPUS * c * s for _, (w, s, c) in per.items()) / 3600
print(f"\n  of which pure model inference: {infh:.1f} GPU-h "
      f"({100*infh/grand:.0f}% of the total)")
print(f"  the rest is CARLA rendering the 4x1920x1080 rig, Scenic compiling the")
print(f"  scenario, and encoding three videos.")

print("\nlive vs pre-recorded, per scenario")
if per:
    tag = "r1" if "r1" in per else next(iter(per))
    wall, sinf, calls = per[tag]
    steps = sum(r.get("frames", 0) for r in rows[tag]) / len(rows[tag])
    print(f"  live, model in the loop : {wall:6.1f} s of wall clock for "
          f"{steps*0.1:.0f} s of simulated driving  ({wall/(steps*0.1):.0f}x slower than real time)")
    print(f"  replaying the recording :   {steps*0.1:6.1f} s, no GPU, no CARLA")
    print(f"  keeping one model resident costs 22.2 GB of VRAM whether or not")
    print(f"  anyone is watching; a recording costs only disk.")
