# VLA candidates for driving the ego

Three open driving VLAs are set up to see which can drive the ego closed-loop in CARLA, inside
a world that Scenic owns. Each is a git submodule under `third_party/`, pinned at the commit
checked out here, with its own environment (`scripts/setup_*_env.sh`).

| | AutoVLA | ORION | Alpamayo via Carlamayo |
|---|---|---|---|
| Repo (commit) | `ucla-mobility/AutoVLA` @ ba34eed | `xiaomi-mlab/Orion` @ 657f3cf | `aveeslab/Carlamayo` @ e6372ea |
| Model | Qwen2.5-VL-3B, action tokens | QT-Former + LLM + generative planner | NVIDIA Alpamayo 1 (R1) and 1.5, 10B |
| Checkpoint | 16 GB (`AutoVLA_PDMS_89.ckpt`) | 49 GB (`Orion.pth` 38.5 GB + Q-Former 14 GB) | ~21 GB per version |
| Environment | Python 3.9, torch 2.5.1 | Python 3.8, torch 2.4.1, vendored mmcv build | Python 3.12, torch 2.8 |
| CARLA code in the repo | to check | Bench2Drive agent | plain CARLA Python API |

## Still to check

- **AutoVLA:** the README reports closed-loop CARLA results. Find the agent and route runner
  that produced them.
- **ORION:** how much of the Bench2Drive leaderboard harness its agent needs, and whether it
  can run against a world that Scenic owns.
- **Carlamayo:** runs both Alpamayo versions through `client.connect` / `spawn_actor` /
  `sensor.listen`. Check its camera rig and PID follower against a Scenic-owned world.
