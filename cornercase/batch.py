"""Queue jobs to the live worker and summarise what each run did.

  python cornercase/batch.py curated_08 curated_10 --models 1,1.5 --vehicles mkz2017,charger

Runs every (scenario, model, car) combination through the resident worker, one
after another, and reduces each run to the handful of numbers that say what
happened: did it collide and when, how hard did it brake, how far did it wander.
Live runs vary, so run a combination several times (--repeat) before reading
much into one result. Jobs are written straight into the queue, so fields the
public API does not expose (control_trace, overlay) are available to callers.
"""
import argparse, json, os, sys, time, uuid
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

QUEUE = os.environ.get("LIVE_QUEUE") or paths.LIVE
JOBS, STATUS, OUT = f"{QUEUE}/jobs", f"{QUEUE}/status", f"{QUEUE}/out"


def submit(scenario, model, vehicle="mkz2017", mode="live", steps=100, seed=42,
           tag="", **extra):
    jid = f"{tag or 'b'}_{scenario}_{model.replace('.','')}_{vehicle}_{uuid.uuid4().hex[:5]}"
    job = {"id": jid, "scenario": scenario, "model": model, "seed": seed,
           "steps": steps, "vehicle": vehicle, "mode": mode}
    job.update(extra)
    os.makedirs(JOBS, exist_ok=True)
    with open(os.path.join(JOBS, jid + ".json"), "w") as f:
        json.dump(job, f)
    return jid


def wait(jid, timeout=1200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(8)
        f = os.path.join(STATUS, jid + ".json")
        if not os.path.exists(f):
            continue
        try: d = json.load(open(f))
        except Exception: continue
        if d.get("phase") == "done":
            return d
        if d.get("phase") == "error":
            return {"phase": "error", "error": d.get("error")}
    return {"phase": "timeout"}


def metrics(jid):
    """Everything needed to judge a run, from its own trace."""
    f = os.path.join(OUT, f"{jid}__trace.json")
    if not os.path.exists(f):
        return None
    d = json.load(open(f)); t = d["trace"]
    if not t: return None
    x = np.array([p["x"] for p in t]); y = np.array([p["y"] for p in t])
    sp = np.array([p["speed"] for p in t]); br = np.array([p["brake"] for p in t])
    st = np.array([p["steer"] for p in t])
    acc = np.diff(sp) / 0.1
    # lateral offset measured against the initial heading, so it works on any map
    yaw = np.deg2rad(t[0]["yaw"])
    dx, dy = x - x[0], y - y[0]
    lat = -np.sin(yaw) * dx + np.cos(yaw) * dy
    lon = np.cos(yaw) * dx + np.sin(yaw) * dy
    cols = d.get("collisions", [])
    return dict(
        job=jid, steps=len(t), cot=(d.get("cot") or "")[:60],
        mean_speed=round(float(sp.mean()), 2), peak_speed=round(float(sp.max()), 2),
        lateral=round(float(lat[np.argmax(np.abs(lat))]), 2),
        travel=round(float(np.abs(lon).max()), 1),
        max_decel=round(float(-acc.min()) if len(acc) else 0.0, 2),
        # Single-tick differences exaggerate: CARLA speed is noisy step to step,
        # and one 0.1s sample can read as 2g when nothing jerked. A 0.5s window
        # is what a passenger would actually feel, so that is what decides.
        decel_05=round(float(-((sp[5:] - sp[:-5]) / 0.5).min()) if len(sp) > 5 else 0.0, 2),
        hard_brake=int((br > 0.7).sum()),
        steer_jerk=round(float(np.abs(np.diff(st)).max()) if len(st) > 1 else 0.0, 3),
        stops=bool((sp[len(sp)//2:] < 0.1).any()),
        collisions=len({(c["with"], c["step"] // 5) for c in cols}),
        collided_with=sorted({c["with"].split(".")[-1] for c in cols})[:3],
        first_collision=min((c["step"] for c in cols), default=-1),
    )


def run(scenario, model, vehicle="mkz2017", mode="live", steps=100, tag="", **extra):
    jid = submit(scenario, model, vehicle, mode, steps, tag=tag, **extra)
    st = wait(jid)
    if st.get("phase") != "done":
        return {"job": jid, "failed": st.get("phase"), "error": st.get("error")}
    m = metrics(jid) or {"job": jid, "failed": "no trace"}
    m["wall_s"] = st.get("wall_s")
    return m


HDR = (f"{'scenario':20} {'md':4} {'veh':8} {'mean':>5} {'lat':>6} {'trav':>6} "
       f"{'dec.5s':>6} {'hb':>3} {'jerk':>5} {'col':>3} {'@':>4}  cot")


def line(scenario, model, vehicle, m):
    if m.get("failed"):
        return f"{scenario:20} {model:4} {vehicle:8}  FAILED: {m.get('failed')} {m.get('error','')}"
    return (f"{scenario:20} {model:4} {vehicle:8} {m['mean_speed']:5.2f} {m['lateral']:+6.2f} "
            f"{m['travel']:6.1f} {m['max_decel']:6.2f} {m['hard_brake']:3} "
            f"{m['steer_jerk']:5.3f} {m['collisions']:3} {m['first_collision']:4}  {m['cot'][:44]}"
            if False else
            f"{scenario:20} {model:4} {vehicle:8} {m['mean_speed']:5.2f} {m['lateral']:+6.2f} "
            f"{m['travel']:6.1f} {m.get('decel_05', 0):6.2f} {m['hard_brake']:3} "
            f"{m['steer_jerk']:5.3f} {m['collisions']:3} {m['first_collision']:4}  {m['cot'][:44]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--models", default="1.5")
    ap.add_argument("--vehicles", default="mkz2017")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--steps", type=int, default=100)
    a = ap.parse_args()
    print(HDR)
    for s in a.scenarios:
        for md in a.models.split(","):
            for veh in a.vehicles.split(","):
                for _ in range(a.repeat):
                    print(line(s, md, veh, run(s, md, veh, steps=a.steps, tag="b")), flush=True)


if __name__ == "__main__":
    main()
