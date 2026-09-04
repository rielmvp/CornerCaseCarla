# Which VLA drives the ego, and why Alpamayo

Three open driving VLAs were set up and checked for running closed-loop in CARLA: environments
built, checkpoints downloaded. Only one fit.

| | AutoVLA | ORION | Alpamayo via Carlamayo |
|---|---|---|---|
| Repo (commit checked) | `ucla-mobility/AutoVLA` @ ba34eed | `xiaomi-mlab/Orion` @ 657f3cf | `aveeslab/Carlamayo` @ e6372ea |
| Model | Qwen2.5-VL-3B, action tokens | QT-Former + LLM + generative planner | NVIDIA Alpamayo 1 (R1) and 1.5, 10B |
| Checkpoint | 16 GB (`AutoVLA_PDMS_89.ckpt`) | 49 GB (`Orion.pth` 38.5 GB + Q-Former 14 GB) | ~21 GB per version |
| Environment | Python 3.9, torch 2.5.1 | Python 3.8, torch 2.4.1, vendored mmcv build | Python 3.12, torch 2.8 |
| CARLA code in the repo | **none** | Bench2Drive agent | plain CARLA Python API |
| Verdict | dropped | dropped | **used** |

## AutoVLA

The README reports closed-loop results on CARLA, but the code that produced them was never
released. The repo evaluates on nuPlan/NAVSIM, nuScenes and Waymo only: `scripts/`,
`config/eval/` and `tools/eval/` contain no CARLA agent, route runner or evaluation, and the
release plan never lists one. Using it here would have meant rebuilding their harness from the
paper. The result would have been our adapter, not AutoVLA's CARLA setup, so it could not be
reported as AutoVLA's behaviour.

## ORION

ORION ships a real CARLA agent (`team_code/orion_b2d_agent.py`), built for the Bench2Drive
leaderboard. It needs Bench2DriveZoo, the leaderboard harness, a vendored mmcv build and six
1600×900 cameras, and it consumes Bench2Drive XML routes. Every scenario would have to be
converted to a route, and its adversaries would no longer be driven by Scenic.

## Alpamayo through Carlamayo

Carlamayo drives NVIDIA Alpamayo through the plain CARLA Python API: `client.connect`,
`world.spawn_actor`, `sensor.listen`. There is no leaderboard and no route format, so it plugs
into a world that Scenic owns. It also comes with both Alpamayo 1 (R1) and Alpamayo 1.5, which
gives two model generations to compare on the same scenes. It is used as a git submodule,
unmodified: the driving loop in `cornercase/alpamayo_core.py` imports its model adapters,
camera rig, PID follower and trajectory projection (see `how_it_works.md`).
