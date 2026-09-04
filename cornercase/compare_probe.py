"""Compare what the PID saw in my Scenic harness vs Carlamayo's native run.

The question this answers is not "does the car drive well" but "is my harness
faithful". If the distribution of Alpamayo's predicted trajectory length, and
therefore of the speed the PID is told to aim for, matches upstream's own run,
then the driving I observe is Alpamayo under Carlamayo's PID config -- not an
artefact of putting Scenic in front of it.
"""
import json, sys, numpy as np


def load(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def stats(rows, key):
    v = np.array([r[key] for r in rows if key in r], dtype=float)
    if not len(v):
        return None
    return dict(n=len(v), mean=v.mean(), med=np.median(v), p10=np.percentile(v, 10),
                p90=np.percentile(v, 90), std=v.std(), mn=v.min(), mx=v.max())


def main(paths):
    sets = [(p.split("/")[-1].replace(".jsonl", ""), load(p)) for p in paths]
    sets = [(n, r) for n, r in sets if r]
    if not sets:
        print("no probe data yet")
        return

    keys = ["traj_extent", "traj_reach_m", "target_speed_kmh", "speed_mps"]
    for k in keys:
        print(f"\n=== {k} ===")
        print(f"{'run':<14}{'n':>6}{'mean':>9}{'median':>9}{'p10':>9}{'p90':>9}{'std':>9}{'max':>9}")
        for name, rows in sets:
            s = stats(rows, k)
            if s:
                print(f"{name:<14}{s['n']:>6}{s['mean']:>9.2f}{s['med']:>9.2f}"
                      f"{s['p10']:>9.2f}{s['p90']:>9.2f}{s['std']:>9.2f}{s['mx']:>9.2f}")

    print("\n=== instability / degeneracy ===")
    print(f"{'run':<14}{'|d extent| med':>16}{'reversing %':>13}{'extent<1m %':>13}{'target@floor %':>16}")
    for name, rows in sets:
        ext = np.array([r["traj_extent"] for r in rows], float)
        endx = np.array([r["traj_end"][0] for r in rows], float)
        tgt = np.array([r["target_speed_kmh"] for r in rows], float)
        d = np.abs(np.diff(ext))
        print(f"{name:<14}{np.median(d):>16.2f}{100*(endx < 0).mean():>13.1f}"
              f"{100*(ext < 1.0).mean():>13.1f}{100*(tgt <= 10.5).mean():>16.1f}")


if __name__ == "__main__":
    main(sys.argv[1:])
