"""Integrity check: no two scenarios may share a video file.

Scenic's simulate() returns None when a scene is rejected. An earlier version of
the runner then fell back to a stale simulation object and wrote the previous
scenario's frames under the rejected scenario's name, reporting "ok". The bug is
fixed, but it was silent, so every batch gets checked for its signature: two
different scenario ids producing byte-identical video.
"""
import hashlib, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
d = sys.argv[1] if len(sys.argv) > 1 else paths.RUNS
by_hash = defaultdict(list)
for f in sorted(os.listdir(d)):
    if not f.endswith(".mp4"):
        continue
    h = hashlib.md5(open(os.path.join(d, f), "rb").read()).hexdigest()
    by_hash[h].append(f)

dupes = {h: v for h, v in by_hash.items() if len(v) > 1}
n = sum(len(v) for v in dupes.values())
print(f"{d}: {sum(len(v) for v in by_hash.values())} videos, {len(by_hash)} distinct")
if not dupes:
    print("OK - every scenario has its own footage")
    sys.exit(0)
print(f"\nFAIL - {n} files share content across {len(dupes)} groups:")
for h, v in dupes.items():
    print(f"  {h[:12]}  " + "  ".join(v))
sys.exit(1)
