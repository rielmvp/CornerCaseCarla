"""Classify what each run actually DID, to see if the manoeuvre is stable.

Small differences in the driven line are acceptable; a different manoeuvre is
not. This reduces a run to three facts that decide the manoeuvre class:

  lateral   max sideways deviation from the initial heading (m). This is NOT
            by itself a lane-change test: the road curves, so a run that stays
            perfectly in lane still accumulates several metres. What matters is
            whether runs AGREE with each other, so the spread across runs is
            the headline number.
  min_speed lowest speed reached (m/s)   -> did it actually come to a stop
  stopped   fraction of steps under 0.5 m/s

  python cornercase/manoeuvre_check.py <jobid-or-label> [...]
"""
import json, math, os, sys

jobs = {}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
LIVE = os.environ.get("LIVE_QUEUE") or paths.LIVE
LABELS = os.path.join(LIVE, "labels.txt")     # optional "<label> <jobid>" lines
if os.path.exists(LABELS):
    for line in open(LABELS):
        p = line.split()
        if len(p) == 2:
            jobs[p[0]] = p[1]


def classify(label):
    jid = jobs.get(label, label)
    f = os.path.join(LIVE, "out", f"{jid}__trace.json")
    if not os.path.exists(f):
        return None
    d = json.load(open(f))
    t = d["trace"]
    if len(t) < 5:
        return None
    # heading at the start, from the first few metres of travel
    x0, y0 = t[0]["x"], t[0]["y"]
    hx, hy = t[4]["x"] - x0, t[4]["y"] - y0
    n = math.hypot(hx, hy) or 1.0
    hx, hy = hx / n, hy / n
    lateral = max(abs(-(p["x"] - x0) * hy + (p["y"] - y0) * hx) for p in t)
    sp = [p["speed"] for p in t]
    return dict(label=label, steps=len(t), lateral=lateral, min_speed=min(sp),
                mean=sum(sp) / len(sp), maxs=max(sp),
                stopped=sum(1 for s in sp if s < 0.5) / len(sp),
                cot=(d.get("cot") or "")[:44])


rows = [r for r in (classify(l) for l in sys.argv[1:]) if r]
print(f"{'run':<20} {'steps':>5} {'lateral m':>10} {'min m/s':>8} {'mean':>6} "
      f"{'max':>6} {'stopped':>8}  manoeuvre        cot")
for r in rows:
    stop = "full stop" if r["min_speed"] < 0.2 else "slows only"
    print(f"{r['label']:<20} {r['steps']:>5} {r['lateral']:>10.2f} {r['min_speed']:>8.2f} "
          f"{r['mean']:>6.2f} {r['maxs']:>6.2f} {r['stopped']:>7.0%}  "
          f"{stop:<11} {r['cot']}")
if len(rows) > 1:
    lat = [r["lateral"] for r in rows]
    spread = max(lat) - min(lat)
    stops = {("full stop" if r["min_speed"] < 0.2 else "slows only") for r in rows}
    print(f"\nAGREEMENT ACROSS {len(rows)} RUNS")
    print(f"  lateral path spread : {spread:.2f} m   "
          f"(lane width ~3.5 m - a lane change between runs would exceed that)")
    print(f"  outcome             : {stops if len(stops) > 1 else stops.pop()}"
          + ("   <-- INCONSISTENT" if len(stops) > 1 else "   (consistent)"))
    print(f"  mean speed range    : {min(r['mean'] for r in rows):.2f} - "
          f"{max(r['mean'] for r in rows):.2f} m/s")
