"""Composite the three camera views of one or more runs into a single reel.

The showcase page plays one video, not three. Three separate <video> elements
drift apart as soon as one of them stalls, and the old pre-rendered clips were
not even the same length: the previous pipeline only started the first-person
encoder once a prediction existed, so first-person was 97 frames against 100
for the other two - 9.7s vs 10.0s. Compositing into one file makes that class
of bug impossible; the views cannot desynchronise if they are the same frame.

Panels are laid out in a row with first-person in the middle. Labels are drawn
by the page in CSS rather than burned in, so they stay crisp and translatable.

Usage:
  python cornercase/build_reel.py --from-runs              segments from the batch runs
  python cornercase/build_reel.py --from-job <job_id> --as curated_08 r1
                                                           one segment from a worker job
  python cornercase/build_reel.py          # rebuild the reel from what is staged
"""
import argparse, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

REEL = os.path.join(paths.SITE, "reel")
LIVE_OUT = os.path.join(os.environ.get("LIVE_QUEUE") or paths.LIVE, "out")
VIEWS = ["bev", "fpv", "tpv"]          # laid out in this order, fpv in the middle
PANEL_W, PANEL_H, FPS = 960, 540, 10

# Fraction of each source frame's width kept (centred crop). The reel is one
# row, so its height on screen is (viewport width / total aspect) - the only way
# to make it taller without shrinking it is to take width off. The bird's-eye
# and third-person views carry scenery at the edges that costs nothing to lose;
# first-person is left whole because its overlay text spans the full frame.
CROP = {"bev": 0.42, "fpv": 1.00, "tpv": 0.52}

# "row"  - all three side by side, first-person in the middle.
# "hero" - first-person large on the left, the two context views stacked on the
#          right. Twice as tall as the row for the same width, and it needs no
#          cropping at all, but it is no longer a straight line of three.
LAYOUT = "row"

# Segments played back to back. Add a (scenario, model) pair here once its
# clips are staged in outputs/site/reel and the reel grows a new section.
SEGMENTS = [("curated_08", "r1"),     # cornercase_1: pedestrian steps out at night
            ("curated_09", "r1"),     # cornercase_4: collision with the construction barriers
            ("curated_01", "v15")]    # cornercase_2: 1.5 drives into the wrong-way car


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def frames(exe, path):
    """Exact frame count, so a length mismatch between views is caught rather than
    silently cropped by hstack. This build of ffmpeg prints no progress line when
    stdout is not a tty, so decode to a tiny grey rawvideo stream and count bytes."""
    n = subprocess.run([exe, "-v", "quiet", "-i", path, "-map", "0:v:0",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-s", "16x16", "-"],
                       capture_output=True).stdout
    return len(n) // (16 * 16)


def stage(job_id, sid, tag):
    """Copy one finished run's three views in as the canonical clips for a segment."""
    os.makedirs(REEL, exist_ok=True)
    for v in VIEWS:
        src = os.path.join(LIVE_OUT, f"{job_id}__{v}.mp4")
        if not os.path.exists(src):
            sys.exit(f"missing {src}")
        shutil.copy2(src, os.path.join(REEL, f"{sid}__{tag}__{v}.mp4"))
    print(f"staged {sid}/{tag} from {job_id}")


def stage_runs(sid, tag):
    """Use a batch run's own clips (outputs/runs) for a segment, overlay and all."""
    os.makedirs(REEL, exist_ok=True)
    for v in VIEWS:
        src = os.path.join(paths.RUNS, f"{sid}__{tag}__{v}.mp4")
        if not os.path.exists(src):
            sys.exit(f"missing {src} - run scripts/run_corner_cases.sh first")
        shutil.copy2(src, os.path.join(REEL, f"{sid}__{tag}__{v}.mp4"))
    print(f"staged {sid}/{tag} from {paths.RUNS}")


def build(exe):
    segs = []
    for sid, tag in SEGMENTS:
        paths = [os.path.join(REEL, f"{sid}__{tag}__{v}.mp4") for v in VIEWS]
        for p in paths:
            if not os.path.exists(p):
                sys.exit(f"missing staged clip {p}")
        n = [frames(exe, p) for p in paths]
        if len(set(n)) != 1:
            print(f"  WARNING {sid}/{tag}: view lengths differ {dict(zip(VIEWS, n))};"
                  f" hstack will stop at the shortest")
        print(f"  {sid}/{tag}: {n[0]} frames per view")
        segs.append(paths)

    if LAYOUT == "hero":
        # bev and tpv are half height each, stacked beside a full-height fpv
        widths = [PANEL_W // 2, PANEL_W, PANEL_W // 2]
        heights = [PANEL_H // 2, PANEL_H, PANEL_H // 2]
    else:
        widths = [max(2, int(PANEL_W * CROP.get(v, 1.0)) // 2 * 2) for v in VIEWS]
        heights = [PANEL_H] * len(VIEWS)
    inputs, filt, labels = [], [], []
    for si, paths in enumerate(segs):
        for pi, p in enumerate(paths):
            inputs += ["-i", p]
            idx = si * len(VIEWS) + pi
            f = 1.0 if LAYOUT == "hero" else CROP.get(VIEWS[pi], 1.0)
            crop = f"crop=iw*{f}:ih:(iw-iw*{f})/2:0," if f < 1.0 else ""
            filt.append(f"[{idx}:v]{crop}scale={widths[pi]}:{heights[pi]},"
                        f"setsar=1,fps={FPS}[s{si}p{pi}]")
        if LAYOUT == "hero":
            b_, f_, t_ = (f"[s{si}p{i}]" for i in range(3))
            filt.append(f"{b_}{t_}vstack=inputs=2[s{si}side]")
            filt.append(f"{f_}[s{si}side]hstack=inputs=2[seg{si}]")
        else:
            filt.append("".join(f"[s{si}p{pi}]" for pi in range(len(paths)))
                        + f"hstack=inputs={len(paths)}[seg{si}]")
        labels.append(f"[seg{si}]")
    if len(segs) > 1:
        filt.append("".join(labels) + f"concat=n={len(segs)}:v=1:a=0[v]")
    else:
        filt.append(f"{labels[0]}null[v]")

    out = os.path.join(REEL, "reel.mp4" if LAYOUT == "row" else f"reel_{LAYOUT}.mp4")
    cmd = ([exe, "-y", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(filt), "-map", "[v]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    subprocess.run(cmd, check=True)
    total = PANEL_W + PANEL_W // 2 if LAYOUT == "hero" else sum(widths)
    print(f"wrote {out}  ({os.path.getsize(out)/1e6:.2f} MB, {total}x{PANEL_H}, "
          f"aspect {total/PANEL_H:.2f}:1, layout {LAYOUT}, "
          f"panels {dict(zip(VIEWS, widths))})")
    # The page draws the panel labels, so it needs the column proportions to
    # keep each label over its own panel now that they are unequal.
    json.dump({"segments": [{"scenario": s, "model": t} for s, t in SEGMENTS],
               "views": VIEWS, "widths": widths, "height": PANEL_H,
               "layout": LAYOUT, "aspect": round(total / PANEL_H, 4), "fps": FPS},
              open(os.path.join(REEL, f"reel{'' if LAYOUT=='row' else '_'+LAYOUT}.json"),
                   "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-job")
    ap.add_argument("--as", dest="as_", nargs=2, metavar=("SCENARIO", "MODEL"))
    ap.add_argument("--from-runs", action="store_true",
                    help="stage every segment from outputs/runs (clips keep their overlay)")
    a = ap.parse_args()
    exe = ffmpeg()
    if a.from_runs:
        for sid, tag in SEGMENTS:
            stage_runs(sid, tag)
    if a.from_job:
        if not a.as_: sys.exit("--from-job needs --as SCENARIO MODEL")
        stage(a.from_job, *a.as_)
    build(exe)
