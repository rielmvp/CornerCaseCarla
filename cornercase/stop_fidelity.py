"""Does the controller do what the model asked?

Alpamayo emits 64 waypoints at dt=0.1 s, so each prediction is a 6.4 s plan and
the speed it intends is arclength / 6.4. This script asks how faithfully the PID
reproduces that, and in particular whether the ego is allowed to stop when the
model plans to stop -- which upstream's clip(10 + 0.5*extent, 10, 35) forbids.
"""
import json, sys, numpy as np

HORIZON_S = 6.4
STOP_KMH = 5.0          # a plan slower than this is the model asking to halt


def load(p):
    return [json.loads(l) for l in open(p) if l.startswith("{")]


def report(name, rows):
    reach = np.array([r["traj_reach_m"] for r in rows])
    tgt = np.array([r["target_speed_kmh"] for r in rows])
    act = np.array([r["speed_mps"] for r in rows]) * 3.6
    brake = np.array([r["brake_raw"] for r in rows])
    plan = 3.6 * reach / HORIZON_S

    stop = plan < STOP_KMH
    err = np.abs(tgt - plan)
    obeyed = (tgt[stop] < STOP_KMH).mean() * 100 if stop.any() else float("nan")
    print(f"{name:<18}{len(rows):>7}{np.median(err):>15.1f}{tgt.min():>12.1f}"
          f"{stop.sum():>12}{obeyed:>12.0f}{np.median(act[stop]) if stop.any() else float('nan'):>12.1f}"
          f"{100*(brake > 0.05).mean():>9.0f}")


if __name__ == "__main__":
    print("how faithfully the PID follows the model's own plan\n")
    print(f"{'run':<18}{'frames':>7}{'|target-plan|':>15}{'min target':>12}"
          f"{'stop plans':>12}{'% honoured':>12}{'km/h then':>12}{'% brake':>9}")
    print("-" * 97)
    for p in sys.argv[1:]:
        rows = load(p)
        if rows:
            report(p.split("/")[-1].replace(".jsonl", ""), rows)
    print("\n|target-plan| : median km/h gap between what the model planned and what the PID was told")
    print("stop plans    : frames where the model's 6.4 s plan implies < 5 km/h")
    print("% honoured    : of those, the share where the PID was also told < 5 km/h")
    print("km/h then     : the ego's actual median speed during those stop plans")
