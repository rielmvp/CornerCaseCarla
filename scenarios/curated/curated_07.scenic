description = "Night fog reveals a truck stopped broadside across the ego's left-hand lane."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town01.xodr')
param carla_map = 'Town01'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = {'cloudiness': 100, 'precipitation': 0, 'sun_altitude_angle': -20, 'fog_density': 100, 'fog_distance': 3, 'wetness': 60}

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

behavior StoppedBehavior():
    while True:
        take SetBrakeAction(1.0)

# The ego sits in the map's OPPOSING lane, so FollowLaneBehavior would turn it
# around. Alpamayo replaces this in the real runs; the preview only needs it to roll.
behavior EgoBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

ego = new Car at egoSpawnPt, facing egoSpawnPt.heading,
    with blueprint MODEL,
    with behavior EgoBehavior(0.45)

# Broadside across a 3.5 m lane a truck is ~9 m long, so it must be allowed to
# overhang the carriageway - blocking it completely is the point.
obsBase = new OrientedPoint following roadDirection from egoBase for Range(15, 18)
obsPt = new OrientedPoint left of obsBase by 3.5
truck = new Truck at obsPt,
    with heading obsBase.heading + 75 deg,
    with blueprint 'vehicle.carlamotors.carlacola',
    with regionContainedIn None,
    with behavior StoppedBehavior()

# Stopped traffic in the lane to the EGO'S RIGHT: the source clip is a queue of
# vehicles halted behind the jack-knifed truck, and without it the ego can simply
# steer around the obstruction.
def rightLanePt(d):
    b = new OrientedPoint following roadDirection from egoBase for d
    return new OrientedPoint at b, facing b.heading + 180 deg

blockA = new Car at rightLanePt(22), facing rightLanePt(22).heading, with behavior StoppedBehavior()
blockB = new Car at rightLanePt(30), facing rightLanePt(30).heading, with behavior StoppedBehavior()
