description = "A steel plank shed by an unsecured load lies across the ego's lane on a multi-lane highway, hidden until the van ahead swings out of the way."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town04.xodr')
param carla_map = 'Town04'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'ClearSunset'

import math

# The source clip is a Japanese multi-lane expressway: left-hand traffic, ego in the
# left-hand running lane, overtaking happens on its RIGHT. Require a
# same-direction lane to the right so the van has somewhere to swing out to.
laneSecs = []
for lane in network.lanes:
    for laneSec in lane.sections:
        pts = laneSec.centerline.points
        if len(pts) < 2 or laneSec.centerline.length <= 80:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        # Town04's multi-lane sections are gently curved even at straightness 0.97,
        # which throws a 46 m-ahead obstacle 14 m off the ego's axis. 0.9999 still
        # leaves 24 sections, the longest 237 m.
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

# Anchor on the SECTION's own centreline, not `following roadDirection ... for d`:
# that integrates the road's direction field and veers off where it crosses into
# another road, which threw the 46 m plank 23 m to the side.
def lanePt(d, lat):
    b = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6 + d), facing roadDirection
    return new OrientedPoint left of b by lat, facing b.heading

# The hazard: a low steel plank lying across the running lane. It is not the
# plank alone that makes this a corner case -- it is that the van ahead
# straddles it until the last moment, so the ego never sees it early.
plank = new Debris at lanePt(46, 0.0),
    with blueprint 'static.prop.ironplank',
    with regionContainedIn None

# A constant throttle below ~0.25 will not move a CARLA vehicle from rest, and a
# fixed-tick steer pulse cannot end a lane change (it leaves yaw rate unresolved
# and the vehicle carries several metres past the target lane). Both loops here
# are closed: speed on self.speed, and the swerve on the target lane's centreline
# with a derivative term so the van settles instead of overshooting.
behavior LeadVanBehavior(target, reveal, slow):
    # Round 4 left both models clean. Two reasons, both fixed here:
    #  1. The van pulled out 13 m before the plank, which is ~31 m ahead of the
    #     ego -- ample warning. It now pulls out 5 m before the plank, and starts
    #     only 12 m ahead of the ego at a speed slightly below the ego's, so the
    #     ego is close behind when the plank is uncovered. (Triggering on the
    #     EGO's time-to-plank does NOT work here: at 9 m/s the van outran the ego
    #     and was 25 m past the plank before the ego's TTC ever fell.)
    #  2. After swerving the van drove away, freeing the right-hand lane, so the
    #     ego simply followed it across (R1 steered 0.271 and never touched the
    #     plank). The van now SLOWS once it is over, so the lane beside the plank
    #     is still occupied when the ego gets there.
    prev = None
    while True:
        if (distance from self to plank) < reveal:
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
        if self.speed < slow:
            take SetThrottleAction(0.45), SetBrakeAction(0.0), SetSteerAction(cmd)
        else:
            take SetThrottleAction(0.0), SetBrakeAction(0.0), SetSteerAction(cmd)

van = new Car at lanePt(12, 0.0),
    with blueprint 'vehicle.mercedes.sprinter',
    with behavior LeadVanBehavior(7.0, 5, 2.5)
