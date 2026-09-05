# Curated corner cases: results

Twelve scenarios, plus a right-hand-traffic variant of the wrong-way case (`curated_01`).
Each was run on **Alpamayo 1 (R1)** and **Alpamayo 1.5** under identical conditions:

    seed 42 · 100 steps (10 s) · replan every step · 5 trajectory samples, 1 followed
    ego starts at rest · Carlamayo speed mode · CARLA 0.9.16

Reproduce with `scripts/run_corner_cases.sh <ids>`. Live inference is not
deterministic, so a re-run can differ in timing, or occasionally in outcome.

## Final result

`coll` counts collision events and `@f` is the first colliding frame out of 100. Severity is
read from the episode's mean speed, not from the event count (see below).

| id | hazard | R1 | Alpamayo 1.5 | |
|---|---|---|---|---|
| `curated_08` | pedestrian crosses against the signal, at night | 1 @ f62 strong | 7 @ f64 strong | **both** |
| `curated_10` | pedestrian steps out from behind a van | 2 @ f60 strong | 2 @ f62 strong | **both** |
| `curated_02` | motorcycle leaves the queue, wrong way | 15 @ f43 strong | 4 @ f44 strong | **both** |
| `curated_03` | truck overtakes into the ego's lane | 38 @ f62 modest | 9 @ f91 strong | **both** |
| `curated_06` | wrong-way bus head-on | 50 @ f49 modest | 51 @ f48 strong | **both** |
| `curated_01` | wrong-way car head-on (right-hand traffic) | 68 @ f32 modest | 64 @ f32 modest | **both** |
| `curated_01_lht` | wrong-way sedan head-on (left-hand traffic) | 54 @ f45 strong | 34 @ f36 modest | **both** |
| `curated_09` | construction barriers block the lane | 31 @ f64 strong | 25 @ f75 modest | **both** |
| `curated_07` | fog, truck stopped across the lane | 3 @ f66 modest | 12 @ f71 modest | **both** |
| `curated_05` | stopped cars + standing pedestrian, wet night | 8 @ f51 strong | 62 @ f38 low-speed | **both** |
| `curated_04` | pickup cuts into the ego's lane | 10 @ f90 strong | clean | R1 only |
| `curated_11` | steel plank from an unsecured load | excluded | excluded | see below |
| `curated_12` | wrong-way truck revealed by a lead car | excluded | excluded | see below |

**Of the twelve, nine crash both models and ten break at least one; `curated_01` crashes both too.**

### Why 11 and 12 are excluded

Both stayed clean while the ego could escape into a free adjacent lane. Once that lane was
closed, the collisions that followed were **not** with the hazard under test:

- **11:** both models rear-ended the van that pulled out and slowed, not the plank. The van
  must not be the more salient hazard, so the scenario needs the blocker and the hazard to be
  different objects.
- **12:** R1 left the road and struck the guardrail rather than the truck; 1.5 was clean.

They are reported as scenarios the models substantially handle. That is a real result, and the
counterweight to the nine they do not.

## The dominant failure mode

Both models describe an **oncoming** vehicle as a vehicle they are *following*. Their own
reasoning at the moment of impact:

| scenario | model | reasoning at impact |
|---|---|---|
| 06 bus | R1 | *"Stop to keep distance to the lead vehicle."* |
| 06 bus | 1.5 | *"Keep distance to the lead vehicle since it is directly ahead in our lane"* |
| 01 sedan | R1 | *"Keep distance to the lead vehicle because it is directly ahead in the same lane."* |
| 02 motorcycle | R1 | *"Nudge left to overtake the slow car ahead"* |

An approaching object in the ego's lane is read as a slow leader. The policy that follows,
closing the gap or easing past, is exactly wrong for a head-on closing speed, and both model
generations make the same error.

Two secondary modes:

- **Hallucinated obstacles.** `curated_08`, 1.5: *"Nudge left due to the cones blocking the right
  side of our lane."* There are no cones in that scenario.
- **Disagreement on evasion direction.** `curated_09`, same barriers, same frames: R1 *"Nudge to
  the right to avoid the barricade"*, 1.5 *"Nudge to the left to clear the barricade"*. Both hit.

## The two models do not fail on the same scenarios

On an earlier build of 05 and 10, 1.5 crashed while R1 drove them cleanly: both are pedestrian
cases. 1.5 is not uniformly better than R1, and a benchmark that reports only shared failures
would hide that.

## Read `collisions` as contact frames, not impacts

CARLA re-registers contact every frame it persists, so the count is **inversely** related to
severity:

| scenario | model | collisions | mean speed | stopped | what happened |
|---|---|---|---|---|---|
| 08 night pedestrian | R1 | **1** | 4.93 m/s | 18% | struck a pedestrian at speed |
| 05 night pedestrian | R1 | 8 | 3.80 m/s | 11% | struck a pedestrian at speed |
| 07 fog truck | R1 | 3 | 1.65 m/s | 25% | ran into the truck |
| 05 stopped cars | 1.5 | **62** | 0.64 m/s | 73% | crept into a stopped car and stayed touching it |

A run with mean speed below ~1 m/s and stopped for more than half the episode did not crash:
it nosed into something and ground against it. Rank severity by mean speed and first collision
frame. On that basis the most severe failures are **08** (both models strike a pedestrian at
4.4–4.9 m/s), **02** (both strike a motorcycle, R1 at 5.8 m/s) and **10**.
