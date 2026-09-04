"""Per-scenario and total render cost for a batch.

wall_s is measured end to end per scenario: Scenic compiles and samples the
scene, CARLA loads the map and ticks it, Alpamayo runs once per tick, and three
videos are encoded. Model load is once per process, not per scenario.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
SRC = sys.argv[1] if len(sys.argv) > 1 else paths.RUNS
LOAD = {"r1": "Alpamayo 1 (R1)", "v15": "Alpamayo 1.5"}

rows = {}
for tag in ("r1", "v15"):
    f = os.path.join(SRC, f"results_{tag}.jsonl")
    if not os.path.exists(f):
        continue
    for line in open(f):
        if line.startswith("{"):
            r = json.loads(line)
            rows.setdefault(tag, {})[r["id"]] = r     # last row per id wins

order = sorted({sid for t in rows.values() for sid in t})
print(f"{'scenario':>16}{'model':>8}{'status':>9}{'wall':>9}{'infer':>8}{'calls':>7}"
      f"{'frames':>8}{'mean km/h':>11}{'%stop':>7}")
print("-" * 83)
tot = {}
for sid in order:
    for tag in ("r1", "v15"):
        r = rows.get(tag, {}).get(sid)
        if not r:
            continue
        w = r.get("wall_s", 0)
        tot[tag] = tot.get(tag, 0) + w
        print(f"{sid:>16}{tag:>8}{r['status']:>9}{w:>8.0f}s{r.get('inference_mean_s',0):>7.2f}s"
              f"{r.get('inference_calls',0):>7}{r.get('frames',0):>8}"
              f"{r.get('speed_mean',0)*3.6:>11.1f}{r.get('frac_stopped',0):>7.2f}")

print("-" * 83)
for tag, t in tot.items():
    n = len([1 for sid in order if sid in rows.get(tag, {})])
    print(f"{'TOTAL '+tag:>16}{'':>8}{n:>9}{t:>8.0f}s   ({t/60:.1f} min, mean {t/max(n,1):.0f}s/scenario)")
if len(tot) > 1:
    grand = sum(tot.values())
    print(f"{'BOTH MODELS':>16}{'':>17}{grand:>8.0f}s   ({grand/60:.1f} min of GPU time; "
          f"{max(tot.values())/60:.1f} min wall, run in parallel)")
print("\n  + one-time model load per process: ~60-90 s each (not in the per-scenario numbers)")
