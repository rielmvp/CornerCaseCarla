"""Non-invasive probe: log what the PID actually sees, in any Carlamayo-based run.

Importing this module wraps OfficialPIDFollower.compute_control so every call
appends one JSON line to $PID_PROBE_OUT. Nothing in Carlamayo or in the runner
is edited; the probe only observes.

Recorded per call:
    traj_extent      farthest point of Alpamayo's predicted path from the ego (m)
    target_speed_kmh what the PID was therefore told to aim for
    traj_reach_m     arclength of the whole predicted path (m)
    traj_end         final predicted waypoint in ego-local frame
This is the chain that decides whether the car crawls: a short predicted path
pins target_speed at the 10 km/h floor, the car stays slow, and the next
prediction is shorter still.
"""
import json, os, numpy as np

_OUT = os.environ.get("PID_PROBE_OUT", "")
_TAG = os.environ.get("PID_PROBE_TAG", "run")
_fh = None
_n = 0


def install(cls=None):
    """Wrap one follower class. Call again for any subclass that defines its own
    compute_control: overriding the method shadows this wrapper, which silently
    produced empty probe logs for every --speed-mode plan run."""
    global _fh
    if not _OUT:
        return
    if cls is None:
        from module.pid_controller import OfficialPIDFollower as cls
    if cls.__dict__.get("_probed"):
        return
    os.makedirs(os.path.dirname(_OUT) or ".", exist_ok=True)
    if _fh is None:
        _fh = open(_OUT, "a", buffering=1)
    orig = cls.compute_control
    # Exposed so a subclass can reach the real method without re-entering
    # this wrapper and logging the same control step twice.
    cls._probe_orig = staticmethod(orig)

    def wrapped(self, vehicle_tf, wp_ego, speed_mps):
        global _n
        st, th, br, dbg = orig(self, vehicle_tf, wp_ego, speed_mps)
        try:
            wp = np.asarray(wp_ego, dtype=np.float64)
            seg = np.linalg.norm(np.diff(wp[:, :2], axis=0), axis=1)
            _fh.write(json.dumps({
                "tag": _TAG, "i": _n,
                "speed_mps": round(float(speed_mps), 3),
                "traj_pts": int(wp.shape[0]),
                "traj_extent": round(float(dbg.get("traj_extent", 0.0)), 3),
                "traj_reach_m": round(float(seg.sum()), 3),
                "traj_end": [round(float(wp[-1, 0]), 2), round(float(wp[-1, 1]), 2)],
                "target_speed_kmh": round(float(dbg.get("target_speed_kmh", 0.0)), 2),
                "target_idx": int(dbg.get("target_idx", -1)),
                "lookahead_m": round(float(dbg.get("lookahead_m", 0.0)), 2),
                "steer_raw": round(float(st), 3),
                "throttle_raw": round(float(th), 3),
                "brake_raw": round(float(br), 3),
            }) + "\n")
            _n += 1
        except Exception:
            pass
        return st, th, br, dbg

    cls.compute_control = wrapped
    cls._probed = True
    print(f"[pid_probe] {cls.__name__} -> {_OUT}", flush=True)
