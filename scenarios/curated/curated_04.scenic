description = "A pickup truck crosses from the far side of the road into the ego's left-hand lane on a multi-lane road."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town05.xodr')
param carla_map = 'Town05'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'ClearNoon'

import math

# The ego must be in the LEFT-HAND lane of a multi-lane carriageway, and the lane
# immediately to its left must be OPPOSING traffic -- i.e. a painted centre line,
# not a barrier. Town04's leftmost lanes sit against a Jersey barrier: a vehicle
# placed on the median there has its tail inside the barrier mesh and physics
# ejects it in a random direction (measured: +0.5 m one run, -4.7 m the next).
laneSecs = []
for lane in network.lanes:
    for laneSec in lane.sections:
        pts = laneSec.centerline.points
        if len(pts) < 2 or laneSec.centerline.length <= 60:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        if straightness > 0.97 \
           and laneSec._laneToLeft is not None \
           and laneSec._laneToLeft.isForward != laneSec.isForward \
           and laneSec._laneToRight is not None \
           and laneSec._laneToRight.isForward == laneSec.isForward:
            laneSecs.append(laneSec)

egoLaneSec = Uniform(*laneSecs)
egoSpawnPt = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(20), facing roadDirection

aheadPt = new OrientedPoint following roadDirection from egoSpawnPt for Range(27, 31)
advPt = new OrientedPoint left of aheadPt by 3.5

# Hold first: the runner ticks NUM_HISTORY=16 warmup frames before frame 0, so a
# pickup that moves immediately has already crossed before the episode starts.
# Then cross, then stop IN the ego's lane -- the source clip's hazard is a vehicle that
# establishes itself in the lane, not one that clears it.
EGO_LANE = egoLaneSec

behavior CrossingBehavior(ttc, throttle, stopdist, xpoint):
    # Trigger on the ego's distance, not a tick count. Round 3 still gave R1 room:
    # from rest the pickup needs ~1 s to break away, so a 16 m trigger handed the
    # ego about 25 m of warning and R1 simply stopped behind it ("Resume speed
    # since the lead vehicle clears the lane"). The source clip's pickup pulls out right in
    # front of oncoming traffic -- trigger at 9 m so it is a genuine cut-in.
    # The runner also ticks NUM_HISTORY=16 warmup frames before frame 0, so a
    # pickup that moves immediately has already crossed before the episode starts.
    # The cap must exceed the episode length or it, not the distance, decides when
    # the pickup moves: at range(45) the hold expired around tick 45 every time and
    # the crossing began at ~15 m regardless of the trigger value. It stays bounded
    # only so a stalled ego cannot deadlock the behavior.
    # Trigger on the ego's TIME to the crossing point, not on a straight-line
    # distance to the pickup: the pickup waits 3.5 m off the ego's lane, so
    # `distance from self to ego` bottoms out near 3.5 m and fires only once the
    # ego is level with it. Time-to-arrival is also speed-invariant, which matters
    # because Alpamayo drives the ego at a different speed than the preview does.
    for i in range(120):
        v = ego.speed
        if v > 0.5 and (distance from ego to xpoint) / v < ttc:
            break
        take SetBrakeAction(1.0)
    # Stop ON the ego's lane, not past it. A fixed 24-tick burst at 0.85-1.0
    # carried the pickup to 6.9 m the far side of the ego -- it swept the lane
    # clean instead of blocking it. Close the loop on the ego lane's centreline
    # and use a gentler throttle so the stopping distance fits inside the lane.
    # The throttle must RAMP from a high value: a Nissan Patrol will not break away
    # from rest at 0.5, it simply sits there with the brake released.
    t = throttle
    for i in range(60):
        if EGO_LANE.centerline.distanceTo(self.position) < stopdist:
            break
        # Scenic's Set*Action calls mutate ONE field of a persistent VehicleControl,
        # so the brake from the hold phase stays applied until it is explicitly
        # cleared. Every earlier variant of this scenario crawled for exactly this
        # reason. Always release the brake in the same tick you apply throttle.
        take SetThrottleAction(t), SetBrakeAction(0.0), SetSteerAction(0.0)
        t = min(1.0, t + 0.05)
    while True:
        take SetThrottleAction(0.0), SetBrakeAction(1.0)

pickup = new Car at advPt,
    with heading aheadPt.heading - 70 deg,
    with blueprint 'vehicle.nissan.patrol',
    with behavior CrossingBehavior(2.4, 0.9, 2.6, aheadPt)

param EGO_SPEED = Range(18, 20)
param SAFETY_DISTANCE = Range(12, 18)

behavior EgoBehavior(target_speed, safety_distance):
    do FollowLaneBehavior(target_speed=target_speed)

ego = new Car at egoSpawnPt,
    with blueprint MODEL,
    with behavior EgoBehavior(globalParameters.EGO_SPEED, globalParameters.SAFETY_DISTANCE)

require 24 <= (distance from ego to pickup) <= 36
