"""Control condition: Carlamayo's own demo setting, with no Scenic involved.

Town03, ego at a random clear spawn point, 50 NPC vehicles + 50 walkers on the
traffic manager -- module/config.py plus carla_interface.spawn_ego_vehicle.
The driving loop is alpamayo_core.DriverCore, byte-for-byte the same object the
Scenic runner uses, so any behavioural difference between the two settings is
the scene, not the harness.
"""
from __future__ import annotations

import argparse, json, os, random, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (Carlamayo + CARLA PythonAPI on sys.path, repo locations)
import alpamayo_core as core_mod
from alpamayo_core import DriverCore, get_adapter, seed_everything

import carla
import module.config as cfg
from module.carla_interface import is_allowed_npc_vehicle_blueprint


def populate(client, world, tm, seed):
    """ego + NPCs, following carla_interface's own spawn logic."""
    bl = world.get_blueprint_library()
    sps = world.get_map().get_spawn_points()
    random.shuffle(sps)

    def clear(sp, d=8.0):
        return all(a.get_location().distance(sp.location) >= d
                   for a in world.get_actors().filter("vehicle.*"))

    spawn = next((sp for sp in sps if clear(sp)), random.choice(sps))
    ebp = bl.find("vehicle.tesla.model3")
    ebp.set_attribute("role_name", "hero")
    ego = world.spawn_actor(ebp, spawn)

    # match carla_interface.spawn_npcs: without these the NPCs default to 30%
    # below the speed limit and a different following distance, so the traffic
    # around the ego is not the traffic Carlamayo's demo shows
    tm.set_global_distance_to_leading_vehicle(2.0)
    tm.global_percentage_speed_difference(0.0)

    vbps = [b for b in bl.filter("vehicle.*") if is_allowed_npc_vehicle_blueprint(b)]
    pts = [p for p in world.get_map().get_spawn_points() if p.location != spawn.location]
    random.shuffle(pts)
    batch = []
    for i in range(min(cfg.NPC_VEHICLE_COUNT, len(pts))):
        b = random.choice(vbps)
        b.set_attribute("role_name", "autopilot")
        batch.append(carla.command.SpawnActor(b, pts[i]).then(
            carla.command.SetAutopilot(carla.command.FutureActor, True, tm.get_port())))
    nv = sum(1 for r in client.apply_batch_sync(batch, True) if not r.error)

    wsp = []
    for _ in range(cfg.NPC_WALKER_COUNT * 4):
        loc = world.get_random_location_from_navigation()
        if loc:
            wsp.append(carla.Transform(loc))
        if len(wsp) >= cfg.NPC_WALKER_COUNT:
            break
    wres = client.apply_batch_sync(
        [carla.command.SpawnActor(random.choice(bl.filter("walker.pedestrian.*")), t)
         for t in wsp], True)
    wids = [r.actor_id for r in wres if not r.error]
    cbp = bl.find("controller.ai.walker")
    cres = client.apply_batch_sync(
        [carla.command.SpawnActor(cbp, carla.Transform(), w) for w in wids], True)
    for c in world.get_actors([r.actor_id for r in cres if not r.error]):
        c.start()
        c.go_to_location(world.get_random_location_from_navigation())
        c.set_max_speed(1.4)
    return ego, nv, len(wids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="random_spawn_1")
    ap.add_argument("--version", default="1", choices=["1", "1.5"])
    ap.add_argument("--ckpt-root", default=paths.CKPT_ROOT)
    ap.add_argument("--out", default=paths.RUNS)
    ap.add_argument("--port", type=int, default=3100)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--replan-every", type=int, default=1)
    ap.add_argument("--speed-mode", default="carlamayo", choices=["carlamayo", "plan", "planvel", "planlook", "tuned"],
                    help="carlamayo = upstream's clip(10+0.5*extent,10,35) heuristic; "
                         "plan = the speed its whole 6.4 s trajectory implies; "
                         "planvel = the velocity the plan carries over its first 1.5 s")
    ap.add_argument("--traj-samples", type=int, default=5,
                    help="NUM_TRAJ_SAMPLES; 5 keeps the similarity filter alive (upstream ships 1)")
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
                    help="re-render even if this scene is already in results_<tag>.jsonl")
    ap.add_argument("--tm-port", type=int, default=9100,
                    help="first TrafficManager port to try; scans upward on bind errors")
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
        cfg.NUM_TRAJ_SAMPLES = a.traj_samples
        print(f"NUM_TRAJ_SAMPLES = {a.traj_samples}", flush=True)

    # Skip work already on disk: a restarted batch re-invokes this per scene and
    # would otherwise re-render r1's random-spawn videos and append duplicate
    # result rows. --no-resume forces a re-run.
    tag_ = "r1" if a.version == "1" else "v15"
    res_ = os.path.join(a.out, f"results_{tag_}.jsonl")
    if not a.no_resume and os.path.exists(res_):
        for line in open(res_):
            if line.startswith("{"):
                try:
                    r0 = json.loads(line)
                except Exception:
                    continue
                if r0.get("id") == a.name and r0.get("status") in ("ok", "partial"):
                    print(f"{a.name} [{tag_}] already done; skipping", flush=True)
                    return

    seed_everything(a.seed)
    ad = get_adapter(a.version, a.ckpt_root)
    print(f"loading {ad.display_name} ...", flush=True)
    t0 = time.time()
    model, proc = ad.load_model(device_map="auto")
    print(f"LOAD {time.time()-t0:.1f}s", flush=True)
    tag = "r1" if a.version == "1" else "v15"

    client = carla.Client("127.0.0.1", a.port)
    client.set_timeout(120.0)
    world = client.load_world(cfg.CARLA_MAP)                # Town03
    # A fixed TM port collides with Scenic's own TrafficManager and with other
    # users on this machine ("failed to create because of bind error"), which
    # killed both random-spawn scenes silently. Scan for one that binds.
    tm = None
    for tm_port in range(a.tm_port, a.tm_port + 40):
        try:
            tm = client.get_trafficmanager(tm_port)
            break
        except RuntimeError as e:
            if "bind" not in str(e).lower():
                raise
    if tm is None:
        raise RuntimeError(f"no free TrafficManager port in "
                           f"{a.tm_port}..{a.tm_port + 39}")
    print(f"TrafficManager on port {tm_port}", flush=True)
    st = world.get_settings()
    st.synchronous_mode = True
    st.fixed_delta_seconds = 0.1
    world.apply_settings(st)
    tm.set_synchronous_mode(True)

    rec = {"id": a.name, "town": cfg.CARLA_MAP, "model": ad.display_name,
           "version": a.version, "seed": a.seed, "replan_every": a.replan_every,
           "traj_samples": a.traj_samples, "speed_mode": a.speed_mode,
           "status": "unknown"}
    t_run = time.time()
    core = None
    try:
        ego, nv, nw = populate(client, world, tm, a.seed)
        rec["npc_vehicles"], rec["npc_walkers"] = nv, nw
        print(f"spawned ego + {nv} vehicles + {nw} walkers on {cfg.CARLA_MAP}", flush=True)

        core = DriverCore(world, ego, ad, model, proc, replan_every=a.replan_every,
                          speed_mode=a.speed_mode)
        core.attach_sensors()
        core.warmup(world.tick)
        for _ in range(a.steps):
            world.tick()
            core.on_tick()

        os.makedirs(a.out, exist_ok=True)
        rec.update(core.summary())
        rec.update(core.write_videos(a.out, a.name, tag))
        with open(os.path.join(a.out, f"trace_{a.name}__{tag}.json"), "w") as fh:
            json.dump({"trace": core.trace, "coc": core.coc_log}, fh)
        rec["status"] = "ok" if rec.get("views_written") == 3 else "partial"
    except Exception as e:
        import traceback
        traceback.print_exc()
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        if core:
            core.detach_sensors()
        try:
            ego.destroy()
        except Exception:
            pass
        st.synchronous_mode = False
        world.apply_settings(st)
        tm.set_synchronous_mode(False)

    rec["wall_s"] = round(time.time() - t_run, 1)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, f"results_{tag}.jsonl"), "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print("RESULT " + json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
