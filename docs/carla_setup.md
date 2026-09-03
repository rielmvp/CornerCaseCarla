# CARLA + Scenic setup

Everything in this repo runs against a **CARLA 0.9.16** server rendering off-screen on an
NVIDIA GPU, driven from Python through the CARLA client and **Scenic 3.1**.

## 1. CARLA server

0.9.16 is the only version still on an official mirror: the 0.9.15 links (on
`carla-releases.b-cdn.net`) return 403/404, and `downloads.carlasim.com` serves 0.9.16 only.

```bash
mkdir -p carla/CARLA_0.9.16
curl -L https://downloads.carlasim.com/Linux/CARLA_0.9.16.tar.gz | tar -xz -C carla/CARLA_0.9.16
```

The release includes Town01–05 and Town10HD, plus their OpenDRIVE road networks under
`CarlaUE4/Content/Carla/Maps/OpenDrive/*.xodr`. Scenic reads those `.xodr` files directly, so
no separate map download is needed.

## 2. Python environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/sim.txt
```

Python 3.10 and 3.12 both work. Keep `shapely` below 2.1: Scenic 3.1.0a1 allows 2.1, but
scene sampling then fails inside `scenic/core/regions.py`.

## 3. GPU rendering (Vulkan)

CARLA renders through Vulkan. If CUDA works but the server never opens its RPC port and
`vulkaninfo` fails, the container image is probably missing the Vulkan loader and libglvnd's
EGL dispatch library. NVIDIA's Vulkan driver loads `libEGL.so.1` while it initialises; when
that file is absent, initialisation fails before any GPU is touched. To confirm, run
`strace -f -e openat vulkaninfo` and look for `libEGL.so.1 ... ENOENT`.

Fix it without root:

```bash
scripts/setup_vulkan_userspace.sh          # apt-get download + dpkg-deb -x into vendor/glvnd
. vendor/glvnd/env.sh && vulkaninfo --summary
```

`scripts/start_carla.sh` sources `vendor/glvnd/env.sh` automatically when it exists. The
permanent fix belongs in the image: `apt-get install -y libegl1 libgles2 libglvnd0 libvulkan1`.

## 4. Start a server and check it

```bash
scripts/start_carla.sh 0 2000              # graphics adapter 0, RPC port 2000
python scripts/carla_smoke_test.py --port 2000 --map Town03 --out logs/smoke
```

- `-graphicsadapter` numbers Vulkan devices, which do not always match `nvidia-smi`
  indices. After launch, check `nvidia-smi` to see which GPU the server is actually on.
- A server binds `port`, `port+1` and `port+2`. Space multiple servers at least 3 apart.
- On the GPU, the RPC port opens in under a minute and the smoke test's 40 ticks at
  1920×1080 take about 20 s. On a software rasterizer the port effectively never opens.
- Servers are started with `setsid`, so they keep running after the shell exits. Stop
  one by the PID the script prints.
