"""Is the CARLA server rendering on the GPU? Spawn a car with a camera, tick, save frames.

  python scripts/carla_smoke_test.py --port 2000 --out logs/smoke [--frames 40]

Runs in synchronous mode at a fixed 0.1 s step, the setting every later runner uses,
so a pass here means the server can actually be driven tick by tick. On the GPU the
RPC port opens in under a minute and 40 ticks at 1920x1080 take about 20 s; on a
software rasterizer (lavapipe) the port effectively never opens.

World settings are restored on exit so a shared server is left as it was found.
"""
import argparse, os, queue, time

import carla


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--map", default=None, help="load this town first, e.g. Town03")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--out", default="logs/smoke")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    client = carla.Client(a.host, a.port)
    client.set_timeout(120.0)                 # the first map load can take a while
    world = client.load_world(a.map) if a.map else client.get_world()
    original = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.1
    world.apply_settings(settings)

    actors = []
    try:
        lib = world.get_blueprint_library()
        car = world.spawn_actor(lib.find("vehicle.lincoln.mkz_2017"),
                                world.get_map().get_spawn_points()[0])
        actors.append(car)
        cam_bp = lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", str(a.width))
        cam_bp.set_attribute("image_size_y", str(a.height))
        cam = world.spawn_actor(cam_bp, carla.Transform(carla.Location(x=-6.0, z=2.5),
                                                        carla.Rotation(pitch=-10.0)),
                                attach_to=car)
        actors.append(cam)
        frames = queue.Queue()
        cam.listen(frames.put)

        t0 = time.time()
        for _ in range(a.frames):
            world.tick()
            img = frames.get(timeout=30.0)
            img.save_to_disk(os.path.join(a.out, f"frame_{img.frame:06d}.png"))
        dt = time.time() - t0
        print(f"{a.frames} sync ticks in {dt:.1f} s ({a.frames / dt:.1f} fps) -> {a.out}")
    finally:
        for x in reversed(actors):
            if x.type_id.startswith("sensor."):
                x.stop()
            x.destroy()
        world.apply_settings(original)


if __name__ == "__main__":
    main()
