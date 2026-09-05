description = "Ego in the left-hand lane meets a wrong-way sedan head-on in its own lane."
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

# Never FollowLaneBehavior for an opposing actor: is_oppositeTraffic only flips the
# lateral PID's error sign while the behavior still walks the centreline forwards,
# so the actor hunts and visibly weaves. Plain throttle, steer pinned to zero.
behavior WrongWayBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

# The ego sits in the map's OPPOSING lane, so FollowLaneBehavior would turn it
# around. Alpamayo replaces this in the real runs; the preview only needs it to roll.
behavior EgoBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

ego = new Car at egoSpawnPt, facing egoSpawnPt.heading,
    with blueprint MODEL,
    with behavior EgoBehavior(0.45)

advBase = new OrientedPoint following roadDirection from egoBase for Range(28, 34)
advPt = new OrientedPoint left of advBase by 3.5, facing advBase.heading + 180 deg
advCar = new Car at advPt, facing advPt.heading,
    with blueprint MODEL,
    with behavior WrongWayBehavior(Range(0.80, 0.90))

# Oncoming traffic in the lane to the EGO'S RIGHT. Without it the ego simply
# nudges right into an empty lane and the head-on never develops - R1 did exactly
# that ("Nudge to the right to increase clearance from the oncoming vehicle").
# The source clip has traffic there too: the wrong-way vehicle is overtaking it.
def rightLanePt(d):
    b = new OrientedPoint following roadDirection from egoBase for d
    return new OrientedPoint at b, facing b.heading + 180 deg

behavior SlowOncomingBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

blockA = new Car at rightLanePt(20), facing rightLanePt(20).heading,
    with behavior SlowOncomingBehavior(0.22)
blockB = new Car at rightLanePt(34), facing rightLanePt(34).heading,
    with behavior SlowOncomingBehavior(0.22)
blockC = new Car at rightLanePt(48), facing rightLanePt(48).heading,
    with behavior SlowOncomingBehavior(0.22)
