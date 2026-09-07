"""Persistent worker: holds CARLA + Alpamayo resident, serves live-render jobs.

Run on one GPU by scripts/demo.sh. The models load once (~1-4 min); each job then
takes roughly 3-7 min. Jobs arrive as JSON files in outputs/live/jobs and progress
is published to outputs/live/status so the web page can show it while rendering.

Every run is live inference: Alpamayo sees the rendered cameras and decides each
step itself. The seed fixes where Scenic places the scene, not the drive - the
model samples its reasoning and trajectories, so two runs of the same job can
take different decisions, which is exactly what the studio is there to show.
"""
from __future__ import annotations
import json, math, os, random, re, sys, time, traceback
from queue import Queue, Empty
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (Carlamayo + CARLA PythonAPI on sys.path, repo locations)
os.chdir(paths.ROOT)

import carla
import scenic
from scenic.simulators.carla.simulator import CarlaSimulator, CarlaSimulation
import module.config as cfg
from module.inference import extract_trajectory_samples, select_trajectory_by_prev_similarity
from module.pid_controller import OfficialPIDFollower
from module.visualization import project_trajectory_to_image

# Sample several trajectories and highlight the chosen one; the alternatives are
# drawn faintly by the overlay. Never collapse this to 1 just to get one line.
cfg.NUM_TRAJ_SAMPLES = 5

def draw_overlay(cam_img, pred_xyz, frame_count, cot_text, speed_kmh, steering):
    """The first-person overlay.

    A local copy rather than module.visualization.create_visualization_frame,
    which belongs to the Carlamayo checkout and is left untouched. Three
    differences: no inference timing (a replayed run does no inference, so
    reporting one would be inventing a measurement), no RUNNING/Nav/Weight
    status line, and the chain of thought is drawn in green.
    """
    import cv2, textwrap
    if pred_xyz is None:
        # Replayed controls: the model was not run, so there is no predicted
        # line to project. The frame/speed/steer readout and the chain of
        # thought are still real, and are drawn exactly as elsewhere.
        vis = cv2.cvtColor(cam_img, cv2.COLOR_RGB2BGR)
    else:
        vis = cv2.cvtColor(project_trajectory_to_image(cam_img, pred_xyz, selected_idx=0),
                           cv2.COLOR_RGB2BGR)
    h, w = vis.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX

    info = f"Frame: {frame_count} | Speed: {speed_kmh:.1f} km/h | Steer: {steering:.2f}"
    (tw, th), _ = cv2.getTextSize(info, font, 1.0, 2)
    o = vis.copy()
    cv2.rectangle(o, (10, 10), (min(w - 10, 10 + tw + 28), 10 + th + 28), (0, 0, 0), -1)
    vis = cv2.addWeighted(o, 0.6, vis, 0.4, 0)
    cv2.putText(vis, info, (20, 50), font, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

    cot = cot_text[:200] + "..." if len(cot_text) > 200 else cot_text
    lines = textwrap.wrap(f"CoT: {cot}", width=120)[:3]
    if lines:
        box_top = h - (34 * len(lines) + 26)
        o = vis.copy()
        cv2.rectangle(o, (10, box_top), (w - 10, h - 10), (0, 0, 0), -1)
        vis = cv2.addWeighted(o, 0.6, vis, 0.4, 0)
        y = box_top + 34
        for line in lines:                      # green, as in the earlier videos
            cv2.putText(vis, line, (20, y), font, 0.7, (127, 212, 143), 2, cv2.LINE_AA)
            y += 30
    return cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)


# A second worker can serve batch work alongside the demo one by pointing
# LIVE_QUEUE at its own queue directory.
_Q = os.environ.get("LIVE_QUEUE") or paths.LIVE
JOBS, STATUS, OUT = f"{_Q}/jobs", f"{_Q}/status", f"{_Q}/out"

OBSERVERS = {
    "bev": dict(x=0.0,  y=0.0, z=28.0, pitch=-90.0, yaw=0.0, fov=90, w=960,  h=540),
    "fpv": dict(x=1.4,  y=0.0, z=1.5,  pitch=0.0,   yaw=0.0, fov=90, w=1280, h=720),
    "tpv": dict(x=-6.5, y=0.0, z=3.2,  pitch=-14.0, yaw=0.0, fov=90, w=960,  h=540),
}


def beat():
    try: open(f"{_Q}/worker_ready", "w").write(str(time.time()))
    except Exception: pass


def pub(jid, **kw):
    # every publish is also a heartbeat: a job runs for minutes without touching
    # the main loop, and the page would otherwise fade to "warming up" mid-run.
    beat()
    p = os.path.join(STATUS, jid + ".json")
    cur = {}
    if os.path.exists(p):
        try: cur = json.load(open(p))
        except Exception: cur = {}
    cur.update(kw); cur["updated"] = time.time()
    tmp = p + ".tmp"
    with open(tmp, "w") as f: json.dump(cur, f)
    os.replace(tmp, p)


def get_adapter(version):
    if version == "1":
        from module.adapters.alpamayo_r1 import AlpamayoR1Adapter as A
        local = os.path.join(paths.CKPT_ROOT, "Alpamayo-R1-10B")
    else:
        from module.adapters.alpamayo_1_5 import Alpamayo15Adapter as A
        local = os.path.join(paths.CKPT_ROOT, "Alpamayo-1.5-10B")
    return type("LocalAdapter", (A,), {"model_id": os.path.abspath(local)})()


class LiveSim(CarlaSimulation):
    adapter = model = processor = None
    replan_every = 1        # replan every step, as the batch runner does
    jid = ""
    total_steps = 120
    job_seed = 42
    ctrl = None             # per-step recorded controls to re-render a drive (render_clean.py)
    cot_trace = None        # [{"t": i, "coc": text}] to caption a replayed drive
    overlay = True          # draw the prediction overlay on the first-person view

    def setup(self):
        super().setup()
        self.enc = {}          # view -> Enc, opened on its first frame
        self.hist, self.mbuf, self.trace, self.inf_times = [], [], [], []
        self._cot_i = 0                 # index into cot_trace, for captioned replays
        self._latest, self._mlatest, self._sensors = {}, {}, []
        self._mq, self._oq = {}, {}     # name -> Queue of raw carla images
        self._traj = self._pred = None
        self._sel, self._cot, self._inf_t, self._prev_traj = 0, "", 0.0, None
        self._prev = {"steer": 0.0, "throttle": 0.0, "brake": 0.0}
        self._i = 0
        ego = self.objects[0].carlaActor
        bl = self.world.get_blueprint_library()
        for name, c in self.adapter.source_camera_configs.items():
            bp = bl.find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", str(cfg.IMG_WIDTH))
            bp.set_attribute("image_size_y", str(cfg.IMG_HEIGHT))
            bp.set_attribute("fov", str(c["fov"]))
            # Post-processing stays on (turning it off darkens the image badly),
            # but its adaptive parts are fixed: auto-exposure drifting over the
            # run and motion blur mixing in the previous frame change what the
            # model sees for reasons that have nothing to do with the scene.
            bp.set_attribute("enable_postprocess_effects", "True")
            for attr, val in (("motion_blur_intensity", "0.0"),
                              ("motion_blur_max_distortion", "0.0"),
                              ("motion_blur_min_object_screen_size", "0.0"),
                              ("exposure_mode", "manual"),
                              ("bloom_intensity", "0.0"),
                              ("lens_flare_intensity", "0.0"),
                              ("chromatic_aberration_intensity", "0.0"),
                              ("blur_amount", "0.0")):
                if bp.has_attribute(attr):
                    bp.set_attribute(attr, val)
            s = self.world.spawn_actor(bp, carla.Transform(
                carla.Location(x=c["x"], y=c["y"], z=c["z"]),
                carla.Rotation(pitch=c["pitch"], yaw=c["yaw"])), attach_to=ego)
            self._mq[name] = Queue()
            s.listen(self._mq[name].put)
            self._sensors.append(s)
        for name, c in OBSERVERS.items():
            bp = bl.find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", str(c["w"]))
            bp.set_attribute("image_size_y", str(c["h"]))
            bp.set_attribute("fov", str(c["fov"]))
            s = self.world.spawn_actor(bp, carla.Transform(
                carla.Location(x=c["x"], y=c["y"], z=c["z"]),
                carla.Rotation(pitch=c["pitch"], yaw=c["yaw"])), attach_to=ego)
            self._oq[name] = Queue()
            s.listen(self._oq[name].put)
            self._sensors.append(s)
        self.pid = OfficialPIDFollower(self.world, ego)
        for _ in range(cfg.NUM_HISTORY):
            self.world.tick(); self._collect(); self._rec()

    def _collect(self, timeout=5.0):
        """Take exactly the images belonging to the current tick from every sensor.

        listen() delivers asynchronously. Reading whatever happens to be in a
        dict means the model can be fed a frame from a different tick depending
        on how the threads were scheduled. Matching on the snapshot's frame id
        guarantees every camera image belongs to the step being decided.
        """
        frame = self.world.get_snapshot().frame
        for q, store, to_rgb in ((self._mq, self._mlatest, True),
                                 (self._oq, self._latest, False)):
            for name, qq in q.items():
                img = None
                while True:
                    try:
                        d = qq.get(timeout=timeout)
                    except Empty:
                        break
                    if d.frame >= frame:
                        img = d
                        break
                if img is None:
                    continue
                a = np.frombuffer(img.raw_data, np.uint8).reshape(
                    (img.height, img.width, 4))[:, :, :3]
                store[name] = (a[:, :, ::-1] if to_rgb else a).copy()

    def _rec(self):
        tf = self.objects[0].carlaActor.get_transform()
        self.hist.append({"x": tf.location.x, "y": tf.location.y,
                          "z": tf.location.z, "yaw": tf.rotation.yaw})
        if len(self.hist) > cfg.NUM_HISTORY: self.hist.pop(0)

    def _ego_hist(self):
        n = cfg.NUM_HISTORY
        if not self.hist: self._rec()
        buf = list(self.hist)
        while len(buf) < n: buf.insert(0, buf[0])
        cur = buf[-1]; cp = np.array([cur["x"], cur["y"], cur["z"]])
        yaw = math.radians(-cur["yaw"]); c_, s_ = math.cos(yaw), math.sin(yaw)
        R = np.array([[c_, -s_, 0], [s_, c_, 0], [0, 0, 1]])
        hx = np.zeros((n, 3), np.float32); hr = np.zeros((n, 3, 3), np.float32)
        for i, st in enumerate(buf):
            hx[i] = R @ (np.array([st["x"], st["y"], st["z"]]) - cp)
            ry = math.radians(-st["yaw"]) - yaw
            hr[i] = np.array([[math.cos(ry), -math.sin(ry), 0],
                              [math.sin(ry), math.cos(ry), 0], [0, 0, 1]])
        return hx, hr

    def _speed(self):
        v = self.objects[0].carlaActor.get_velocity()
        return float(math.sqrt(v.x**2 + v.y**2 + v.z**2))

    def executeActions(self, allActions):
        ego = self.objects[0]
        from collections import defaultdict
        d = defaultdict(tuple)
        d.update({a: acts for a, acts in allActions.items() if a is not ego})
        super().executeActions(d)

    def step(self):
        ego = self.objects[0].carlaActor
        self._rec()
        names = list(self.adapter.source_camera_configs.keys())
        if all(n in self._mlatest for n in names):
            self.mbuf.append([self._mlatest[n] for n in names])
            if len(self.mbuf) > cfg.NUM_FRAMES: self.mbuf.pop(0)
        if self.cot_trace:
            # The reasoning the model gave while producing this drive, replayed
            # alongside it, so the caption tracks the drive frame for frame.
            while (self._cot_i + 1 < len(self.cot_trace)
                   and self.cot_trace[self._cot_i + 1]["t"] <= self._i):
                self._cot_i += 1
            e = self.cot_trace[self._cot_i]
            self._cot = e.get("coc", e.get("cot", "")) if e["t"] <= self._i else ""
        if self.ctrl is not None:
            # Recorded commands are applied verbatim below; the model is never
            # consulted, so there is no predicted trajectory to draw.
            pass
        elif len(self.mbuf) >= cfg.NUM_FRAMES and self._i % self.replan_every == 0:
            imgs = np.zeros((len(names), cfg.NUM_FRAMES, cfg.IMG_HEIGHT, cfg.IMG_WIDTH, 3), np.uint8)
            for c in range(len(names)):
                for t in range(cfg.NUM_FRAMES): imgs[c, t] = self.mbuf[t][c]
            hx, hr = self._ego_hist(); t0 = time.time()
            px, extra = self.adapter.run_inference(
                self.model, self.processor, self.adapter.prepare_model_input(imgs, hx, hr, 0))
            self._inf_t = time.time() - t0; self.inf_times.append(self._inf_t)
            sm = extract_trajectory_samples(px)
            self._sel, _ = select_trajectory_by_prev_similarity(sm, self._prev_traj)
            self._traj = sm[self._sel]; self._prev_traj = sm[self._sel].copy(); self._pred = sm
            self._cot = self.adapter.extract_cot_text(extra) or self._cot
            pub(self.jid, phase="rendering", step=self._i, total=self.total_steps,
                cot=self._cot, inference_s=round(self._inf_t, 2),
                traj_samples=int(sm.shape[0]), selected=int(self._sel),
                speed_kmh=round(self._speed() * 3.6, 1))
        steer = throttle = brake = 0.0
        if self.ctrl is not None:
            r = self.ctrl[min(self._i, len(self.ctrl) - 1)]
            steer = float(r.get("steer", 0.0)); throttle = float(r.get("throttle", 0.0))
            brake = float(r.get("brake", 0.0))
            ego.apply_control(carla.VehicleControl(
                throttle=float(np.clip(throttle, 0, 1)), steer=float(np.clip(steer, -1, 1)),
                brake=float(np.clip(brake, 0, 1))))
            if self._i % 10 == 0:
                pub(self.jid, phase="rendering", step=self._i, total=self.total_steps,
                    speed_kmh=round(self._speed() * 3.6, 1))
        elif self._traj is not None:
            sr, tr, br, _ = self.pid.compute_control(ego.get_transform(), self._traj[:, :3], self._speed())
            a = cfg.CONTROL_SMOOTH_ALPHA
            steer = (1-a)*self._prev["steer"] + a*sr
            throttle = (1-a)*self._prev["throttle"] + a*tr
            brake = (1-a)*self._prev["brake"] + a*br
            if throttle >= brake: brake = 0.0
            else: throttle = 0.0
            self._prev = {"steer": steer, "throttle": throttle, "brake": brake}
            ego.apply_control(carla.VehicleControl(
                throttle=float(np.clip(throttle, 0, 1)), steer=float(np.clip(steer, -1, 1)),
                brake=float(np.clip(brake, 0, 1))))
        tf = ego.get_transform()
        self.trace.append({"t": self._i, "speed": round(self._speed(), 4),
                           "x": round(tf.location.x, 4), "y": round(tf.location.y, 4),
                           "yaw": round(tf.rotation.yaw, 3), "sel": int(self._sel),
                           "steer": round(steer, 5), "throttle": round(throttle, 5),
                           "brake": round(brake, 5)})
        super().step()
        self._collect()
        for nm in OBSERVERS:
            img = self._latest.get(nm)
            if img is None: continue
            if nm == "fpv" and self.overlay and (self._pred is not None
                                                 or self.cot_trace is not None):
                # Five candidates are still sampled; only the one the car is
                # actually following is drawn, so the overlay shows the decision
                # rather than the search.
                fr = draw_overlay(img, None if self._pred is None
                                  else self._pred[self._sel:self._sel + 1],
                                  self._i, self._cot, self._speed()*3.6, steer)
            else:
                fr = img
            e = self.enc.get(nm)
            if e is None:
                h, w = fr.shape[:2]
                e = self.enc[nm] = Enc(os.path.join(OUT, f"{self.jid}__{nm}.mp4"), w, h)
            e.write(fr)
        self._i += 1
        if self._i % 10 == 0:
            pub(self.jid, phase="rendering", step=self._i, total=self.total_steps)

    def destroy(self):
        for s in getattr(self, "_sensors", []):
            try: s.stop(); s.destroy()
            except Exception: pass
        self._sensors = []
        super().destroy()


class LiveSimulator(CarlaSimulator):
    last = None
    def createSimulation(self, scene, *, timestep, **kw):
        self.scenario_number += 1
        LiveSim.adapter, LiveSim.model, LiveSim.processor = self._ad, self._m, self._p
        LiveSim.replan_every, LiveSim.jid, LiveSim.total_steps = self._replan, self._jid, self._steps
        LiveSim.job_seed = self._seed
        LiveSim.ctrl = getattr(self, "_ctrl", None)
        LiveSim.cot_trace = getattr(self, "_cot_trace", None)
        LiveSim.overlay = getattr(self, "_overlay", True)
        try:    # the traffic manager has its own RNG; tie it to the scene seed
            self.tm.set_random_device_seed(int(self._seed))
        except Exception:
            pass
        s = LiveSim(scene, self.client, self.tm, self.render, self.record,
                    self.scenario_number, timestep=timestep, **kw)
        LiveSimulator.last = s
        return s


def town_of(p):
    t = open(p).read()
    m = re.search(r"param\s+carla_map\s*=\s*['\"](Town\w+)['\"]", t)
    if m: return m.group(1)
    m = re.search(r"^\s*Town\s*=\s*['\"](Town\w+)['\"]", t, re.M)
    return m.group(1) if m else "Town05"


class Enc:
    """Pipe frames into ffmpeg as they are rendered.

    The previous path buffered every frame, wrote a VP9 .webm with
    cv2.VideoWriter and then transcoded it to H.264. That is minutes of dead
    time after the last tick, with the page stuck on 100/100 and no video.
    Encoding as we go leaves only the flush, so the file is playable about a
    second after the run ends. CARLA hands us BGRA; we keep the BGR view, which
    is what both the overlay and ffmpeg's bgr24 expect.
    """

    def __init__(self, path, w, h, fps=10):
        import subprocess, imageio_ffmpeg
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path, self.n = path, 0
        self.p = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
             "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def write(self, f):
        try:
            self.p.stdin.write(np.ascontiguousarray(f).tobytes()); self.n += 1
        except Exception:
            pass

    def close(self):
        try:
            self.p.stdin.close(); self.p.wait(timeout=120)
        except Exception:
            try: self.p.kill()
            except Exception: pass
        return os.path.getsize(self.path) if os.path.exists(self.path) else 0


def reset_scenic_state():
    """Clear Scenic's module-level simulation state after a failed job.

    scenic.syntax.veneer keeps currentBehavior / currentSimulation /
    evaluatingRequirement as module globals. A simulation that aborts while a
    behavior is running never clears them, and every later scenario that creates
    an object then dies with "tried to create an object inside a behavior" - one
    bad scenario poisons the worker for everything after it. Observed as seven
    consecutive scenarios failing identically after a single spawn failure.
    """
    try:
        from scenic.syntax import veneer
        veneer.currentBehavior = None
        veneer.currentSimulation = None
        veneer.evaluatingRequirement = False
        return True
    except Exception:
        return False


def run_job(job, models, port):
    jid = job["id"]; ver = job.get("model", "1"); stem = job["scenario"]
    seed = int(job.get("seed", 42)); steps = int(job.get("steps", 120))
    ad, model, proc = models[ver]
    f = paths.scenario_file(stem)
    if not os.path.exists(f):
        raise FileNotFoundError(f"no scenario {stem} in {paths.SCENARIOS}")
    town = town_of(f); xodr = paths.map_file(town)
    pub(jid, phase="compiling", step=0, total=steps, scenario=stem,
        model=ad.display_name, seed=seed, town=town)
    t0 = time.time()
    # The seed decides the SCENE: Scenic samples road, positions and timings
    # from python/numpy RNGs. The curated scenarios were checked at seed 42, so
    # the hazard is where it should be. torch is deliberately not seeded - the
    # drive itself is the model's own, sampled afresh on every run.
    random.seed(seed); np.random.seed(seed)
    sc = scenic.scenarioFromFile(f, mode2D=True, params={
        "map": xodr, "carla_map": town, "port": port, "render": 0, "timestep": 0.1})
    scene, _ = sc.generate(maxIterations=4000)
    pub(jid, phase="simulating", step=0, total=steps)
    # 120s is not enough when two pipelines share the GPU: the server stalls
    # under contention, the client gives up, and the C++ exception aborts the
    # whole worker rather than failing one job. Waiting longer is strictly
    # better than dying - a slow tick costs seconds, a crash costs a restart.
    sim = LiveSimulator(carla_map=town, map_path=xodr, port=port, render=False,
                        timestep=0.1, timeout=int(os.environ.get("CARLA_TIMEOUT", "300")))
    sim._ad, sim._m, sim._p = ad, model, proc
    sim._replan, sim._jid, sim._steps = int(job.get("replan_every", 1)), jid, steps
    sim._seed = seed
    # A recorded per-step control trace re-renders an earlier drive without
    # consulting the model: the commands that were actually applied are replayed.
    # render_clean.py uses this to get overlay-free views of a batch run.
    sim._ctrl = None
    sim._cot_trace = None
    ct = job.get("control_trace")
    if ct and os.path.exists(ct):
        sim._ctrl = json.load(open(ct))["trace"]
    # Captions for a replayed drive come from the same file that recorded it,
    # so the reasoning shown is the reasoning that produced those commands.
    cc = job.get("cot_trace")
    if cc and os.path.exists(cc):
        d = json.load(open(cc))
        sim._cot_trace = d.get("coc") or d.get("cot") or None
    sim._overlay = bool(job.get("overlay", True))
    # LiveSimulator.last is a class attribute set when a simulation is created.
    # Scenic can return without creating one (a rejected scene, a spawn failure)
    # and then this would silently report the PREVIOUS job's trace under this
    # job's id - two different scenarios producing byte-identical drives. Clear
    # it first and refuse to summarise a run that never happened.
    LiveSimulator.last = None
    sim.simulate(scene, maxSteps=steps, maxIterations=1, raiseGuardViolations=False)
    s = LiveSimulator.last
    if s is None:
        raise RuntimeError("simulation produced no result "
                           "(scene rejected or actors failed to spawn)")
    pub(jid, phase="encoding", step=steps, total=steps)
    vids = {}
    for v in OBSERVERS:                      # already encoded; this only flushes
        e = s.enc.get(v)
        if e is not None and e.close():
            vids[v] = f"live/out/{jid}__{v}.mp4"     # URL path; live_server maps it to OUT

    # full per-step trace
    try:
        with open(os.path.join(OUT, f"{jid}__trace.json"), "w") as f:
            json.dump({"job": job, "cot": s._cot, "trace": s.trace}, f)
    except Exception:
        pass
    sp = [x["speed"] for x in s.trace] or [0]
    pub(jid, phase="done", step=steps, total=steps, videos=vids,
        cot=s._cot, wall_s=round(time.time()-t0, 1),
        inference_calls=len(s.inf_times),
        inference_mean_s=round(float(np.mean(s.inf_times)), 2) if s.inf_times else 0,
        speed_mean=round(sum(sp)/len(sp), 2), traj_samples=cfg.NUM_TRAJ_SAMPLES,
        mode=("replay" if sim._ctrl is not None else "live"))


def main():
    port = int(os.environ.get("CARLA_PORT", "3500"))
    want = os.environ.get("MODELS", "1").split(",")
    for d in (JOBS, STATUS, OUT): os.makedirs(d, exist_ok=True)
    models = {}
    for v in want:
        v = v.strip()
        print(f"loading Alpamayo {v} ...", flush=True)
        try:
            ad = get_adapter(v); t = time.time()
            m, p = ad.load_model(device_map="auto")
            models[v] = (ad, m, p)
            print(f"  loaded in {time.time()-t:.1f}s", flush=True)
        except Exception as e:
            # One unavailable model must not take the studio down: serve what
            # loaded, and let the supervisor retry the rest on the next restart.
            print(f"  SKIPPED Alpamayo {v}: {type(e).__name__}: {e}"[:400], flush=True)
    if not models:
        print("no models loaded - exiting so the supervisor retries", flush=True)
        return 1
    # A worker that dies mid-job leaves its status stuck on a running phase, and
    # the page then spins forever. Anything still "in flight" at startup cannot
    # be ours, so fail it explicitly and let the user resubmit.
    for f in os.listdir(STATUS) if os.path.isdir(STATUS) else []:
        if not f.endswith(".json"):
            continue
        fp = os.path.join(STATUS, f)
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if d.get("phase") in ("queued", "compiling", "simulating", "rendering", "encoding"):
            d["phase"] = "error"
            d["error"] = "the render worker restarted while this run was in flight"
            d["updated"] = time.time()
            tmp = fp + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(d, fh)
            os.replace(tmp, fp)
            print(f"  marked orphaned job {f[:-5]} as failed", flush=True)

    open(f"{_Q}/worker_ready", "w").write(str(time.time()))
    print(f"WORKER READY (models={list(models)}, carla port={port}, "
          f"NUM_TRAJ_SAMPLES={cfg.NUM_TRAJ_SAMPLES})", flush=True)
    while True:
        # heartbeat: the page treats a stale file as "warming up", so a worker
        # that died can never keep reporting itself ready.
        beat()
        pend = sorted(f for f in os.listdir(JOBS) if f.endswith(".json"))
        if not pend:
            time.sleep(1); continue
        jf = os.path.join(JOBS, pend[0])
        try: job = json.load(open(jf))
        except Exception: os.remove(jf); continue
        os.remove(jf)
        jid = job.get("id", str(int(time.time())))
        try:
            if job.get("model") not in models:
                pub(jid, phase="error", error=f"model {job.get('model')} not loaded")
                continue
            run_job(job, models, port)
        except Exception as e:
            traceback.print_exc()
            pub(jid, phase="error", error=f"{type(e).__name__}: {e}"[:300])
            # A failed job can leave Scenic's global behavior/simulation state
            # set, which makes every later scenario fail with an unrelated
            # error. Clear it so one bad scenario costs one job, not the queue.
            if reset_scenic_state():
                print("  reset Scenic global state after failure", flush=True)


if __name__ == "__main__":
    main()
