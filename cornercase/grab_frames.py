"""Pull a few frames out of a run's videos so they can be eyeballed.

  python cornercase/grab_frames.py <jobid-or-label> [view] [out_dir]
"""
import json, os, subprocess, sys
import imageio_ffmpeg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
LIVE = os.environ.get("LIVE_QUEUE") or paths.LIVE
OUT = os.path.join(LIVE, "out")
jobs = {}
LABELS = os.path.join(LIVE, "labels.txt")     # optional "<label> <jobid>" lines
if os.path.exists(LABELS):
    for line in open(LABELS):
        p = line.split()
        if len(p) == 2:
            jobs[p[0]] = p[1]

label = sys.argv[1]
view = sys.argv[2] if len(sys.argv) > 2 else "fpv"
dest = sys.argv[3] if len(sys.argv) > 3 else os.path.join(paths.OUTPUTS, "frame_checks")
jid = jobs.get(label, label)
src = os.path.join(OUT, f"{jid}__{view}.mp4")
if not os.path.exists(src):
    sys.exit(f"no video at {src}")
os.makedirs(dest, exist_ok=True)
ff = imageio_ffmpeg.get_ffmpeg_exe()
# a frame from early, middle and late in the run
for tag, t in (("early", "1.5"), ("mid", "5.0"), ("late", "8.5")):
    dst = os.path.join(dest, f"{label}__{view}__{tag}.png")
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", t, "-i", src,
                    "-frames:v", "1", "-vf", "scale=760:-1", dst], check=False)
    print(dst if os.path.exists(dst) else f"  failed {tag}")
