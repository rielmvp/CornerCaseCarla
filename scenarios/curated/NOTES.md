# How the curated corner cases are built

Each scenario starts from a text spec in `specs.json`: a plain-language description of the
hazard plus construction notes. It is then written in Scenic 3 by hand, using patterns that
were verified in CARLA. Scenic samples the scene and drives every other actor; in the actual
runs Alpamayo takes over the ego, so the ego's own Scenic behaviour only matters in previews.

## Rules every scenario follows

- **Pick the road explicitly.** `Uniform(*network.lanes)` over the whole map picks ramps and
  short connectors, and the episode dies in a few steps. Every scenario filters lane sections
  for the geometry it needs, for example a straight, undivided two-lane road:

      straightness = math.dist(pts[0], pts[-1]) / laneSec.centerline.length
      if straightness > 0.97 and len(laneSec.lane.road.lanes) == 2 \
         and laneSec._laneToLeft is not None \
         and laneSec._laneToLeft.isForward != laneSec.isForward: ...

  Straight two-lane two-way sections per town: Town01 34, Town02 18, Town03 12, Town04 12,
  Town05 0. Town03 has none longer than 80 m.
- **Spawn the hazard 20–40 m ahead** and trigger it on the ego's distance, not on time. The
  conflict has to happen inside the 10 s episode, and after the model's warm-up frames.
- **No `terminate after N seconds`.** The runner ends the episode after a fixed number of
  steps, and a time-based terminate is counted in steps, which kills the run at ~1.5 s.

## Left-hand traffic

Seven source situations are from left-hand-traffic countries, but CARLA ships right-hand maps
only. Left-hand traffic is built explicitly: anchor in the map's forward lane, then put the
ego one lane width to its left, still facing forward:

    egoBase    = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection
    egoSpawnPt = new OrientedPoint left of egoBase by 3.5, facing egoBase.heading

The centre line is then on the ego's right and the kerb on its left. From there:

- anything in the **ego's own lane** is `left of <basePt> by 3.5`;
- anything in the **lane to the ego's right** (oncoming traffic) sits on `<basePt>`;
- a behaviour that aims at the ego's lane centreline must use
  `egoLaneSec._laneToLeft.centerline`. Aiming at `egoLaneSec.centerline` targets the other
  lane: an overtaking truck built that way drove across the ego's lane onto the pavement.
- the preview ego uses plain throttle: `FollowLaneBehavior` would steer it round to the lane's
  nominal direction.

## Wrong-way and oncoming actors

Never `FollowLaneBehavior(is_oppositeTraffic=True)`. The flag only flips the sign of the
lateral controller's cross-track error, so the actor hunts and visibly weaves. Wrong-way
actors drive plain throttle with `SetSteerAction(0.0)` on sections filtered to straightness
above 0.97.

## Checking a scene before any model drives it

`scripts/check_scenario.sh <id>` runs two checks:

1. **Geometric pre-filter** (`cornercase/scenario_validate.py`): samples the scene over several
   seeds and reports the ego→hazard gap and whether the hazard is ahead. It catches missing,
   behind-the-ego and 200-m-away hazards without a simulator.
2. **CARLA preview** (`cornercase/scenario_preview.py`): runs the scenario with its own scripted
   behaviours, writes a contact sheet, and prints every actor's longitudinal and lateral offset
   in the ego's frame each tick. A small contact sheet cannot show whether a car actually
   crossed the centre line; the trace can.

Problems these checks caught:

- a pedestrian 1.4 m from a stopped car's centre is inside its body, so CARLA refuses the spawn;
- a truck overshot 1.8 m past the ego's lane, leaving only a glancing overlap;
- a scenario sampled on a town with no qualifying road came out empty.

The preview and the real run must seed the same way (`random` and `numpy`, seed 42, the same
`maxIterations`). Otherwise the preview checks a different scene from the one that runs.
