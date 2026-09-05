description = "Ego vehicle encounters a wrong-way oncoming sedan approaching head-on in its lane on a two-lane road."
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
        if len(pts) < 2 or laneSec.centerline.length <= 40:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        if straightness > 0.97 and len(laneSec.lane.road.lanes) == 2 and laneSec._laneToLeft is not None and laneSec._laneToLeft.isForward != laneSec.isForward:
            laneSecs.append(laneSec)
egoLaneSec = Uniform(*laneSecs)
egoSpawnPt = new OrientedPoint in egoLaneSec.centerline
advSpawnPt = new OrientedPoint following roadDirection from egoSpawnPt for Range(28, 34)

egoTrajectory = [egoLaneSec.lane]

param EGO_SPEED = Range(13, 14)
param EGO_SAFETY_DISTANCE = Range(10, 15)

behavior EgoBehavior(speed, safety_distance):
    do DriveAvoidingCollisions(target_speed=speed, avoidance_threshold=safety_distance)

ego = new Car at egoSpawnPt,
    with blueprint MODEL,
    with behavior EgoBehavior(globalParameters.EGO_SPEED, globalParameters.EGO_SAFETY_DISTANCE)

param ADV_THROTTLE = Range(0.80, 0.90)

behavior WrongWayBehavior(throttle):
    while True:
        take SetThrottleAction(throttle), SetSteerAction(0.0)

advCar = new Car at advSpawnPt,
    facing advSpawnPt.heading + 180 deg,
    with blueprint MODEL,
    with behavior WrongWayBehavior(globalParameters.ADV_THROTTLE)

require 26 <= (distance from ego to advCar) <= 36