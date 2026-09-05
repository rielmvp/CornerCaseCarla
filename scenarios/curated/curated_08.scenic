description = "At night a pedestrian steps off the kerb and walks across the ego's lane against the signal."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town02.xodr')
param carla_map = 'Town02'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'ClearNight'

import math

laneSecs = []
for lane in network.lanes:
    for laneSec in lane.sections:
        pts = laneSec.centerline.points
        if len(pts) < 2 or laneSec.centerline.length <= 100:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        if straightness > 0.97 and len(laneSec.lane.road.lanes) == 2 \
           and laneSec._laneToLeft is not None \
           and laneSec._laneToLeft.isForward != laneSec.isForward:
            laneSecs.append(laneSec)
egoLaneSec = Uniform(*laneSecs)

# North American source clip: normal right-hand-traffic construction.
egoSpawnPt = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection

behavior EgoBehavior(speed):
    do FollowLaneBehavior(target_speed=speed)

ego = new Car at egoSpawnPt, with blueprint MODEL, with behavior EgoBehavior(8)

pedBase = new OrientedPoint following roadDirection from egoSpawnPt for Range(22, 28)
pedPt = new OrientedPoint right of pedBase by 4.5

behavior CrossBehavior(speed, heading):
    for i in range(60):
        if (distance from self to ego) < 20:
            break
        wait
    while True:
        take SetWalkingDirectionAction(heading), SetWalkingSpeedAction(speed)

walker = new Pedestrian at pedPt,
    facing pedBase.heading + 90 deg,
    with regionContainedIn None,
    with behavior CrossBehavior(1.7, pedBase.heading + 90 deg)
