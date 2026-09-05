description = "Just past a signalised junction a motorcycle pulls out of the queue in the right-hand lane and rides the wrong way into the ego's left-hand lane."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town01.xodr')
param carla_map = 'Town01'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'ClearNoon'

import math

# Straight two-lane exit from a SIGNALISED junction, long enough to hold the whole
# queue past the intersection. Town01's signalised exits run to 224 m; Town03's
# 4-way exits are only 42-52 m and push the rear of the queue into the next junction.
laneSecs = []
for intersection in network.intersections:
    if not intersection.isSignalized:
        continue
    for lane in intersection.outgoingLanes:
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

# LEFT-HAND TRAFFIC: ego one lane width left of the map's forward lane.
egoBase = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection
egoSpawnPt = new OrientedPoint left of egoBase by 3.5, facing egoBase.heading

behavior EgoBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

behavior StoppedBehavior():
    while True:
        take SetBrakeAction(1.0)

# Scripted steer pulse, never LaneChangeBehavior/is_oppositeTraffic (that only
# flips the lateral PID's error sign and the bike weaves). The ego's lane is on the
# motorcycle's left-or-right depending on which lane it starts in - verified
# against the trace.
behavior PullOutBehavior(throttle, hold, steer):
    for i in range(hold):
        take SetThrottleAction(throttle), SetSteerAction(0.0)
    for i in range(15):
        take SetThrottleAction(throttle), SetSteerAction(steer)
    for i in range(14):
        take SetThrottleAction(throttle), SetSteerAction(-steer)
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

ego = new Car at egoSpawnPt, facing egoSpawnPt.heading,
    with blueprint MODEL, with behavior EgoBehavior(0.45)

def rightLanePt(d):
    # the lane to the EGO'S RIGHT is the map's forward lane: no lateral offset
    b = new OrientedPoint following roadDirection from egoBase for d
    return new OrientedPoint at b, facing b.heading + 180 deg

motoPt = rightLanePt(26)
advMotorcycle = new Motorcycle at motoPt, facing motoPt.heading,
    with blueprint 'vehicle.yamaha.yzf',
    with behavior PullOutBehavior(0.45, 5, 0.55)

q1 = new Car at rightLanePt(33), facing rightLanePt(33).heading, with behavior StoppedBehavior()
q2 = new Car at rightLanePt(40), facing rightLanePt(40).heading, with behavior StoppedBehavior()
q3 = new Car at rightLanePt(47), facing rightLanePt(47).heading, with behavior StoppedBehavior()
q4 = new Car at rightLanePt(54), facing rightLanePt(54).heading, with behavior StoppedBehavior()
q5 = new Car at rightLanePt(61), facing rightLanePt(61).heading, with behavior StoppedBehavior()
q6 = new Car at rightLanePt(68), facing rightLanePt(68).heading, with behavior StoppedBehavior()
