"""Tests for simulation readiness: colliders, semantics, height slices, robot + Nav2, ROS map."""
import math
import os
import py_compile

import numpy as np
import pytest
from PIL import Image

import architecture as arch
import map_format
import nav_export
from config import LEGACY_CELL, EDGE_DOOR, EDGE_WALL


def _room(**extra):
    """Two 3 x 3 m rooms with a door between them (a legacy 3 m map, converted)."""
    m = {"grid": [2, 1], "cells": {"0,0": 1, "1,0": 1},
         "vedges": {"0,0": EDGE_WALL, "1,0": EDGE_DOOR, "2,0": EDGE_WALL},
         "hedges": {"0,0": 1, "1,0": 1, "0,1": 1, "1,1": 1}, "furniture": []}
    m.update(extra)
    return map_format.ensure(m)


# ----------------------------------------------------------------------------
# Door leaves (BEV obstacle)
# ----------------------------------------------------------------------------
class TestDoorLeaves:
    def test_open_leaf_swings_into_plus_x_room(self):
        (x0, y0, x1, y1), = arch.door_leaves(_room())
        assert x1 > x0 + 0.8                          # vedge door opens towards +X
        assert abs(math.hypot(x1 - x0, y1 - y0) - arch.DOOR_LEAF_W) < 1e-9

    def test_closed_door_has_no_leaf_obstacle(self):
        assert arch.door_leaves(_room(door_default="closed")) == []


# ----------------------------------------------------------------------------
# ROS map frame == USD world frame
# ----------------------------------------------------------------------------
class TestRosMap:
    def test_pgm_flipped_and_origin(self, tmp_path):
        import bev_export as bev
        m = _room(furniture=[{"asset": "X", "x": 1.0, "y": 0.5, "yaw": 0, "shape": "bbox",
                              "w": 0.4, "h": 0.4, "r": 0.2}])
        png = str(tmp_path / "s.png")
        bev.write_raster(m, png, scale=20)
        txt = open(str(tmp_path / "s.yaml")).read()
        assert "origin: [-0.2000, -0.2000, 0.0]" in txt          # margin 0.2 m
        pgm = np.asarray(Image.open(str(tmp_path / "s.pgm")))
        # map_server: world (x, y) -> col = (x - ox)/res, row = H - 1 - (y - oy)/res
        H = pgm.shape[0]
        col = int((1.0 + 0.2) * 20)
        row = H - 1 - int((0.5 + 0.2) * 20)
        assert pgm[row, col] == 0                              # the box at (1.0, 0.5)
        row_mirror = H - 1 - int((LEGACY_CELL - 0.5 + 0.2) * 20)
        assert pgm[row_mirror, col] != 0                       # not at the mirrored y


# ----------------------------------------------------------------------------
# Height slices
# ----------------------------------------------------------------------------
class TestSlices:
    def _table(self):
        """Box legs 0..0.7 m at the 4 corners + a 1x1 m top at 0.70..0.75 m."""
        tris = []

        def quad(a, b, c, d):
            tris.extend([[a, b, c], [a, c, d]])

        def box(x0, y0, z0, x1, y1, z1):
            p = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
            quad(p[0], p[1], p[3], p[2])
            quad(p[4], p[5], p[7], p[6])
            quad(p[0], p[1], p[5], p[4])
            quad(p[2], p[3], p[7], p[6])
            quad(p[0], p[2], p[6], p[4])
            quad(p[1], p[3], p[7], p[5])
        for sx in (-0.45, 0.4):
            for sy in (-0.45, 0.4):
                box(sx, sy, 0.0, sx + 0.05, sy + 0.05, 0.70)
        box(-0.5, -0.5, 0.70, 0.5, 0.5, 0.75)
        return np.asarray(tris, dtype=float)

    def test_low_slice_sees_only_legs(self):
        import slice_footprints as sf
        img, frame = sf.slice_mask(self._table(), 0.05, 0.5, mpp=0.01)
        occ = (np.asarray(img) < 128).mean()
        assert frame == 3.0
        assert 0 < occ < 0.01                       # 4 legs of 5x5 cm in a 3x3 m frame
        img2, _ = sf.slice_mask(self._table(), 0.05, 1.0, mpp=0.01)
        assert (np.asarray(img2) < 128).mean() > 0.1  # the 1x1 m top is inside 0.05..1.0

    def test_nothing_in_slab(self):
        import slice_footprints as sf
        img, frame = sf.slice_mask(self._table(), 1.0, 2.0)
        assert img is None and frame is None


# ----------------------------------------------------------------------------
# Robot + Nav2
# ----------------------------------------------------------------------------
class TestNav:
    def test_plan_headings(self):
        init, wps = nav_export.nav_plan({"spawn": {"x": 0, "y": 0, "yaw": 90},
                                         "waypoints": [[1, 0], [1, 1]]})
        assert init == {"x": 0.0, "y": 0.0, "yaw": math.pi / 2}
        assert abs(wps[0]["yaw"] - math.pi / 2) < 1e-9     # heads to the next waypoint
        assert abs(wps[1]["yaw"] - math.pi / 2) < 1e-9     # last keeps the arrival heading

    def test_write_files(self, tmp_path):
        m = _room(robot={"spawn": {"x": 1, "y": 1, "yaw": 0}, "waypoints": [[4, 1.5]]})
        path = nav_export.write_nav(m, str(tmp_path), "s", "s_occ.yaml")
        txt = open(path).read()
        assert "map: s_occ.yaml" in txt and "initial_pose: {x: 1.0000" in txt
        py_compile.compile(str(tmp_path / "follow_waypoints.py"), doraise=True)

    def test_no_robot_no_files(self, tmp_path):
        assert nav_export.write_nav(_room(), str(tmp_path), "s") is None


class TestEditorRobot:
    def _editor(self):
        from scene_editor import Editor
        e = Editor.__new__(Editor)
        e.robot = {"spawn": {"x": 1.0, "y": 1.0, "yaw": 0.0}, "waypoints": [[3.0, 1.0], [5.0, 1.0]]}
        e._undo_stack, e._redo_stack, e._max_undo = [], [], 50
        e.msg = ""
        e.map_data = lambda: {}
        return e

    def test_remove_nearest(self):
        e = self._editor()
        e.remove_robot_point(3.2, 1.1)
        assert e.robot["waypoints"] == [[5.0, 1.0]]
        e.remove_robot_point(1.1, 0.9)
        assert e.robot["spawn"] is None

    def test_far_click_removes_nothing(self):
        e = self._editor()
        e.remove_robot_point(20.0, 20.0)
        assert len(e.robot["waypoints"]) == 2 and e.robot["spawn"]


# ----------------------------------------------------------------------------
# USD build: physics + semantics + markers (needs OpenUSD)
# ----------------------------------------------------------------------------
@pytest.fixture
def built(tmp_path):
    import scene_builder as sb
    if sb.Usd is None:
        pytest.skip("OpenUSD not available")
    from config import PROJECT_ROOT
    m = _room(furniture=[{"asset": "SM_ChairOffice", "x": 1.5, "y": 1.5, "yaw": 0}],
              robot={"spawn": {"x": 1, "y": 1, "yaw": 0}, "waypoints": [[4, 1.5], [5, 2]]},
              styles={"1,0": "hospital"})
    out = os.path.join(PROJECT_ROOT, "output", "scenes", "_test_sim_ready.usd")
    stats = sb.build_scene(m, out)
    yield sb, stats, out
    if os.path.exists(out):
        os.remove(out)


def test_build_physics_semantics_markers(built):
    sb, stats, out = built
    from pxr import Usd, UsdPhysics, UsdSemantics
    st = Usd.Stage.Open(out)
    assert st.GetPrimAtPath("/World/PhysicsScene").IsA(UsdPhysics.Scene)
    cols = [p for p in st.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI)]
    assert stats["colliders"] > 0 and len(cols) >= stats["colliders"]
    # the builder adds colliders on furniture meshes (Office structure ships its own)
    assert any(str(p.GetPath()).startswith("/World/Furniture/SM_ChairOffice_0/") for p in cols)
    labels = {}
    for p in st.Traverse():
        if p.HasAPI(UsdSemantics.LabelsAPI, "class"):
            labels[str(p.GetPath())] = UsdSemantics.LabelsAPI(p, "class").GetLabelsAttr().Get()[0]
    assert labels["/World/Furniture/SM_ChairOffice_0"] == "seating"
    assert {"floor", "wall", "door", "ceiling"} <= set(labels.values())
    assert stats["robot_markers"] == 3
    assert st.GetPrimAtPath("/World/Robot/Waypoints/WP_01")
    txt = open(out, encoding="utf-8").read()
    assert txt.startswith("#usda") and "../../assets/" in txt


def test_semantic_class_lookup():
    import scene_builder as sb
    assert sb.semantic_class("SM_ChairOffice") == "seating"
    assert sb.semantic_class("SM_Printer") == "appliance"
    assert sb.semantic_class("does_not_exist") == "furniture"
