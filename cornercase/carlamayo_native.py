"""Run Carlamayo's OWN closed loop, unmodified, as the reference baseline.

This is the control experiment for "is my Scenic harness faithful?". It runs
upstream carlamayo.py --loop closed in its native Town03 random-spawn setting
with 50 NPC vehicles and 50 walkers, with only two things changed from outside:
  * the adapter's model_id points at the local checkpoint instead of the Hub
  * pid_probe observes compute_control
Both are monkeypatches applied before main() runs; no upstream file is edited.

If my harness's traj_extent / target_speed distribution matches this run's,
the harness is faithful and the driving I see is Alpamayo + Carlamayo's PID,
not a bug of mine.
"""
import os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (Carlamayo + CARLA PythonAPI on sys.path, repo locations)

CKPT = paths.CKPT_ROOT
LOCAL = {"1": "Alpamayo-R1-10B", "1.5": "Alpamayo-1.5-10B"}


def patch_model_ids():
    from module.adapters import alpamayo_r1, alpamayo_1_5
    alpamayo_r1.AlpamayoR1Adapter.model_id = os.path.join(CKPT, LOCAL["1"])
    alpamayo_1_5.Alpamayo15Adapter.model_id = os.path.join(CKPT, LOCAL["1.5"])


def arm_deadline(seconds):
    """Their loop is `while True`; stop it from outside after N seconds."""
    def bomb():
        time.sleep(seconds)
        print(f"[native] deadline {seconds}s reached, stopping", flush=True)
        os._exit(0)
    threading.Thread(target=bomb, daemon=True).start()


if __name__ == "__main__":
    dl = float(os.environ.get("NATIVE_DEADLINE_S", "900"))
    patch_model_ids()
    import pid_probe; pid_probe.install()
    arm_deadline(dl)
    from carlamayo import main
    main(preset_loop="closed")
