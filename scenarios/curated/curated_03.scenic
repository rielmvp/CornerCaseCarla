description = "A truck overtakes slow oncoming traffic and crosses head-on into the ego's left-hand lane on a two-lane road."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town01.xodr')
param carla_map = 'Town01'
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

egoBase = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection
egoSpawnPt = new OrientedPoint left of egoBase by 3.5, facing egoBase.heading

behavior EgoBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

# Oncoming traffic in the lane to the EGO'S RIGHT faces against that lane's map
# direction, so FollowLaneBehavior would turn these cars around. Plain throttle.
# A bare throttle of 0.16 does NOT move a CARLA vehicle from rest -- it sits below
# static friction and the car creeps ~0.2 m in 80 ticks, turning "slow oncoming
# traffic" into a parked line. Close the loop on speed instead.
behavior SlowOncomingBehavior(target):
    while True:
        if self.speed < target:
            take SetThrottleAction(0.5), SetBrakeAction(0.0), SetSteerAction(0.0)
        else:
            take SetThrottleAction(0.0), SetBrakeAction(0.0), SetSteerAction(0.0)

# The overtake is triggered by the EGO'S DISTANCE. Fixed tick counts are unusable:
# a CARLA Truck's steer response is strongly nonlinear with speed, and the runner's
# 16-tick warmup eats part of any scripted phase before frame 0. The crossing is
# closed-loop on the EGO'S lane centreline - which, because the ego is in the map's
# opposing lane, is egoLaneSec._laneToLeft.centerline - so the truck stops crossing
# the moment it reaches that lane instead of running onto the pavement.
EGO_LANE = egoLaneSec._laneToLeft

behavior OvertakeBehavior(throttle, trigger, steer):
    for i in range(60):
        if (distance from self to ego) < trigger:
            break
        take SetThrottleAction(throttle), SetSteerAction(0.0)
    # One PD controller for the whole crossing. A pull-out phase followed by a
    # fixed counter-steer cannot work here: by the time the truck reaches the ego's
    # lane it carries enough yaw rate to travel another 4 m sideways, which put it
    # up on the pavement (the artefact reported in an earlier build). The derivative term
    # starts unwinding the crossing while the truck is still ~2.8 m out.
    prev = None
    while True:
        off = EGO_LANE.centerline.signedDistanceTo(self.position)
        rate = 0.0 if prev is None else (off - prev)
        prev = off
        cmd = max(-0.6, min(0.6, 1.2 * off + 12.0 * rate))
        take SetThrottleAction(throttle), SetBrakeAction(0.0), SetSteerAction(cmd)

ego = new Car at egoSpawnPt, facing egoSpawnPt.heading,
    with blueprint MODEL, with behavior EgoBehavior(0.45)

def rightLanePt(d):
    b = new OrientedPoint following roadDirection from egoBase for d
    return new OrientedPoint at b, facing b.heading + 180 deg

c1 = new Car at rightLanePt(30), facing rightLanePt(30).heading, with behavior SlowOncomingBehavior(3.0)
c2 = new Car at rightLanePt(38), facing rightLanePt(38).heading, with behavior SlowOncomingBehavior(3.0)
c3 = new Car at rightLanePt(46), facing rightLanePt(46).heading, with behavior SlowOncomingBehavior(3.0)

c4 = new Car at rightLanePt(64), facing rightLanePt(64).heading, with behavior SlowOncomingBehavior(3.0)
c5 = new Car at rightLanePt(72), facing rightLanePt(72).heading, with behavior SlowOncomingBehavior(3.0)

truckPt = rightLanePt(56)
truck = new Truck at truckPt, facing truckPt.heading,
    with blueprint 'vehicle.carlamotors.carlacola',
    with behavior OvertakeBehavior(0.6, 44, 0.62)
