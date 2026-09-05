"""Preview one corner-case scenario in CARLA and emit a contact sheet for visual judging.

Runs the scenario with its OWN scripted behaviors (no Alpamayo) so we can tell
whether the *scene* was built correctly -- is the wrong-way car actually coming
head-on, is the pedestrian where the spec puts it -- before spending model time on it.

Captures a bird's-eye and a chase view, samples N frames evenly, and writes a
labelled strip JPEG. One scenario per process (Scenic keeps global state in
scenic.core.veneer that is not safe to reuse across simulate() calls).
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
import numpy as np
import carla
import scenic
from scenic.simulators.carla.simulator import CarlaSimulator, CarlaSimulation

W, H = 640, 360
BEV = carla.Transform(carla.Location(x=0, z=32.0), carla.Rotation(pitch=-90.0))
TPV = carla.Transform(carla.Location(x=-7.0, z=3.4), carla.Rotation(pitch=-14.0))


class PreviewSimulation(CarlaSimulation):
    def setup(self):
        super().setup()
        self.shots = {"bev": [], "tpv": []}
        self.trace = []
        self._cams = []
        try:
            ego = self.objects[0].carlaActor
        except Exception:
            return
        bl = self.world.get_blueprint_library()
        for name, tf in (("bev", BEV), ("tpv", TPV)):
            bp = bl.find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", str(W))
            bp.set_attribute("image_size_y", str(H))
            bp.set_attribute("fov", "90")
            cam = self.world.spawn_actor(bp, tf, attach_to=ego)
            buf = self.shots[name]
            cam.listen(lambda img, b=buf: b.append(
                np.frombuffer(img.raw_data, dtype=np.uint8).reshape((H, W, 4))[:, :, :3].copy()))
            self._cams.append(cam)

    def step(self):
        # Numeric trace: longitudinal / lateral offset of every non-ego object in
        # the EGO's frame. Squinting at a 640x360 contact sheet cannot tell whether
        # a wrong-way actor actually crossed the centre line; this can.
        r = super().step()
        try:
            import math as _m
            objs = self.objects
            e = objs[0]
            ex, ey = e.position[0], e.position[1]
            fx, fy = _m.cos(e.heading + _m.pi / 2), _m.sin(e.heading + _m.pi / 2)
            rx, ry = fy, -fx
            row = []
            for o in objs[1:]:
                dx, dy = o.position[0] - ex, o.position[1] - ey
                row.append((dx * fx + dy * fy, dx * rx + dy * ry))
            self.trace.append(row)
        except Exception:
            pass
        return r

    def destroy(self):
        for c in getattr(self, '_cams', []):
            try:
                c.stop(); c.destroy()
            except Exception:
                pass
        self._cams = []
        return super().destroy()


class PreviewSimulator(CarlaSimulator):
    def createSimulation(self, scene, **kw):
        kw.pop("timestep", None)
        return PreviewSimulation(scene, self.client, self.tm, self.render,
                                 self.record, self.scenario_number,
                                 timestep=self.timestep, **kw)


def town_of(path):
    import re
    t = open(path).read()
    m = re.search(r"param\s+carla_map\s*=\s*['\"](Town\w+)['\"]", t)
    if m:
        return m.group(1)
    m = re.search(r"^\s*Town\s*=\s*['\"](Town\w+)['\"]", t, re.M)
    return m.group(1) if m else "Town05"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenic_file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=3500)
    ap.add_argument("--steps", type=int, default=80)
    ap.add_argument("--maps", default=paths.MAPS)
    ap.add_argument("--panels", type=int, default=5)
    # Seed exactly as alpamayo_runner.seed_everything() does. Without this the
    # preview samples a DIFFERENT scene than the real run, so a preview can pass
    # while the real run fails to spawn (observed on curated_05).
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    import random as _random
    _random.seed(a.seed)
    np.random.seed(a.seed)
    town = town_of(a.scenic_file)
    xodr = os.path.join(a.maps, town + ".xodr")
    sc = scenic.scenarioFromFile(a.scenic_file, mode2D=True, params={
        "map": xodr, "carla_map": town, "port": a.port, "render": 0, "timestep": 0.1})
    scene, _ = sc.generate(maxIterations=4000)
    print(f"scene objects={len(scene.objects)} town={town}", flush=True)

    sim = PreviewSimulator(carla_map=town, map_path=xodr, port=a.port,
                           render=False, timestep=0.1, timeout=120)
    run = sim.simulate(scene, maxSteps=a.steps, maxIterations=1, raiseGuardViolations=False)
    if run is None:
        print("REJECTED: scenario requirement violated during simulation", flush=True)
        sys.exit(2)
    trace = getattr(run, "trace", None)
    if trace is None:
        for attr in ("simulation", "_simulation"):
            s_ = getattr(run, attr, None)
            if s_ is not None and hasattr(s_, "trace"):
                trace = s_.trace
                break
    if trace:
        names = [type(o).__name__ for o in scene.objects[1:]]
        print("TRACE (lon,lat in ego frame; lat>0 = ego's right):", flush=True)
        print("  step | " + " | ".join(f"{n[:5]:>13s}" for n in names), flush=True)
        for i in range(0, len(trace), max(1, len(trace) // 12)):
            print(f"  {i:4d} | " + " | ".join(f"{lon:6.1f},{lat:6.1f}" for lon, lat in trace[i]), flush=True)

    shots = run.shots if hasattr(run, "shots") else None
    if shots is None:
        for attr in ("simulation", "_simulation"):
            s = getattr(run, attr, None)
            if s is not None and hasattr(s, "shots"):
                shots = s.shots
                break
    if not shots or not shots.get("tpv"):
        print("NO FRAMES captured", flush=True)
        sys.exit(3)

    from PIL import Image, ImageDraw
    n = min(a.panels, len(shots["tpv"]))
    idx = [int(i * (len(shots["tpv"]) - 1) / max(1, n - 1)) for i in range(n)]
    rows = []
    for key in ("bev", "tpv"):
        buf = shots.get(key) or []
        if not buf:
            continue
        row = Image.new("RGB", (n * W, H), (15, 15, 15))
        for c, i in enumerate(idx):
            i = min(i, len(buf) - 1)
            im = Image.fromarray(buf[i][:, :, ::-1])  # BGR -> RGB
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 132, 22], fill=(0, 0, 0))
            d.text((5, 6), f"{key} f{i}", fill=(255, 255, 0))
            row.paste(im, (c * W, 0))
        rows.append(row)
    sheet = Image.new("RGB", (n * W, H * len(rows)), (15, 15, 15))
    for r, row in enumerate(rows):
        sheet.paste(row, (0, r * H))
    sheet.save(a.out, quality=88)
    print(f"WROTE {a.out}  frames={len(shots['tpv'])}", flush=True)


if __name__ == "__main__":
    main()
