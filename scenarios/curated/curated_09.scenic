description = "A line of construction barriers blocks the ego's lane on a multi-lane highway, forcing an abrupt merge."
param map = localPath('../../carla/CARLA_0.9.16/CarlaUE4/Content/Carla/Maps/OpenDrive/Town05.xodr')
param carla_map = 'Town05'
model scenic.simulators.carla.model
MODEL = 'vehicle.lincoln.mkz_2017'
param weather = 'ClearNoon'

import math

laneSecs = []
for lane in network.lanes:
    for laneSec in lane.sections:
        pts = laneSec.centerline.points
        if len(pts) < 2 or laneSec.centerline.length <= 60:
            continue
        straightness = math.dist(tuple(pts[0])[:2], tuple(pts[-1])[:2]) / laneSec.centerline.length
        if straightness > 0.97 \
           and laneSec._laneToLeft is not None \
           and laneSec._laneToLeft.isForward == laneSec.isForward:
            laneSecs.append(laneSec)
egoLaneSec = Uniform(*laneSecs)
egoSpawnPt = new OrientedPoint at egoLaneSec.centerline.pointAlongBy(6), facing roadDirection

behavior EgoBehavior(speed):
    do FollowLaneBehavior(target_speed=speed)

ego = new Car at egoSpawnPt, with blueprint MODEL, with behavior EgoBehavior(8)

def barrierAt(d, lat):
    b = new OrientedPoint following roadDirection from egoSpawnPt for d
    return new OrientedPoint left of b by lat, facing b.heading

b1 = new Barrier at barrierAt(22, -1.2), with blueprint 'static.prop.streetbarrier', with regionContainedIn None
b2 = new Barrier at barrierAt(25, 0.0),  with blueprint 'static.prop.streetbarrier', with regionContainedIn None
b3 = new Barrier at barrierAt(28, 1.2),  with blueprint 'static.prop.streetbarrier', with regionContainedIn None
c1 = new Cone at barrierAt(19, -1.4), with blueprint 'static.prop.constructioncone', with regionContainedIn None
c2 = new Cone at barrierAt(19, 1.4),  with blueprint 'static.prop.constructioncone', with regionContainedIn None
