"""One implementation of Carlamayo's closed loop, shared by every runner here.

Both the Scenic runner and the native random-spawn runner drive the ego through
this file, so the only difference between them is who owns the world and how the
scene was populated -- never the control loop. That is what makes the two
directly comparable; two hand-maintained copies had already drifted apart once.

Per tick, matching module/loops/closed_loop.py:
    world.tick() -> record ego state -> blocking synchronised camera read ->
    frame buffer -> inference -> PID -> apply control (effective next tick)
"""
from __future__ import annotations

import math, os, queue, random, subprocess, sys, time
import numpy as np
import carla, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (Carlamayo + CARLA PythonAPI on sys.path, repo locations)

import module.config as cfg
from module.inference import extract_trajectory_samples, select_trajectory_by_prev_similarity
from module.pid_controller import (OfficialPIDFollower, alpamayo_to_carla_local,
                                   local_to_world)
from module.visualization import project_trajectory_to_image

import pid_probe; pid_probe.install()

# Observer views. "fpv" is NOT a separate camera: it is the model's own
# front-wide camera, which is what the trajectory projection is calibrated for
# (camera_height=2.4, fov=120). Drawing it on any other camera mis-projects it.
OBSERVERS = {
    # world-aligned: follows the ego's position but keeps a fixed heading, so a
    # turn looks like the car turning rather than the map rotating around it
    "bev": dict(x=0.0,  y=0.0, z=28.0, pitch=-90.0, yaw=0.0, fov=90, w=960, h=540,
                attach=False),
    # chase camera: rides with the ego, so it does inherit the ego's heading
    "tpv": dict(x=-6.5, y=0.0, z=3.2,  pitch=-14.0, yaw=0.0, fov=90, w=960, h=540,
                attach=True),
}
VIEWS = list(OBSERVERS) + ["fpv"]
FPV_W, FPV_H = 1280, 720

# Draw only the selected trajectory, while still SAMPLING the full ensemble.
# This is the default, per the 2026-09-04 decision: sample five, paint one.
# The two are independent: NUM_TRAJ_SAMPLES controls how many plans the model
# draws (and therefore what select_trajectory_by_prev_similarity has to choose
# between -- the only temporal filter in the pipeline), while this flag controls
# how many get painted. Setting NUM_TRAJ_SAMPLES=1 to get a single line silently
# disables that filter; this flag gets the single line without paying for it.
DRAW_SELECTED_ONLY = True


# Alpamayo's trajectory head emits 64 waypoints at dt=0.1 s (checkpoint
# config.json: "dt": 0.1), so every prediction is a 6.4 second plan and the speed
# the model intends is simply its arclength over that horizon.
TRAJ_DT = 0.1


class PlanSpeedFollower(OfficialPIDFollower):
    """PID follower that takes its target speed from the model's own plan.

    Carlamayo derives the target from a heuristic on how far away the farthest
    waypoint is:

        target_kmh = clip(10.0 + 0.5 * traj_extent, 10.0, 35.0)

    The floor in that expression means the ego is commanded to keep moving at
    10 km/h no matter what the model predicted, so it cannot come to a stop.
    Measured against upstream's own Town03 run: in every frame where Alpamayo
    planned to stop, the PID was still told to drive at 10-11 km/h. That is
    tolerable in free driving, where it happens in 3% of frames, and fatal on a
    corner-case corpus where 46% of the scenarios exist precisely to make the
    car stop or yield.

    Reading the plan instead of guessing at it removes both ends of the problem:
    a stopping plan asks for 0 km/h, and a long plan is allowed past 35 km/h.
    Kept behind --speed-mode so the upstream behaviour stays reproducible.
    """

    MAX_KMH = 50.0

    def compute_control(self, vehicle_tf, wp_ego, speed_mps):
        wp = np.asarray(wp_ego, dtype=np.float64)
        n = len(wp)
        if n < 2:
            return super().compute_control(vehicle_tf, wp_ego, speed_mps)
        reach = float(np.linalg.norm(np.diff(wp[:, :2], axis=0), axis=1).sum())
        target_kmh = float(np.clip(3.6 * reach / ((n - 1) * TRAJ_DT), 0.0, self.MAX_KMH))

        wp_world = local_to_world(vehicle_tf, alpamayo_to_carla_local(wp))
        target_wp, target_idx, lookahead_m = self._pick_target(wp_world, speed_mps)
        if target_wp is None:
            return 0.0, 0.0, 0.0, {"mode": "plan_speed_no_target", "traj_extent": 0.0}
        c = self.pid.run_step(target_kmh, target_wp)
        return float(c.steer), float(c.throttle), float(c.brake), {
            "mode": "plan_speed",
            "target_speed_kmh": target_kmh,
            "lookahead_m": lookahead_m,
            "target_idx": int(target_idx),
            "traj_extent": float(np.max(np.linalg.norm(wp[:, :2], axis=1))),
        }


class PlanVelocityFollower(OfficialPIDFollower):
    """Target speed = the velocity the plan itself is carrying, not its length.

    Both other controllers derive target speed from how *long* the predicted
    path is:

        upstream : clip(10.0 + 0.5 * traj_extent, 10.0, 35.0)
        plan     : 3.6 * arclength / 6.4

    Alpamayo's output is a 6.4 s plan, so when it decides to slow down the path
    necessarily gets shorter -- less distance covered in the same 6.4 s. Feeding
    that back as "go slower" closes a positive feedback loop:

        slower -> shorter path -> read as slower -> slower still

    Measured on scenario 1 (R1): between t=83 and t=93 the path fell 65.4 m ->
    15.2 m and the ego went 34.8 km/h -> 0.0, while the Chain-of-Causation said
    "adapt speed for the right curve ahead" on all twenty of those frames. The
    model asked to slow for a bend; the controller stopped the car dead.

    The waypoints are evenly spaced in time (checkpoint config.json: dt = 0.1 s),
    so the speed the model intends *now* is simply how far apart the first few
    waypoints are. Reading that decouples "how fast" from "how far": a plan to
    cruise at 30 km/h gives the same near-term spacing whether the plan runs 6 m
    or 60 m. A slow-down then reads as a slow-down instead of as a stop.

    The target is also EMA-smoothed. Upstream smooths the control output
    (CONTROL_SMOOTH_ALPHA) but not the target it is chasing, so per-frame
    prediction noise still arrives at the PID as a step change.
    """

    AT_LOOKAHEAD = False   # read at the aim point rather than at the ego
    LOOK_S = 1.5        # read the plan's velocity over its first 1.5 seconds
    MAX_KMH = 50.0
    TGT_ALPHA = 0.3     # EMA on the target speed itself

    def __init__(self, world, vehicle):
        super().__init__(world, vehicle)
        self._tgt = None

    def compute_control(self, vehicle_tf, wp_ego, speed_mps):
        wp = np.asarray(wp_ego, dtype=np.float64)
        n = len(wp)
        if n < 3:
            return super().compute_control(vehicle_tf, wp_ego, speed_mps)

        wp_world0 = local_to_world(vehicle_tf, alpamayo_to_carla_local(wp))
        if self.AT_LOOKAHEAD:
            # The opening of the plan starts from the ego's *current* velocity,
            # so using it as a target is circular -- it asks the car to keep
            # doing what it is already doing and never to accelerate. The speed
            # the model actually intends is the one it plans to be carrying
            # where the PID is aiming, so read the spacing around that index.
            _, j, _ = self._pick_target(wp_world0, speed_mps)
            lo, hi = max(1, j - 2), min(n - 1, max(2, j) + 3)
            step = np.linalg.norm(np.diff(wp[lo - 1:hi + 1, :2], axis=0), axis=1).mean()
            raw = float(np.clip(3.6 * step / TRAJ_DT, 0.0, self.MAX_KMH))
        else:
            k = max(2, min(n - 1, int(round(self.LOOK_S / TRAJ_DT))))
            near = float(np.linalg.norm(np.diff(wp[:k + 1, :2], axis=0), axis=1).sum())
            raw = float(np.clip(3.6 * near / (k * TRAJ_DT), 0.0, self.MAX_KMH))
        self._tgt = raw if self._tgt is None else \
            (1 - self.TGT_ALPHA) * self._tgt + self.TGT_ALPHA * raw
        target_kmh = float(self._tgt)

        wp_world = local_to_world(vehicle_tf, alpamayo_to_carla_local(wp))
        target_wp, target_idx, lookahead_m = self._pick_target(wp_world, speed_mps)
        if target_wp is None:
            return 0.0, 0.0, 0.0, {"mode": "plan_velocity_no_target", "traj_extent": 0.0}
        c = self.pid.run_step(target_kmh, target_wp)
        return float(c.steer), float(c.throttle), float(c.brake), {
            "mode": "plan_velocity",
            "target_speed_kmh": target_kmh,
            "target_raw_kmh": raw,
            "lookahead_m": lookahead_m,
            "target_idx": int(target_idx),
            "traj_extent": float(np.max(np.linalg.norm(wp[:, :2], axis=1))),
        }


pid_probe.install(PlanSpeedFollower)
class PlanLookaheadFollower(PlanVelocityFollower):
    """PlanVelocityFollower, but reading the plan's velocity at the aim point."""
    AT_LOOKAHEAD = True


pid_probe.install(PlanVelocityFollower)
pid_probe.install(PlanLookaheadFollower)   # its override would otherwise shadow the probe


class TunedPIDFollower(OfficialPIDFollower):
    """Upstream's targets and geometry, rescaled longitudinal gains.

    Nothing here changes what the model is asked to do -- the target speed is
    still upstream's clip(10 + 0.5*extent, 10, 35). What changes is how hard
    CARLA reacts to being wrong about it.

    CARLA's PIDLongitudinalController takes its error in km/h
    (agents/navigation/controller.py:154) and clips K_P*e + K_D*de + K_I*ie to
    [-1, 1], and VehiclePIDController.run_step maps any negative output straight
    to brake with no deadband. With PID_LON_KP = 0.9 the controller reaches full
    authority at 1.11 km/h of error, so a 2.4 km/h overshoot became a 0.44 brake
    and the car stopped two frames later. That gain is upstream's config, not a
    porting artefact: it is the amplifier that turns plan jitter into lurching.

    Three independent knobs, so their effects can be attributed separately:

    LON_KP              rescale so full authority arrives at a speed error a
                        driver would actually respond to. K_I is scaled by the
                        same factor, keeping the K_I:K_P ratio upstream chose.
                        Note K_I matters more than it looks: _ie = sum(buffer)*dt
                        over a 10-deep buffer at dt=0.1 is ~= the error itself,
                        so upstream's 0.05 saturates on its own at 20 km/h.
    BRAKE_DEADBAND_KMH  coast rather than brake when barely over target. A human
                        lifts off; upstream stamps the brake pedal.
    STEER_GUARD         when the plan is too short to resolve the lookahead, the
                        lateral target is drawn from the noisy near field. Steer
                        jitter measures 2.2x higher while stopped (0.0237 vs
                        0.0109) with mean extent 6.8 m vs 24.0 m, which is how a
                        stopped car creeps out of its lane. Hold straight instead
                        of chasing a target the plan does not actually define.
    """

    LON_KP = 0.07             # full authority at ~14 km/h of error, not 1.11
    BRAKE_DEADBAND_KMH = 0.0
    STEER_GUARD = False
    STEER_GUARD_TAIL_FRAC = 0.8   # guard when the lookahead lands past this much of the plan
    STEER_GUARD_MAX_MPS = 1.0     # ...and only while barely moving

    def __init__(self, world, vehicle):
        super().__init__(world, vehicle)
        if self.LON_KP:
            scale = self.LON_KP / cfg.PID_LON_KP
            self.pid.change_longitudinal_PID({
                "K_P": self.LON_KP,
                "K_I": cfg.PID_LON_KI * scale,
                "K_D": cfg.PID_LON_KD * scale,
                "dt": cfg.CONTROL_DT,
            })

    def compute_control(self, vehicle_tf, wp_ego, speed_mps):
        # Reach the real method directly: super().compute_control is the probe's
        # wrapper, and going through it would log every step twice.
        base = getattr(OfficialPIDFollower, "_probe_orig", None) or OfficialPIDFollower.compute_control
        steer, throttle, brake, dbg = base(self, vehicle_tf, wp_ego, speed_mps)
        dbg["lon_kp"] = self.LON_KP or cfg.PID_LON_KP
        dbg.setdefault("traj_pts", int(np.asarray(wp_ego).shape[0]))

        if self.BRAKE_DEADBAND_KMH and brake > 0.0:
            err = float(dbg.get("target_speed_kmh", 0.0)) - speed_mps * 3.6
            if -self.BRAKE_DEADBAND_KMH < err <= 0.0:
                throttle = brake = 0.0
                dbg["deadband_coast"] = True

        if self.STEER_GUARD:
            # First attempt compared the plan's ARC LENGTH to the lookahead. That is
            # dead code: arc is the sum of 63 segments and is always larger than a
            # 4 m lookahead, so it fired 0 times in 97 calls. The quantity that
            # actually matters is where along the plan the lookahead lands. Measured
            # over the scene-9 runs: while stopped, target_idx averages 53 of 63 and
            # sits in the last fifth of the plan on 64% of frames (moving: 26, 19%),
            # because a stopped car's waypoints are packed so tightly that 4 m of arc
            # consumes the whole prediction. The lateral controller is then steering
            # at the terminal waypoint of a 6.4 s plan -- its least constrained point.
            # Speed-gated, because the tail condition alone is far too blunt. Over
            # 776 recorded control steps it holds on 32% of frames -- including 100
            # while moving, 14 of which command a real turn (|steer| > 0.10). Gating
            # on speed < 1 m/s narrows it to 5% of frames and 2 such turns, which is
            # the actual pathology: a stopped car whose plan has been consumed by the
            # lookahead. Note target_idx == n does NOT mean the plan is shorter than
            # the lookahead -- searchsorted returns n when the lookahead lands in the
            # final segment -- which is why the earlier arc-length test never fired.
            n = int(dbg.get("traj_pts", len(wp_ego))) - 1
            idx = int(dbg.get("target_idx", 0))
            if (n > 0 and idx > self.STEER_GUARD_TAIL_FRAC * n
                    and speed_mps < self.STEER_GUARD_MAX_MPS):
                steer = 0.0
                dbg["steer_guard"] = True
                dbg["target_idx_frac"] = round(idx / n, 3)

        return steer, throttle, brake, dbg


pid_probe.install(TunedPIDFollower)


DETERMINISTIC = False


def seed_everything(seed):
    """Alpamayo samples trajectories with temperature=0.6 / top_p=0.98 plus a
    diffusion sampler, so torch RNG -- not just python/numpy -- decides the
    rollout. Without this the same scene produces a different drive each run.

    Seeding alone is NOT enough. Two runs with identical configuration and the
    same seed were measured diverging at t=3, on the very first inference call
    (traj_extent 6.76 vs 6.89), and by t=8 the plans were unrelated (2.94 vs
    15.80). The RNG stream is fixed; the kernels are not -- TF32 matmuls, cuDNN
    algorithm selection and non-deterministic reductions all vary run to run, and
    a closed loop turns that into a different drive. DETERMINISTIC pins those
    too, at some cost in inference speed. Note CUBLAS_WORKSPACE_CONFIG must be
    set in the environment before CUDA initialises; the runners' worker scripts
    export it."""
    import torch
    random.seed(seed); np.random.seed(seed)
    torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    if DETERMINISTIC:
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False


def get_adapter(version, ckpt_root):
    if version == "1":
        from module.adapters.alpamayo_r1 import AlpamayoR1Adapter as A
        local = os.path.join(ckpt_root, "Alpamayo-R1-10B")
    elif version == "1.5":
        from module.adapters.alpamayo_1_5 import Alpamayo15Adapter as A
        local = os.path.join(ckpt_root, "Alpamayo-1.5-10B")
    else:
        raise ValueError(f"unsupported version {version}")
    return type("LocalAdapter", (A,), {"model_id": os.path.abspath(local)})()


def draw_overlay(rgb_img, pred_xyz, sel_idx, frame_i, inf_t, coc_text, speed_kmh, steer):
    """Carlamayo-style overlay, using Alpamayo's own term: Chain-of-Causation."""
    vis = project_trajectory_to_image(rgb_img, pred_xyz, selected_idx=sel_idx)
    vis = cv2.cvtColor(vis, cv2.COLOR_RGB2BGR)
    vis = cv2.resize(vis, (FPV_W, FPV_H), interpolation=cv2.INTER_AREA)
    h, w = vis.shape[:2]
    ov = vis.copy()
    cv2.rectangle(ov, (0, 0), (w, 34), (0, 0, 0), -1)
    cv2.rectangle(ov, (0, h - 58), (w, h), (0, 0, 0), -1)
    vis = cv2.addWeighted(ov, 0.62, vis, 0.38, 0)
    hud = (f"Frame {frame_i} | Inference {inf_t:.2f}s | "
           f"Speed {speed_kmh:.1f} km/h | Steer {steer:+.2f}")
    cv2.putText(vis, hud, (12, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
    txt = " ".join((coc_text or "").split())
    mc = 96
    lines = [txt[i:i + mc] for i in range(0, min(len(txt), mc * 2), mc)] or [""]
    cv2.putText(vis, "CoC: " + lines[0], (12, h - 34), cv2.FONT_HERSHEY_SIMPLEX,
                0.56, (150, 235, 150), 1, cv2.LINE_AA)
    if len(lines) > 1:
        cv2.putText(vis, "     " + lines[1], (12, h - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.56, (150, 235, 150), 1, cv2.LINE_AA)
    return vis


def write_video(frames, path, fps=10):
    """Pipe raw BGR frames straight into ffmpeg.

    The previous path wrote a VP9 file with cv2.VideoWriter and then transcoded
    it to H.264, which cost about 90 s per scenario -- hours across the corpus,
    for an intermediate nobody reads. Encoding once, from the frames already in
    memory, produces the same H.264/yuv420p/faststart file the browser needs.
    """
    if not frames:
        return 0
    import imageio_ffmpeg
    h, w = frames[0].shape[:2]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE)
    try:
        for f in frames:
            p.stdin.write(np.ascontiguousarray(f).tobytes())
        p.stdin.close()
        p.wait(timeout=600)
    except Exception as e:
        print(f"  video encode failed for {os.path.basename(path)}: {e}", flush=True)
        try:
            p.kill()
        except Exception:
            pass
        return 0
    return os.path.getsize(path) if os.path.exists(path) else 0


class DriverCore:
    """Alpamayo drives one ego vehicle in one CARLA world, one tick at a time."""

    def __init__(self, world, ego, adapter, model, processor, replan_every=1,
                 nav_text="", speed_mode="carlamayo"):
        self.world, self.ego = world, ego
        self.adapter, self.model, self.processor = adapter, model, processor
        self.replan_every = max(1, int(replan_every))
        # Alpamayo R1 has no route input at all, so it picks its own manoeuvre and
        # will happily turn right where the scenario intends a left. 1.5 accepts a
        # navigation string; giving it the scenario's own description is the only
        # way to tell either model what the scene is asking for.
        self.nav_text = nav_text if getattr(adapter, "supports_navigation", False) else ""
        self.frames = {k: [] for k in VIEWS}
        self.hist, self.mbuf, self.trace, self.inf_times, self.coc_log = [], [], [], [], []
        self.traj = self.pred = self.prev_traj = None
        self.sel, self.coc, self.inf_t, self.i = 0, "", 0.0, 0
        self.prev = {"steer": 0.0, "throttle": 0.0, "brake": 0.0}
        self.mq, self.oq, self.sensors, self.free_cams = {}, {}, [], []
        self.collisions = []      # upstream runs a collision sensor; without one
                                  # a stuck ego is indistinguishable from a model
                                  # that chose to stop
        self.cam_order = list(adapter.source_camera_configs)
        self.speed_mode = speed_mode
        follower = {"plan": PlanSpeedFollower,
                    "planvel": PlanVelocityFollower,
                    "planlook": PlanLookaheadFollower,
                    "tuned": TunedPIDFollower}.get(speed_mode, OfficialPIDFollower)
        self.pid = follower(world, ego)

    # ---------- sensors ----------
    def attach_sensors(self):
        bl = self.world.get_blueprint_library()

        def cam(w, h, fov, post, loc, rot, q, attach=True):
            bp = bl.find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", str(w))
            bp.set_attribute("image_size_y", str(h))
            bp.set_attribute("fov", str(fov))
            if post:
                bp.set_attribute("enable_postprocess_effects", "True")
            tf = carla.Transform(loc, rot)
            if attach:
                s = self.world.spawn_actor(bp, tf, attach_to=self.ego)
            else:
                el = self.ego.get_transform().location
                s = self.world.spawn_actor(bp, carla.Transform(
                    carla.Location(x=el.x + loc.x, y=el.y + loc.y, z=el.z + loc.z), rot))
                self.free_cams.append((s, loc, rot))
            # Blocking queue, as Carlamayo does: guarantees every camera contributes
            # a frame from the SAME tick. A last-write-wins dict hands the model
            # views of differing age, which it reads as motion that never happened.
            s.listen(lambda img, qq=q: qq.put(img))
            self.sensors.append(s)

        for name, c in self.adapter.source_camera_configs.items():
            self.mq[name] = queue.Queue()
            cam(cfg.IMG_WIDTH, cfg.IMG_HEIGHT, c["fov"], True,
                carla.Location(x=c["x"], y=c["y"], z=c["z"]),
                carla.Rotation(pitch=c["pitch"], yaw=c["yaw"]), self.mq[name])
        for name, c in OBSERVERS.items():
            self.oq[name] = queue.Queue()
            cam(c["w"], c["h"], c["fov"], False,
                carla.Location(x=c["x"], y=c["y"], z=c["z"]),
                carla.Rotation(pitch=c["pitch"], yaw=c["yaw"]), self.oq[name],
                attach=c.get("attach", True))
        self._attach_collision()

    def _attach_collision(self):
        bp = self.world.get_blueprint_library().find("sensor.other.collision")
        s = self.world.spawn_actor(bp, carla.Transform(), attach_to=self.ego)
        s.listen(lambda e: self.collisions.append({
            "t": self.i,
            "with": getattr(e.other_actor, "type_id", "?"),
            "impulse": round(float((e.normal_impulse.x ** 2 + e.normal_impulse.y ** 2
                                    + e.normal_impulse.z ** 2) ** 0.5), 1)}))
        self.sensors.append(s)

    def detach_sensors(self):
        for s in self.sensors:
            try:
                s.stop(); s.destroy()
            except Exception:
                pass
        self.sensors = []

    def _drain(self):
        for q in list(self.mq.values()) + list(self.oq.values()):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass

    def _grab(self, q, h, w, rgb):
        try:
            d = q.get(timeout=2.0)
        except queue.Empty:
            return None
        a = np.frombuffer(d.raw_data, np.uint8).reshape((h, w, 4))[:, :, :3]
        return cv2.cvtColor(a, cv2.COLOR_BGR2RGB) if rgb else a.copy()

    # ---------- state ----------
    def record_state(self):
        tf = self.ego.get_transform()
        self.hist.append({"x": tf.location.x, "y": tf.location.y,
                          "z": tf.location.z, "yaw": tf.rotation.yaw})
        if len(self.hist) > cfg.NUM_HISTORY:
            self.hist.pop(0)

    def ego_history(self):
        """Port of carla_interface.get_history_in_local_frame."""
        n = cfg.NUM_HISTORY
        if not self.hist:
            self.record_state()
        buf = list(self.hist)
        while len(buf) < n:
            buf.insert(0, buf[0])
        cur = buf[-1]
        cp = np.array([cur["x"], cur["y"], cur["z"]])
        yaw = math.radians(-cur["yaw"])
        c_, s_ = math.cos(yaw), math.sin(yaw)
        R = np.array([[c_, -s_, 0], [s_, c_, 0], [0, 0, 1]])
        hx = np.zeros((n, 3), np.float32)
        hr = np.zeros((n, 3, 3), np.float32)
        for i, st in enumerate(buf):
            hx[i] = R @ (np.array([st["x"], st["y"], st["z"]]) - cp)
            ry = math.radians(-st["yaw"]) - yaw
            hr[i] = np.array([[math.cos(ry), -math.sin(ry), 0],
                              [math.sin(ry), math.cos(ry), 0], [0, 0, 1]])
        return hx, hr

    def speed(self):
        v = self.ego.get_velocity()
        return float(math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2))

    def warmup(self, tick):
        """Fill the history buffer with real motion before the first inference."""
        for _ in range(cfg.NUM_HISTORY):
            self._follow()
            tick()
            self.record_state()
            self._drain()

    # ---------- the tick ----------
    def on_tick(self):
        """Call immediately AFTER world.tick(). Does everything for this frame."""
        self.record_state()
        imgs = [self._grab(self.mq[n], cfg.IMG_HEIGHT, cfg.IMG_WIDTH, True)
                for n in self.cam_order]
        if all(im is not None for im in imgs):
            self.mbuf.append(imgs)
            if len(self.mbuf) > cfg.NUM_FRAMES:
                self.mbuf.pop(0)

        if len(self.mbuf) >= cfg.NUM_FRAMES and self.i % self.replan_every == 0:
            arr = np.zeros((len(self.cam_order), cfg.NUM_FRAMES,
                            cfg.IMG_HEIGHT, cfg.IMG_WIDTH, 3), np.uint8)
            for c in range(len(self.cam_order)):
                for t in range(cfg.NUM_FRAMES):
                    arr[c, t] = self.mbuf[t][c]
            hx, hr = self.ego_history()
            t0 = time.time()
            data = self.adapter.prepare_model_input(
                arr, hx, hr, int(self.i * cfg.CONTROL_DT * 1_000_000))
            px, extra = (self.adapter.run_inference(self.model, self.processor, data,
                                                   navigation_text=self.nav_text)
                         if self.nav_text else
                         self.adapter.run_inference(self.model, self.processor, data))
            self.inf_t = time.time() - t0
            self.inf_times.append(self.inf_t)
            sm = extract_trajectory_samples(px)
            self.sel, _ = select_trajectory_by_prev_similarity(sm, self.prev_traj)
            self.traj = sm[self.sel]
            self.prev_traj = sm[self.sel].copy()
            self.pred = sm
            coc = self.adapter.extract_cot_text(extra)
            if coc:
                self.coc = coc
                self.coc_log.append({"t": self.i, "coc": coc[:300]})

        steer = throttle = brake = 0.0
        dbg = {}
        if self.traj is not None:
            sr, tr, br, dbg = self.pid.compute_control(
                self.ego.get_transform(), self.traj[:, :3], self.speed())
            a = cfg.CONTROL_SMOOTH_ALPHA
            steer = (1 - a) * self.prev["steer"] + a * sr
            throttle = (1 - a) * self.prev["throttle"] + a * tr
            brake = (1 - a) * self.prev["brake"] + a * br
            if throttle >= brake:
                brake = 0.0
            else:
                throttle = 0.0
            self.prev = {"steer": steer, "throttle": throttle, "brake": brake}
            self.ego.apply_control(carla.VehicleControl(
                throttle=float(np.clip(throttle, 0, 1)),
                steer=float(np.clip(steer, -1, 1)),
                brake=float(np.clip(brake, 0, 1))))

        self.trace.append({
            "t": self.i, "speed": round(self.speed(), 2),
            "throttle": round(float(throttle), 2), "brake": round(float(brake), 2),
            "steer": round(float(steer), 3),
            "target_kmh": round(float(dbg.get("target_speed_kmh", 0.0)), 1),
            "traj_extent": round(float(dbg.get("traj_extent", 0.0)), 2),
        })

        slot = self.adapter.viz_camera_slot
        if imgs[slot] is not None and self.pred is not None:
            pred, sel = self.pred, self.sel
            if DRAW_SELECTED_ONLY:
                pred, sel = pred[sel:sel + 1], 0
            self.frames["fpv"].append(draw_overlay(
                imgs[slot], pred, sel, self.i, self.inf_t,
                self.coc, self.speed() * 3.6, steer))
        for name, c in OBSERVERS.items():
            im = self._grab(self.oq[name], c["h"], c["w"], False)
            if im is not None:
                self.frames[name].append(im)
        self._follow()
        self.i += 1

    def _follow(self):
        """Re-place the unattached cameras over the ego, keeping their world heading."""
        if not self.free_cams:
            return
        el = self.ego.get_transform().location
        for s, off, rot in self.free_cams:
            try:
                s.set_transform(carla.Transform(
                    carla.Location(x=el.x + off.x, y=el.y + off.y, z=el.z + off.z), rot))
            except Exception:
                pass

    # ---------- reporting ----------
    def summary(self):
        first = self.collisions[0] if self.collisions else None
        out = {"frames": len(self.frames["tpv"]), "nav_text": self.nav_text[:160],
               "speed_mode": self.speed_mode,
               "collisions": len(self.collisions),
               "first_collision_frame": first["t"] if first else None,
               "first_collision_with": first["with"] if first else None,
               "inference_calls": len(self.inf_times),
               "inference_mean_s": round(float(np.mean(self.inf_times)), 2) if self.inf_times else 0,
               "coc_last": (self.coc or "")[:200],
               "coc_emissions": len(self.coc_log)}
        if self.trace:
            sp = [x["speed"] for x in self.trace]
            tgt = [x["target_kmh"] for x in self.trace if x["target_kmh"] > 0]
            ext = [x["traj_extent"] for x in self.trace if x["traj_extent"] > 0]
            out.update(
                speed_mean=round(sum(sp) / len(sp), 2), speed_max=round(max(sp), 2),
                frac_stopped=round(sum(1 for v in sp if v < 0.5) / len(sp), 2),
                frac_braking=round(sum(1 for x in self.trace if x["brake"] > 0.05) / len(self.trace), 2),
                steer_abs_mean=round(sum(abs(x["steer"]) for x in self.trace) / len(self.trace), 3),
                target_kmh_mean=round(sum(tgt) / len(tgt), 1) if tgt else 0,
                traj_extent_mean=round(sum(ext) / len(ext), 2) if ext else 0)
        return out

    def write_videos(self, out_dir, stem, tag):
        rec, n = {}, 0
        for v in VIEWS:
            b = write_video(self.frames.get(v, []), os.path.join(out_dir, f"{stem}__{tag}__{v}.mp4"))
            rec[f"{v}_bytes"] = b
            if b:
                n += 1
        rec["views_written"] = n
        return rec
