"""Re-render chosen gallery samples with no overlay, reproducing the same drive.

Batch-run clips have the prediction overlay burned into the first-person view
- header bar, chain-of-thought box and the planned trajectory drawn on the road.
None of that can be cropped off, so a clean view has to be rendered again.

Re-running the model would give a different drive: the renderer is not
reproducible and the model branches on what it sees. But every batch run
recorded the control it actually applied, step by step, in
outputs/runs/trace_<id>__<model>.json. Replaying those commands
reproduces the drive without consulting the model at all, and with the overlay
switched off all three views come out clean.

Needs the worker running (scripts/demo.sh). Jobs are written straight into the
queue so the extra fields do not have to be exposed on the public API.

  python cornercase/render_clean.py                       the three reel segments
  python cornercase/render_clean.py curated_10:v15 ...    any batch run, scenario:tag
"""
import json, os, sys, time, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

LIVE = os.environ.get("LIVE_QUEUE") or paths.LIVE
JOBS, STATUS = os.path.join(LIVE, "jobs"), os.path.join(LIVE, "status")

# (scenario id, model tag, model version, label) - the showcase reel's segments
SAMPLES = [
    ("curated_08", "r1",  "1",   "cornercase_1"),
    ("curated_09", "r1",  "1",   "cornercase_4"),
    ("curated_01", "v15", "1.5", "cornercase_2"),
]
TRACE = os.path.join(paths.RUNS, "trace_{stem}__{tag}.json")


def trace_for(stem, tag):
    p = TRACE.format(stem=stem, tag=tag)
    if os.path.exists(p):
        return p
    sys.exit(f"no control trace for {stem}/{tag}")


def submit(stem, tag, ver):
    tr = trace_for(stem, tag)
    n = len(json.load(open(tr))["trace"])
    jid = f"clean_{stem}_{tag}_{uuid.uuid4().hex[:6]}"
    job = {"id": jid, "scenario": stem, "model": ver, "seed": 42,
           "steps": n, "mode": "live", "control_trace": tr, "overlay": False}
    os.makedirs(JOBS, exist_ok=True)
    with open(os.path.join(JOBS, jid + ".json"), "w") as f:
        json.dump(job, f)
    print(f"  submitted {jid}  ({n} steps, control from {os.path.basename(tr)})")
    return jid


def wait(jid, timeout=900):
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
            print(f"  ERROR {jid}: {d.get('error')}")
            return None
    print(f"  TIMEOUT {jid}")
    return None


if __name__ == "__main__":
    done = []
    picks = [(s.split(":")[0], s.split(":")[1], "1" if s.split(":")[1] == "r1" else "1.5", s)
             for s in sys.argv[1:]] or SAMPLES
    for stem, tag, ver, label in picks:
        print(f"{label}  ({stem} / {tag})")
        jid = submit(stem, tag, ver)
        d = wait(jid)
        if d:
            print(f"  done in {d.get('wall_s')}s -> {jid}")
            done.append((stem, tag, jid))
    print("\nrendered:")
    for stem, tag, jid in done:
        print(f"  {stem:18} {tag:4} {jid}")
    if done:
        print("\nstage them for the reel with: python cornercase/build_reel.py "
              + " ".join(f"--from-job {j} --as {s} {t}" for s, t, j in done[:1]) + " ...")
