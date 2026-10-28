"""Tests for robots.py: imported robot models, footprints, Nav2 / generator / USD use."""
import os

import pytest

import robots
import nav_export
import map_generator as mg

EXPECTED = ["jetauto_pro", "jetbot", "turtlebot3_burger", "turtlebot3_waffle_pi", "turtlebot4",
            "turtlebot4_lite"]


def test_models_imported_in_order():
    assert list(robots.load_robots()) == EXPECTED
    for rid in EXPECTED:
        assert os.path.isfile(os.path.join(robots.ROBOTS_DIR, rid + ".svg"))


@pytest.mark.parametrize("rid", EXPECTED)
def test_footprint_sane(rid):
    s = robots.get(rid)
    pts = s["footprint"]["points"]
    assert len(pts) >= 4
    assert 0.08 < s["r_circ"] < 0.4 and 0 < s["r_insc"] <= s["r_circ"]
    assert 0.1 < s["height"] < 1.0
    xs = [p[0] for p in pts]
    assert min(xs) < 0 < max(xs)                    # origin inside the body


def test_jetauto_outline_from_mesh():
    """Traced from jetauto_pro.usd, not navsim's centred 0.324 x 0.26 box: the back shell
    reaches x = -0.167, the front wheels x = +0.148, wheels +/-0.128 in y."""
    s = robots.get("jetauto_pro")
    assert s["sources"]["footprint"]["kind"] == "measured"
    assert s["sources"]["footprint"]["replaces"]["type"] == "rectangle"
    xs = [p[0] for p in s["footprint"]["points"]]
    ys = [p[1] for p in s["footprint"]["points"]]
    assert abs(min(xs) + 0.167) < 0.004 and abs(max(xs) - 0.148) < 0.004
    assert abs(max(ys) - 0.128) < 0.004 and abs(min(ys) + 0.128) < 0.004
    assert len(xs) > 8                                     # wheels / body notches kept
    assert s["drive"] == "omnidirectional" and s["lidar"]  # the rest still from navsim


def test_outline_is_ccw():
    for s in robots.load_robots().values():
        pts = s["footprint"]["points"]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
        assert area > 0, s["id"]


def test_unknown_falls_back_to_default():
    assert robots.get("r2d2")["id"] == robots.DEFAULT_ROBOT
    assert robots.model_of({}) == robots.DEFAULT_ROBOT


def test_place_rotates_about_pose():
    s = robots.get("jetauto_pro")
    local = s["footprint"]["points"]
    pts = robots.place(s, 1.0, 2.0, 90)                  # +x (forward) -> world +y
    for (lx, ly), (wx, wy) in zip(local, pts):
        assert abs(wx - (1.0 - ly)) < 1e-9 and abs(wy - (2.0 + lx)) < 1e-9


def test_nav_yaml_has_footprint(tmp_path):
    md = {"robot": {"model": "turtlebot4", "spawn": {"x": 1, "y": 1, "yaw": 0},
                    "waypoints": [[2, 2]]}}
    path = nav_export.write_nav(md, str(tmp_path), "m")
    text = open(path, encoding="utf-8").read()
    assert "robot_model: turtlebot4" in text and "footprint: \"[[" in text
    assert text.count("], [") + 1 <= 16                   # simplified outline


def test_generator_records_model_and_radius():
    md = mg.generate_map(3, "office", size=(6, 5), density=0.15, robot="jetbot")
    assert md["robot"]["model"] == "jetbot"
    assert mg.map_metrics(md)["robot"] == "jetbot"
    small = mg.map_metrics(md)["robot_free_ratio"]
    md["robot"]["model"] = "turtlebot3_waffle_pi"          # bigger robot -> less free space
    assert mg.map_metrics(md)["robot_free_ratio"] < small


def test_usd_spawn_footprint(tmp_path):
    from usd_runtime import pxr_available
    if not pxr_available():
        pytest.skip("no OpenUSD")
    from pxr import Usd, UsdGeom
    import scene_builder as sb
    stage = Usd.Stage.CreateInMemory()
    sb.add_robot_markers(stage, {"model": "jetbot", "spawn": {"x": 0, "y": 0, "yaw": 0}})
    prim = stage.GetPrimAtPath("/World/Robot/Spawn/Footprint")
    assert prim and len(UsdGeom.BasisCurves(prim).GetPointsAttr().Get()) == len(
        robots.get("jetbot")["footprint"]["points"])
    assert stage.GetPrimAtPath("/World/Robot/Spawn").GetCustomDataByKey("robot:model") == "jetbot"
