"""Drive Scenic scenarios with NVIDIA Alpamayo in CARLA, and record what happened.

Scenic samples the scene and drives every adversary; only the ego is taken over
by Alpamayo. The .scenic files are never modified -- the ego's Scenic actions
are dropped in executeActions and replaced by PID control over the model's
predicted trajectory.

The control loop itself lives in alpamayo_core.DriverCore, shared verbatim with
random_spawn_runner.py so the Scenic and native settings stay comparable.
"""
from __future__ import annotations

import argparse, json, os, re, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (Carlamayo + CARLA PythonAPI on sys.path, repo locations)
import alpamayo_core as core_mod
from alpamayo_core import (VIEWS, DriverCore, get_adapter, seed_everything)

import carla
import scenic
from scenic.simulators.carla.simulator import CarlaSimulator, CarlaSimulation


class AlpamayoSimulation(CarlaSimulation):
    adapter = model = processor = None
    replan_every = 1
    init_speed = 0.0
    nav_text = ""
    speed_mode = "carlamayo"

    def setup(self):
        super().setup()
        ego = self.objects[0].carlaActor
        self.core = DriverCore(self.world, ego, self.adapter, self.model,
                              self.processor, replan_every=self.replan_every,
                              nav_text=self.nav_text,
                              speed_mode=self.speed_mode)
        self.core.attach_sensors()

        # Scenic forbids a nonzero initial speed on its objects, so every actor
        # starts from rest -- but these scenarios assume traffic already moving.
        # Nudge the CARLA actors directly; no .scenic edit.
        if self.init_speed > 0:
            for obj in self.objects:
                act = getattr(obj, "carlaActor", None)
                if act is None or not isinstance(act, carla.Vehicle):
                    continue
                try:
                    f = act.get_transform().get_forward_vector()
                    act.set_target_velocity(carla.Vector3D(
                        x=f.x * self.init_speed, y=f.y * self.init_speed, z=0.0))
                except Exception as e:
                    print(f"  init-speed skipped: {type(e).__name__}: {e}", flush=True)

        self.core.warmup(self.world.tick)

    # Scenic drives the adversaries; Alpamayo drives the ego.
    def executeActions(self, allActions):
        from collections import defaultdict
        ego_obj = self.objects[0]
        d = defaultdict(tuple)
        d.update({a: acts for a, acts in allActions.items() if a is not ego_obj})
        super().executeActions(d)

    def step(self):
        super().step()          # world.tick() FIRST, as Carlamayo does
        self.core.on_tick()

    def destroy(self):
        if getattr(self, "core", None):
            self.core.detach_sensors()
        super().destroy()


class AlpamayoSimulator(CarlaSimulator):
    def createSimulation(self, scene, *, timestep, **kw):
        self.scenario_number += 1
        for k in ("adapter", "model", "processor", "replan_every", "init_speed", "nav_text",
                  "speed_mode"):
            setattr(AlpamayoSimulation, k, getattr(self, "_" + k))
        return AlpamayoSimulation(scene, self.client, self.tm, self.render,
                                  self.record, self.scenario_number, timestep=timestep, **kw)


def description_of(path):
    """The scenario's own one-line description, used as navigation text."""
    m = re.search(r"""^description\s*=\s*(['\"])(.*?)\1""", open(path).read(), re.M | re.S)
    return " ".join(m.group(2).split()) if m else ""


def town_of(path):
    t = open(path).read()
    m = re.search(r"param\s+carla_map\s*=\s*['\"](Town\w+)['\"]", t)
    if m:
        return m.group(1)
    m = re.search(r"^\s*Town\s*=\s*['\"](Town\w+)['\"]", t, re.M)
    return m.group(1) if m else "Town05"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--version", default="1", choices=["1", "1.5"])
    ap.add_argument("--scenario-dir", default=paths.SCENARIOS)
    ap.add_argument("--maps", default=paths.MAPS)
    ap.add_argument("--ckpt-root", default=paths.CKPT_ROOT)
    ap.add_argument("--out", default=paths.RUNS)
    ap.add_argument("--port", type=int, default=3100)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--replan-every", type=int, default=1)
    ap.add_argument("--init-speed", type=float, default=0.0)
    ap.add_argument("--speed-mode", default="carlamayo", choices=["carlamayo", "plan", "planvel", "planlook", "tuned"],
                    help="carlamayo = upstream's clip(10+0.5*extent,10,35) heuristic; "
                         "plan = the speed its whole 6.4 s trajectory implies; "
                         "planvel = the velocity the plan carries over its first 1.5 s")
    ap.add_argument("--traj-samples", type=int, default=5,
                    help="NUM_TRAJ_SAMPLES. Upstream's config ships 1, but at 1 the "
                         "select_trajectory_by_prev_similarity call is inert and the "
                         "pipeline loses its only temporal filter, so 5 is the default "
                         "here. The extra samples are selected among, not drawn: see "
                         "DRAW_SELECTED_ONLY. 0 = leave config.py untouched")
    ap.add_argument("--suffix", default="",
                    help="append to the recorded id and video names, e.g. _planvel, so a "
                         "variant sits beside the original instead of overwriting it")
    ap.add_argument("--draw-all-samples", action="store_true",
                    help="paint the whole candidate spread (red selected + white rejected). "
                         "Off by default: the ensemble is always sampled, only one line is drawn")
    ap.add_argument("--lon-kp", type=float, default=0.0,
                    help="TunedPIDFollower longitudinal K_P (0 = upstream's 0.9, which "
                         "saturates at 1.11 km/h of error). K_I scales with it")
    ap.add_argument("--brake-deadband", type=float, default=0.0,
                    help="coast instead of braking within this many km/h over target")
    ap.add_argument("--steer-guard", action="store_true",
                    help="hold steering straight when the plan is too short to resolve "
                         "the lateral lookahead")
    ap.add_argument("--no-resume", action="store_true",
                    help="re-run scenarios already present in results_<tag>.jsonl")
    ap.add_argument("--nav", action="store_true",
                    help="feed the scenario description as navigation text (Alpamayo 1.5 only)")
    ap.add_argument("--deterministic", action="store_true",
                    help="pin cuDNN/cuBLAS/TF32 as well as the RNG. Seeding alone does not "
                         "reproduce a run: identical configs diverge on the first inference")
    a = ap.parse_args()

    if a.deterministic:
        core_mod.DETERMINISTIC = True
        print("DETERMINISTIC = True", flush=True)

    if a.draw_all_samples:
        core_mod.DRAW_SELECTED_ONLY = False
        print("DRAW_SELECTED_ONLY = False (full candidate spread)", flush=True)
    if a.lon_kp:
        core_mod.TunedPIDFollower.LON_KP = a.lon_kp
    if a.brake_deadband:
        core_mod.TunedPIDFollower.BRAKE_DEADBAND_KMH = a.brake_deadband
    if a.steer_guard:
        core_mod.TunedPIDFollower.STEER_GUARD = True
    if a.speed_mode == "tuned":
        print(f"tuned: LON_KP={core_mod.TunedPIDFollower.LON_KP} "
              f"deadband={core_mod.TunedPIDFollower.BRAKE_DEADBAND_KMH} "
              f"steer_guard={core_mod.TunedPIDFollower.STEER_GUARD}", flush=True)

    if a.traj_samples:
        import module.config as cfg
        cfg.NUM_TRAJ_SAMPLES = a.traj_samples
        print(f"NUM_TRAJ_SAMPLES = {a.traj_samples}", flush=True)

    ad = get_adapter(a.version, a.ckpt_root)
    print(f"loading {ad.display_name} ...", flush=True)
    t0 = time.time()
    model, proc = ad.load_model(device_map="auto")
    print(f"LOAD {time.time()-t0:.1f}s", flush=True)
    tag = "r1" if a.version == "1" else "v15"

    os.makedirs(a.out, exist_ok=True)
    res_path = os.path.join(a.out, f"results_{tag}.jsonl")

    def already_done():
        """Scenarios already recorded, so an interrupted batch can resume."""
        done = set()
        if os.path.exists(res_path):
            for line in open(res_path):
                if line.startswith("{"):
                    try:
                        r = json.loads(line)
                        if r.get("status") in ("ok", "partial", "rejected"):
                            done.add(r["id"])
                    except Exception:
                        pass
        return done

    def record(rec):
        with open(res_path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print("RESULT " + json.dumps(rec), flush=True)

    todo = [s.strip() for s in a.scenarios.split(",") if s.strip()]
    if not a.no_resume:
        # compare against the id actually recorded, which carries --suffix;
        # matching on the bare stem makes a variant look already-done
        done = already_done()
        skipped = [s for s in todo if s + a.suffix in done]
        todo = [s for s in todo if s + a.suffix not in done]
        if skipped:
            print(f"resuming: {len(skipped)} already done, {len(todo)} to go", flush=True)

    for stem in todo:
        f = os.path.join(a.scenario_dir, stem + ".scenic")
        town = town_of(f)
        xodr = os.path.join(a.maps, town + ".xodr")
        desc = description_of(f)
        nav = desc if a.nav else ""
        out_id = stem + a.suffix
        rec = {"id": out_id, "town": town, "description": desc,
               "model": ad.display_name, "version": a.version,
               "seed": a.seed, "replan_every": a.replan_every, "init_speed": a.init_speed,
               "traj_samples": a.traj_samples, "speed_mode": a.speed_mode,
               "status": "unknown"}
        t_run = time.time()
        try:
            seed_everything(a.seed)     # re-seed per scenario: order must not matter
            sc = scenic.scenarioFromFile(f, mode2D=True, params={
                "map": xodr, "carla_map": town, "port": a.port,
                "render": 0, "timestep": 0.1})
            scene, _ = sc.generate(maxIterations=4000)
            sim = AlpamayoSimulator(carla_map=town, map_path=xodr, port=a.port,
                                    render=False, timestep=0.1, timeout=120)
            sim._adapter, sim._model, sim._processor = ad, model, proc
            sim._replan_every, sim._init_speed = a.replan_every, a.init_speed
            sim._nav_text = nav
            sim._speed_mode = a.speed_mode
            # simulate() returns None when every iteration was rejected by a
            # requirement. Reading a leftover simulation object here is how
            # one scenario once came to be served another's video under its own
            # name, reported as "ok" -- so a rejection must end this scenario, loudly.
            # maxIterations=1: a rejection here means Alpamayo violated one of
            # the scenario's requirements, and retrying re-runs the whole
            # simulation for the same reason; one measured retry took 480 s to
            # reach the same rejection twice.
            sim_run = sim.simulate(scene, maxSteps=a.steps, maxIterations=1,
                                   raiseGuardViolations=False)
            if sim_run is None:
                rec["status"] = "rejected"
                rec["error"] = "Scenic rejected the simulation (requirement violated)"
                rec["wall_s"] = round(time.time() - t_run, 1)
                record(rec)
                continue
            core = sim_run.core
            if len(core.trace) < 2:
                raise RuntimeError(f"simulation produced only {len(core.trace)} steps")
            rec.update(core.summary())
            rec.update(core.write_videos(a.out, out_id, tag))
            with open(os.path.join(a.out, f"trace_{out_id}__{tag}.json"), "w") as fh:
                json.dump({"trace": core.trace, "coc": core.coc_log}, fh)
            rec["status"] = "ok" if rec.get("views_written") == 3 else "partial"
        except Exception as e:
            import traceback
            traceback.print_exc()
            rec["status"] = "error"
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
        rec["wall_s"] = round(time.time() - t_run, 1)
        record(rec)


if __name__ == "__main__":
    main()
