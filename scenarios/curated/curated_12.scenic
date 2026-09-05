description = "A truck comes head-on the wrong way down the ego's lane of a divided highway, revealed only when the car the ego is following swerves clear."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town04.xodr')
param carla_map = 'Town04'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'CloudyNoon'

import math

# The source clip is an Indian divided highway: left-hand traffic, ego in the left-hand
# running lane with a same-direction lane to its right, a dark SUV ahead of it,
# and a loaded truck coming straight at the camera down the ego's own lane.
# Town04's multi-lane sections are gently curved even at straightness 0.97, so
# require 0.9999 -- that still leaves 24 sections, the longest 237 m.
laneSecs = []
for lane in network.lanes:
    for laneSec in lane.sections:
        pts = laneSec.centerline.points
        if len(pts) < 2 or laneSec.centerline.length <= 120:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        if straightness > 0.9999 \
           and laneSec._laneToRight is not None \
           and laneSec._laneToRight.isForward == laneSec.isForward:
            laneSecs.append(laneSec)
egoLaneSec = Uniform(*laneSecs)
egoSpawnPt = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection

RIGHT_LANE = egoLaneSec._laneToRight

behavior EgoBehavior(speed):
    do FollowLaneBehavior(target_speed=speed)

ego = new Car at egoSpawnPt, with blueprint MODEL, with behavior EgoBehavior(10)

# Anchor on the SECTION's own centreline: `following roadDirection ... for d`
# integrates the road's direction field and veers where it crosses into another
# road, which throws distant objects tens of metres off the ego's axis.
def lanePt(d, lat):
    b = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6 + d), facing roadDirection
    return new OrientedPoint left of b by lat, facing b.heading

# Never FollowLaneBehavior for an opposing actor: is_oppositeTraffic only flips the
# lateral PID's error sign while the behavior still walks the centreline forwards,
# so the actor hunts and visibly weaves. Plain throttle, steer pinned to zero.
behavior WrongWayBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetBrakeAction(0.0), SetSteerAction(0.0)

truckPt = lanePt(85, 0.0)
truck = new Truck at truckPt, facing truckPt.heading + 180 deg,
    with blueprint 'vehicle.carlamotors.carlacola',
    with regionContainedIn None,
    with behavior WrongWayBehavior(0.5)

# The lead car is what makes this different from a bare head-on: the ego is
# following it, so the truck is masked until the lead swerves clear and hands the
# ego a fully developed head-on at short range. The swerve is closed-loop on the
# right-hand lane's centreline with a derivative term -- a fixed-tick steer pulse
# leaves yaw rate unresolved and carries the car several metres too far.
behavior LeadCarBehavior(target, reveal):
    prev = None
    while True:
        if (distance from self to truck) < reveal:
            break
        if self.speed < target:
            take SetThrottleAction(0.6), SetBrakeAction(0.0), SetSteerAction(0.0)
        else:
            take SetThrottleAction(0.0), SetBrakeAction(0.0), SetSteerAction(0.0)
    while True:
        off = RIGHT_LANE.centerline.signedDistanceTo(self.position)
        rate = 0.0 if prev is None else (off - prev)
        prev = off
        cmd = max(-0.5, min(0.5, 0.9 * off + 10.0 * rate))
        if self.speed < target:
            take SetThrottleAction(0.6), SetBrakeAction(0.0), SetSteerAction(cmd)
        else:
            take SetThrottleAction(0.0), SetBrakeAction(0.0), SetSteerAction(cmd)

lead = new Car at lanePt(20, 0.0),
    with blueprint 'vehicle.nissan.patrol',
    with behavior LeadCarBehavior(9.0, 30)

# Round 4 left both models clean: when the SUV swerved right the ego simply
# followed it into an empty lane (R1 steered 0.284 and reported "Keep distance to
# the lead vehicle because it is ahead in the same lane"). The source clip's highway is
# busy, so fill the right-hand lane and take that escape away. A gap is left
# around 26-40 m for the SUV itself to slot into.
# `lanePt(d, lat)` offsets to the ego's LEFT for positive lat, so the ego's RIGHT
# lane is lat = -3.5.
behavior SameDirectionBehavior(target):
    while True:
        if self.speed < target:
            take SetThrottleAction(0.5), SetBrakeAction(0.0), SetSteerAction(0.0)
        else:
            take SetThrottleAction(0.0), SetBrakeAction(0.0), SetSteerAction(0.0)

r1c = new Car at lanePt(6, -3.5), facing lanePt(6, -3.5).heading,
    with behavior SameDirectionBehavior(6.0)
r2c = new Car at lanePt(17, -3.5), facing lanePt(17, -3.5).heading,
    with behavior SameDirectionBehavior(6.0)
r3c = new Car at lanePt(48, -3.5), facing lanePt(48, -3.5).heading,
    with behavior SameDirectionBehavior(6.0)
