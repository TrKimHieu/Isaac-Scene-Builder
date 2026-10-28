"""Tests for architecture.py: room styles, double-panel walls, caps, doors, windows, glass."""
import glob
import json
import math
import os

import pytest

import architecture as arch
from config import (CELL, KIT, WALL_HALF, DOOR_HINGE, DOOR_OPEN_DEG, MAPS_DIR,
                    EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING)


def _map(cells, vedges=None, hedges=None, **extra):
    m = {"grid": [6, 6], "cells": {"%d,%d" % k: v for k, v in cells.items()},
         "vedges": {"%d,%d" % k: v for k, v in (vedges or {}).items()},
         "hedges": {"%d,%d" % k: v for k, v in (hedges or {}).items()}, "furniture": []}
    m.update(extra)
    return m


def _items(m, **filt):
    return [it for it in arch.plan_structure(m)
            if all(it.get(k) == v for k, v in filt.items())]


def _near(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


class TestStyles:
    def test_default_and_painted(self):
        m = _map({(0, 0): 1, (1, 0): 1}, styles={"1,0": "hospital"})
        assert arch.cell_styles(m) == {(0, 0): "office", (1, 0): "hospital"}

    def test_unknown_style_falls_back(self):
        m = _map({(0, 0): 1}, styles={"0,0": "spaceship"})
        assert arch.cell_styles(m)[(0, 0)] == "office"

    def test_floor_and_ceiling_take_cell_style(self):
        m = _map({(0, 0): 1}, styles={"0,0": "warehouse"})
        assert {(it["slot"], it["style"]) for it in _items(m, kind="floor")} == {("floor", "warehouse")}
        assert {(it["slot"], it["style"]) for it in _items(m, kind="ceiling")} == {("ceiling", "warehouse")}


class TestWalls:
    def test_wall_is_two_back_to_back_panels(self):
        m = _map({(0, 0): 1, (1, 0): 1}, vedges={(1, 0): EDGE_WALL})
        a, b = _items(m, kind="wall")
        assert a["asset"] == b["asset"] == KIT["wall"]
        assert _near(a["pos"], (CELL, 0, 0)) and a["yaw"] == 0
        assert _near(b["pos"], (CELL, CELL, 0)) and b["yaw"] == 180

    def test_each_face_takes_its_room_style(self):
        m = _map({(0, 0): 1, (1, 0): 1}, vedges={(1, 0): EDGE_WALL},
                 styles={"0,0": "hospital", "1,0": "warehouse"})
        a, b = _items(m, kind="wall")
        assert a["style"] == "warehouse"        # panel A faces +X = cell (1,0)
        assert b["style"] == "hospital"         # panel B faces -X = cell (0,0)

    def test_hedge_faces(self):
        m = _map({(0, 0): 1, (0, 1): 1}, hedges={(0, 1): EDGE_WALL},
                 styles={"0,0": "hospital", "0,1": "residential"})
        a, b = _items(m, kind="wall")
        assert a["yaw"] == 270 and a["style"] == "hospital"      # -Y side = cell (0,0)
        assert b["yaw"] == 90 and b["style"] == "residential"

    def test_outer_wall_outside_face_uses_inside_style(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): EDGE_WALL}, styles={"0,0": "hospital"})
        assert {it["style"] for it in _items(m, kind="wall")} == {"hospital"}


class TestCaps:
    def test_straight_run_has_no_caps(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): 1, (0, 1): 1})
        caps = [c for c in _items(m, kind="cap") if c["name"].startswith("Cap_0_1_")]
        assert caps == []

    def test_free_end_cap_faces_away(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): 1})        # runs (0,0)->(0,3)
        caps = {c["name"]: c for c in _items(m, kind="cap")}
        start = caps["Cap_0_0_S"]
        assert _near(start["pos"], (0, 0, 0)) and start["yaw"] == 0
        end = caps["Cap_0_1_N"]
        assert _near(end["pos"], (0, CELL, 0)) and end["yaw"] == 180

    def test_l_corner_closes_the_two_open_sides(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): 1}, hedges={(0, 0): 1})   # N + E at (0,0)
        caps = {c["name"]: c for c in _items(m, kind="cap") if c["name"].startswith("Cap_0_0_")}
        assert set(caps) == {"Cap_0_0_S", "Cap_0_0_W"}
        assert _near(caps["Cap_0_0_S"]["pos"], (0, -WALL_HALF, 0))
        assert _near(caps["Cap_0_0_W"]["pos"], (-WALL_HALF, 0, 0))

    def test_t_junction_one_cap(self):
        m = _map({(0, 0): 1}, vedges={(1, 0): 1, (1, 1): 1}, hedges={(1, 1): 1})
        caps = [c["name"] for c in _items(m, kind="cap") if c["name"].startswith("Cap_1_1_")]
        assert caps == ["Cap_1_1_W"]

    def test_windows_do_not_count_as_thick(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): EDGE_WALL, (0, 1): EDGE_WINDOW})
        names = {c["name"] for c in _items(m, kind="cap")}
        assert "Cap_0_1_N" in names             # wall end next to the thinner window


class TestDoors:
    def _door(self, **extra):
        m = _map({(0, 0): 1, (1, 0): 1}, vedges={(1, 0): EDGE_DOOR}, **extra)
        d = {it["name"].split("_")[-1]: it for it in _items(m, kind="door")}
        return m, d

    def test_door_parts(self):
        m, d = self._door()
        assert d["frame"]["asset"] == KIT["door_frame"]
        assert _near(d["frame"]["pos"], (CELL, CELL / 2, 0))
        assert {it["asset"] for it in _items(m, kind="wall")} == {KIT["wall_door"]}

    def test_open_by_default_hinged_at_frame(self):
        _, d = self._door()
        assert _near(d["leaf"]["pos"], (CELL + DOOR_HINGE[0], CELL / 2 + DOOR_HINGE[1], 0))
        assert d["leaf"]["yaw"] == DOOR_OPEN_DEG

    def test_closed_override(self):
        _, d = self._door(door_state={"v:1,0": "closed"})
        assert d["leaf"]["yaw"] == 0
        _, d = self._door(door_default="closed")
        assert d["leaf"]["yaw"] == 0

    def test_handle_follows_leaf(self):
        _, d = self._door()
        hx = d["handle"]["pos"][0] - d["leaf"]["pos"][0]
        hy = d["handle"]["pos"][1] - d["leaf"]["pos"][1]
        assert abs(math.hypot(hx, hy) - math.hypot(-0.026, -0.896)) < 1e-6
        assert d["handle"]["yaw"] == d["leaf"]["yaw"]

    def test_opening_has_no_leaf(self):
        m = _map({(0, 0): 1, (1, 0): 1}, vedges={(1, 0): EDGE_OPENING})
        assert _items(m, kind="door") == []
        assert {it["asset"] for it in _items(m, kind="wall")} == {KIT["wall_door"]}


class TestWindowGlass:
    def test_window(self):
        m = _map({(0, 0): 1}, hedges={(0, 0): EDGE_WINDOW})
        (w,) = _items(m, kind="window")
        assert w["asset"] == KIT["window"] and w["yaw"] == 270

    def test_glass_is_2m_plus_1m(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): EDGE_GLASS})
        g = sorted(_items(m, kind="glass"), key=lambda it: it["pos"][1])
        assert [it["asset"] for it in g] == [KIT["glass_2m"], KIT["glass_1m"]]
        assert _near(g[1]["pos"], (0, 2.0, 0))

    def test_legacy_window_structure(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): EDGE_WALL}, structure={"wall": "SM_Window_3m_B"})
        (w,) = _items(m, kind="window")
        assert w["asset"] == "SM_Window_3m_B"


class TestBevEdges:
    def test_kinds(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): EDGE_DOOR, (1, 0): EDGE_WINDOW},
                 hedges={(0, 0): EDGE_GLASS, (0, 1): EDGE_OPENING}, door_default="closed")
        kinds = sorted(k for k, *_ in arch.bev_edges(m))
        assert kinds == ["door_closed", "glass", "opening", "window"]

    def test_rows_and_raster(self, tmp_path):
        import bev_export as bev
        m = _map({(0, 0): 1}, vedges={(0, 0): EDGE_DOOR, (1, 0): EDGE_WALL},
                 hedges={(0, 0): EDGE_GLASS, (0, 1): EDGE_WINDOW}, styles={"0,0": "hospital"})
        _, _, rows = bev.scene_rows(m)
        assert [r["name"] for r in rows if r["kind"] == "floor"] == ["hospital"]
        assert {r["kind"] for r in rows} >= {"door", "wall", "glass", "window"}
        W, H = bev.write_raster(m, str(tmp_path / "x.png"))
        assert W > 0 and H > 0


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(MAPS_DIR, "map*.json"))))
def test_existing_maps_still_plan(path):
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    items = arch.plan_structure(m)
    assert items and all(it["asset"] for it in items)
    n_edges = sum(1 for v in list(m["vedges"].values()) + list(m["hedges"].values()) if v)
    assert len(arch.bev_edges(m)) == n_edges


def test_door_flip_swings_into_other_room():
    m = _map({(0, 0): 1, (1, 0): 1}, vedges={(1, 0): EDGE_DOOR})
    (x0, _, x1, _), = arch.door_leaves(m)
    assert x1 > x0                                   # default: into the +X room
    m["door_flip"] = {"v:1,0": True}
    (x0, _, x1, _), = arch.door_leaves(m)
    assert x1 < x0                                   # flipped: into the -X room
    frame = [it for it in _items(m, kind="door") if it["name"].endswith("frame")][0]
    assert frame["yaw"] == 180
