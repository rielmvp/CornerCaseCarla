# How the simulations work

Describes the harness in `cornercase/`, which drives NVIDIA Alpamayo
(1 / R1 and 1.5) through CARLA 0.9.16 scenarios and renders three synchronized
videos per run.

---

## 1. The common core

Both scenario families, the curated corner cases and random spawn, go
through **one** control loop, `DriverCore` in [`cornercase/alpamayo_core.py`](../cornercase/alpamayo_core.py).
Both runners construct the same object, so they cannot drift apart. Only the way
the *world* is set up differs between families.

### Upstream, unmodified

The model, its adapters, the camera rig, the PID follower and the trajectory
visualiser are all upstream [Carlamayo](https://github.com/aveeslab/Carlamayo)
code, imported rather than copied:

```python
import module.config as cfg
from module.inference import extract_trajectory_samples, select_trajectory_by_prev_similarity
from module.pid_controller import OfficialPIDFollower, alpamayo_to_carla_local, local_to_world
from module.visualization import project_trajectory_to_image
```

No upstream file is edited. Every deviation is a subclass or a runtime override in
`cornercase/`, so `git status` in `third_party/Carlamayo` stays clean and each difference from
upstream is greppable in one directory.

Loop mode is upstream's **`closed`** (verified against `closed_loop.py`'s sync
branch), not `live-open`: the model's own predictions move the car, and the next
observation is a consequence of the previous prediction.

### The tick

CARLA runs synchronously at a fixed 0.1 s step (Scenic sets
`synchronous_mode=True`, `fixed_delta_seconds=0.1`). Ordering matters and is
fixed:

```
world.tick()            → advance physics one 0.1 s step
record_state()          → ego pose/velocity into the history buffer
grab camera frames      → blocking queue.Queue() per camera, one frame each
stack frame buffer      → [4 cameras, NUM_FRAMES=4, 1080, 1920, 3]
infer                   → Alpamayo emits trajectory samples + Chain-of-Causation
PID                     → trajectory → steer/throttle/brake
apply_control()         → applied before the next tick
```

An earlier version read cameras *before* ticking, which fed the model a frame the
control had already acted on — an off-by-one that made the car appear to react
late. Camera frames also used a plain dict (last write wins) before the per-camera
blocking queues, which silently desynchronised the four views.

Before the first inference, `warmup()` runs `NUM_HISTORY = 16` ticks so the ego
history buffer holds **real** motion. An earlier version fabricated a zero
history, which told the model the car had been stationary forever.

### Model I/O

| | |
|---|---|
| cameras | 4 (`cross_left_120`, `front_wide_120`, `cross_right_120`, `front_tele_30`), all at z = 2.4 m |
| frames per inference | `NUM_FRAMES = 4` |
| ego history | `NUM_HISTORY = 16` poses |
| trajectory out | 64 waypoints at `dt = 0.1` → **a 6.4 s plan** |
| replan | every frame (`--replan-every 1`) |
| sampling | `temperature 0.6`, `top_p 0.98`, 10 diffusion steps |

**Trajectory samples.** `NUM_TRAJ_SAMPLES = 5`, and only the selected sample is
drawn. These are independent settings and conflating them is a real trap: with 5
samples, `select_trajectory_by_prev_similarity` picks the candidate closest to the
previous frame's plan, and that selection is the **only temporal filter anywhere in
the pipeline**. Setting the count to 1 to get a single-coloured overlay silently
deletes it — measured on an intersection scenario used during development, frame-to-frame plan jitter doubled (4.62 → 9.04 m)
and R1 went from 2 % to 17 % of frames braking. The filter also rejects the ~1 % of
samples where the model omits `<traj_future_start>` and upstream falls back to the
last token position, yielding a malformed plan.

So: **sample five, paint one** (`DRAW_SELECTED_ONLY = True`; `--draw-all-samples`
restores the red-selected + white-rejected spread).

### Control

Upstream's `OfficialPIDFollower` derives target speed from the plan's *reach*:

```python
traj_extent   = max(‖waypoint_xy‖)
target_speed  = clip(10.0 + 0.5 * traj_extent, 10.0, 35.0)   # km/h
```

then hands it to CARLA's `VehiclePIDController`. Two upstream facts drive most of
the observed driving behaviour:

- The longitudinal error is in **km/h** and the output is clipped to [-1, 1], so
  `PID_LON_KP = 0.9` reaches full authority at **1.11 km/h** of error. `K_I = 0.05`
  saturates on its own at 20 km/h, because `_ie = sum(buffer) * dt` over a 10-deep
  buffer at `dt = 0.1` is approximately the error itself.
- `run_step` maps any negative output straight to brake with no deadband, and
  `THROTTLE_MAX = 0.6` while `BRAKE_MAX = 1.0`. The gain therefore sets *both* the
  full-brake threshold (`1/K_P`) and the point where throttle stops being capped
  (`0.6/K_P`).

Together these make the controller bang-bang: because target speed is a function of
plan length, and plan length jitters, small prediction changes become full
throttle/brake cycles. `TunedPIDFollower` (`--speed-mode tuned --lon-kp 0.20`)
rescales the gains, K_I with K_P, and is the recommended setting — see §5.

### Sensors and output

A collision sensor is attached to the ego (upstream `closed_loop` has one; an
earlier version of this harness did not, which meant "the car stopped" could not be
distinguished from "the car hit something"). `collisions`, `first_collision_frame`
and `first_collision_with` are recorded per run.

Three videos per run, H.264, written by piping raw BGR frames straight into ffmpeg:

- **fpv** — the model's own `front_wide_120` camera with the trajectory overlay,
  HUD and Chain-of-Causation text. The overlay geometry is only correct on this
  camera, since that is the one the projection matrix belongs to.
- **bev** — free camera 28 m up, pitch −90°, **not attached** to the ego. It
  follows the ego's position but keeps a fixed heading, so a turn looks like the
  car turning rather than the map rotating.
- **tpv** — chase camera at x = −6.5 m, z = 3.2 m, attached, so it does inherit
  the ego's heading.

Results append incrementally to `outputs/runs/results_{r1,v15}.jsonl`,
one row per run, so an interrupted batch resumes instead of restarting.

---

## 2. Scenario families

### 2a. Curated corner cases: `curated_01` … `curated_12`

Scenic programs in [`scenarios/curated/`](../scenarios/curated/), each written from a text spec
in `specs.json` (see that folder's `NOTES.md` for the construction rules and `RESULTS.md` for
the outcomes). Driven by [`cornercase/alpamayo_runner.py`](../cornercase/alpamayo_runner.py)
for batch runs and by the live worker for the studio. Scenic samples the scene with seed
42 and drives every adversary; the ego's Scenic actions are dropped in `executeActions` and
replaced by Alpamayo's control. The `.scenic` files are never modified at run time; the map
comes from CARLA's own OpenDRIVE files and the ego car can be swapped by the worker.

### 2b. Random spawn — `random_spawn_1`, `random_spawn_2`

The only family with **no Scenic program at all**. Driven by
[`cornercase/random_spawn_runner.py`](../cornercase/random_spawn_runner.py), which builds the
world procedurally:

- Town03, ego placed at a random *clear* spawn point (`clear()` rejects points with
  an actor nearby; falls back to a random point if none qualifies).
- 50 NPC vehicles from the upstream-allowed blueprint filter
  (`is_allowed_npc_vehicle_blueprint`), spawned in batch at other spawn points,
  handed to the TrafficManager on autopilot.
- 50 walkers plus `controller.ai.walker` AI controllers.

TrafficManager tuning matches upstream `closed_loop`:
`set_global_distance_to_leading_vehicle(2.0)` and
`global_percentage_speed_difference(0.0)`. The TM port is **scanned upward** from
`--tm-port` (default 9100) because a fixed port collides when several runs share a
machine — the working port in practice has been 9101.

This family exists as a **control**: it has no adversary and no scripted event, so
it measures how the model drives in ordinary traffic: free driving asks the ego to
stop in ~3 % of frames, scripted scenarios far more often.

One deliberate omission: upstream's `RespawnMonitor` is **not** ported. Respawning
the ego mid-episode is meaningful for a free-driving benchmark but would void the
semantics of a scripted scenario, and the two runners share the loop.

---

## 3. Known deviations from upstream

Kept deliberately, listed so nobody has to rediscover them:

| deviation | why |
|---|---|
| `NUM_TRAJ_SAMPLES = 5` (upstream ships 1) | keeps `select_trajectory_by_prev_similarity` alive; see §1 |
| draw only the selected trajectory | one line is legible; the ensemble is still sampled |
| 2 extra observer cameras (bev, tpv) | upstream renders only the model camera |
| 16 warm-up ticks | real ego history before the first inference |
| collision sensor | distinguishes "stopped" from "crashed" |
| `RespawnMonitor` omitted | would void scripted-scenario semantics |
| `TunedPIDFollower` (opt-in) | rescales the km/h-error gains; see §5 |

---

## 4. Reproducibility — read this before comparing two runs

**Closed-loop runs are not reproducible, and this is not fixable from our side.**

- Alpamayo inference **is** bit-deterministic: same model, same fixed input, three
  runs, `max_abs_diff = 0.000e+00`.
- CARLA's observations are not. Two runs with identical configuration, identical
  seed and `seed_everything()` applied diverge at **t = 3, the first inference**,
  and are unrelated by t = 8.
- Pinning `torch.use_deterministic_algorithms`, cuDNN, TF32 and
  `CUBLAS_WORKSPACE_CONFIG` changes **nothing**: 37 of 40 frames differ either way.
  (`--deterministic` exists and is honest about this.)

Consequences for methodology:

- Replicate spread on mean speed is **~1 % below 30 frames** and **4–27 % at 100
  frames** — divergence compounds with episode length, and the noise is scene- and
  model-specific, not a constant.
- The interesting behaviour (braking, stalling, lane drift) happens *after*
  divergence sets in. **No single pair of videos can rank two controllers.**
- Use ≥3 replicates and report distributions, or restrict metrics to the first
  ~30 frames. Brake *magnitude* is far more stable than brake *frequency*, since a
  whole episode typically contains only one brake event.

---

## 5. Which mode to use

Default for new work:

```bash
python cornercase/alpamayo_runner.py --scenarios <id> --version {1,1.5} \
    --port <carla-port> --steps 100 --replan-every 1 --seed 42 \
    --speed-mode tuned --lon-kp 0.20 --traj-samples 5
```

`--speed-mode` options:

| mode | what sets target speed | verdict |
|---|---|---|
| `carlamayo` | upstream `clip(10 + 0.5·extent, 10, 35)` | the faithful baseline; use to reproduce upstream |
| **`tuned`** | same as `carlamayo`, rescaled longitudinal gains | **recommended** at `--lon-kp 0.20` |
| `plan` | speed the whole 6.4 s plan implies | **do not use** — cold-start deadlock; a stationary car predicts a stationary plan and never moves |
| `planvel` | velocity the plan carries over its first 1.5 s | **do not use** — circular; the plan's opening velocity is the current velocity, so it commands "keep doing what you're doing". Takes 5.1 s to start moving vs 1.0 s for baseline |
| `planlook` | plan velocity at the lookahead point | fixes `planvel`'s circularity but still sits upstream of the gain, so it gets bang-banged anyway |

`--lon-kp 0.20`, measured over 3 replicates on an intersection scenario:

| | R1 `K_P=0.9` | R1 `K_P=0.20` | 1.5 `K_P=0.9` | 1.5 `K_P=0.20` |
|---|---|---|---|---|
| max brake | 0.53 ± 0.06 | **0.13 ± 0.19** | 0.57 ± 0.10 | **0.17 ± 0.05** |
| mean speed | 3.30 ± 0.03 | 3.13 ± 0.16 | 3.08 ± 0.15 | 2.95 ± 0.02 |

Max-brake ranges are non-overlapping on both models (3–4× reduction); mean-speed
ranges **overlap**, so the ~4 % speed difference is not established. Below
`K_P ≈ 0.12` the car under-throttles badly, because throttle stops being capped at
`0.6/K_P` — at `K_P = 0.07` it eases off 8.6 km/h below target and never builds
speed.

Two further flags exist but are **not validated**: `--brake-deadband` (coast rather
than brake when barely over target — inert at low gain, needs testing at `K_P = 0.9`)
and `--steer-guard` (hold straight when the lateral lookahead lands in the last
fifth of the plan and the car is below 1 m/s). The mechanism behind the steer guard
is measured — while stopped, the 4 m lookahead lands in the plan's last fifth on
64 % of frames vs 19 % while moving — but its *benefit* is not.

Always use `--steps 100` (10 s) for comparable episodes. `--steps 64` truncates to
Alpamayo's 6.4 s planning horizon; it exists only to test whether scenario length
past the horizon matters, and produces runs that are not comparable to full ones.
