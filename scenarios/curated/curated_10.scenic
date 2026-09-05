description = "A pedestrian steps out from behind a parked van into the ego's left-hand lane."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town02.xodr')
param carla_map = 'Town02'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'ClearNoon'

import math

laneSecs = []
for lane in network.lanes:
    for laneSec in lane.sections:
        pts = laneSec.centerline.points
        if len(pts) < 2 or laneSec.centerline.length <= 120:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        if straightness > 0.97 and len(laneSec.lane.road.lanes) == 2 \
           and laneSec._laneToLeft is not None \
           and laneSec._laneToLeft.isForward != laneSec.isForward:
            laneSecs.append(laneSec)
egoLaneSec = Uniform(*laneSecs)

# LEFT-HAND TRAFFIC (the source clip is from a left-hand-drive country).
# Anchor in the map's forward lane, then put the ego one lane width to its left so
# it drives on the left-hand side: centre line on the ego's right, kerb on its
# left. Anything in the EGO'S OWN lane is `left of <basePt> by 3.5`; anything in
# the lane to the EGO'S RIGHT sits on <basePt> with no offset.
egoBase = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection
egoSpawnPt = new OrientedPoint left of egoBase by 3.5, facing egoBase.heading

# The ego sits in the map's OPPOSING lane, so FollowLaneBehavior would turn it
# around. Alpamayo replaces this in the real runs; the preview only needs it to roll.
behavior EgoBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

ego = new Car at egoSpawnPt, facing egoSpawnPt.heading,
    with blueprint MODEL,
    with behavior EgoBehavior(0.45)

# Round 1 and 2 both left this scenario clean on both models: a pedestrian in
# clear daylight with 13 m of open sightline is an easy case, and R1 reported
# "no critical agent needs attention". The source clip's hazard is OCCLUSION -- the walker
# is hidden behind a parked van until the ego is almost level with it.
behavior StoppedBehavior():
    while True:
        take SetBrakeAction(1.0)

# The near-side kerb for a left-hand-lane ego is on the ego's LEFT.
vanDist = Range(18, 22)
vanBase = new OrientedPoint following roadDirection from egoBase for vanDist
vanLane = new OrientedPoint left of vanBase by 3.5
vanPt = new OrientedPoint left of vanLane by 2.6

# 4.5 m clear of the van's centre: a Sprinter is ~5.5 m long, and at 3.0 m the
# walker starts against its rear quarter and is dragged down to 0.67 m/s.
pedBase = new OrientedPoint following roadDirection from egoBase for vanDist + 4.5
pedLane = new OrientedPoint left of pedBase by 3.5
pedPt = new OrientedPoint left of pedLane by 4.0

# Trigger on the ego's distance with a bounded timeout: the runner ticks 16 warmup
# frames before frame 0, and a pure distance wait deadlocks if the ego stops short.
# Trigger on TIME-TO-ARRIVAL, not distance. A fixed distance cannot work here:
# the ego's speed varies run to run (Alpamayo drives it, not the preview throttle),
# so 13 m let the walker finish crossing before the ego arrived ("the road ahead is
# clear") while 8 m let the ego pass in front of it. Starting the walk a fixed
# 1.6 s of travel ahead of the ego is speed-invariant, and the walker needs about
# 1.3 s to reach the lane centre from the kerb.
#
# Measure the ego's time to the CROSSING POINT, not to the walker: a pedestrian
# waiting 4 m off the carriageway never gets closer than 4 m in a straight-line
# distance, so `distance from self to ego` bottoms out and fires only once the ego
# is already level with it.
behavior CrossBehavior(speed, heading, ttc, xpoint):
    # Bounded only so a stalled ego cannot deadlock the behavior; the cap must
    # out-last the episode or it, not the trigger, decides when the walk starts.
    for i in range(120):
        v = ego.speed
        if v > 0.5 and (distance from ego to xpoint) / v < ttc:
            break
        wait
    while True:
        take SetWalkingDirectionAction(heading), SetWalkingSpeedAction(speed)

van = new Car at vanPt, facing vanLane.heading,
    with blueprint 'vehicle.mercedes.sprinter',
    with regionContainedIn None,
    with behavior StoppedBehavior()

walker = new Pedestrian at pedPt,
    facing pedLane.heading - 90 deg,
    with regionContainedIn None,
    with behavior CrossBehavior(3.0, pedLane.heading - 90 deg, 3.0, pedLane)
