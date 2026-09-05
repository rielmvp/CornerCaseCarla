"""Cheap geometric pre-filter for corner-case scenarios.

Rendering every candidate costs a CARLA simulation; most bad scenarios are
already detectable from the sampled scene alone (hazard missing, hazard behind
the ego, hazard 200 m away, no head-on when one was required). This samples the
scene over several seeds and reports the conflict geometry, so only plausible
scenarios get rendered and eyeballed.

Reports per seed: object count, ego->hazard gap, heading difference, and whether
the hazard lies ahead of the ego along its heading.
"""
import argparse, math, os, random, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
MAPS = paths.MAPS


def town_of(path):
    t = open(path).read()
    m = re.search(r"param\s+carla_map\s*=\s*['\"](Town\w+)['\"]", t)
    return m.group(1) if m else "Town05"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenic_file")
    ap.add_argument("--seeds", default="1,7,42,123")
    ap.add_argument("--port", type=int, default=3500)
    a = ap.parse_args()

    import scenic
    town = town_of(a.scenic_file)
    xodr = os.path.join(MAPS, town + ".xodr")
    rows = []
    import numpy as np
    for seed in [int(s) for s in a.seeds.split(",")]:
        # MUST mirror alpamayo_runner.seed_everything() + its maxIterations, or we
        # validate a different scene than the one that actually runs. Seeding only
        # `random` with maxIterations=3000 once reported a 15.3 m gap while the
        # runner's own sample had the cars overlapping at frame 0.
        random.seed(seed)
        np.random.seed(seed)
        try:
            sc = scenic.scenarioFromFile(a.scenic_file, mode2D=True, params={
                "map": xodr, "carla_map": town, "port": a.port, "render": 0, "timestep": 0.1})
            scene, _ = sc.generate(maxIterations=4000)
        except BaseException as e:
            print(f"seed {seed:4d}: SAMPLE FAIL {type(e).__name__}: {str(e)[:90]}")
            rows.append(None)
            continue
        objs = scene.objects
        ego = objs[0]
        if len(objs) < 2:
            print(f"seed {seed:4d}: only {len(objs)} object(s) - NO HAZARD")
            rows.append(None)
            continue
        # nearest non-ego object is the hazard of interest
        best = None
        for o in objs[1:]:
            d = math.dist((ego.position[0], ego.position[1]), (o.position[0], o.position[1]))
            if best is None or d < best[0]:
                best = (d, o)
        gap, haz = best
        rel = abs((math.degrees(ego.heading - haz.heading) + 180) % 360 - 180)
        # is the hazard ahead of the ego along its heading?
        vx, vy = haz.position[0] - ego.position[0], haz.position[1] - ego.position[1]
        fx, fy = math.cos(ego.heading + math.pi / 2), math.sin(ego.heading + math.pi / 2)
        ahead = (vx * fx + vy * fy) > 0
        kind = "HEAD-ON" if rel > 140 else ("crossing" if 40 < rel <= 140 else "same-dir")
        print(f"seed {seed:4d}: objs={len(objs)} gap={gap:6.1f}m headingdiff={rel:6.1f} "
              f"{kind:9s} {'AHEAD' if ahead else 'BEHIND'}  hazard={type(haz).__name__}")
        rows.append({"gap": gap, "rel": rel, "ahead": ahead, "kind": kind, "n": len(objs)})

    good = [r for r in rows if r and r["ahead"] and 8 <= r["gap"] <= 60]
    print(f"\nVERDICT: {len(good)}/{len(rows)} seeds place a hazard ahead of the ego within 8-60 m")
    sys.exit(0 if len(good) >= max(1, len(rows) // 2) else 1)


if __name__ == "__main__":
    main()
