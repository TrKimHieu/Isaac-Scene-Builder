"""Tests for architecture.py on the 1 m grid: room styles, wall runs split into kit pieces,
caps, doors on one 1 m edge, windows, glass, floor meshes, legacy 3 m map conversion."""
import glob
import json
import math
import os

import pytest

import architecture as arch
import map_format
from config import (CELL, KIT, KIT_M, WALL_HALF, DOOR_HINGE, DOOR_OPEN_DEG, MAPS_DIR,
                    EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING, LEGACY_CELL)


def _map(cells, vedges=None, hedges=None, **extra):
    m = {"cell": CELL, "grid": [12, 12], "cells": {"%d,%d" % k: v for k, v in cells.items()},
         "vedges": {"%d,%d" % k: v for k, v in (vedges or {}).items()},
         "hedges": {"%d,%d" % k: v for k, v in (hedges or {}).items()}, "furniture": []}
    m.update(extra)
    return m


def _block(i0, j0, w, h, v=1):
    return {(i, j): v for i in range(i0, i0 + w) for j in range(j0, j0 + h)}


def _vline(i, j0, n, t=EDGE_WALL):
    return {(i, j): t for j in range(j0, j0 + n)}


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

    def test_floor_and_ceiling_one_mesh_per_style(self):
        cells = _block(0, 0, 3, 2)
        m = _map(cells, styles={"2,1": "warehouse"})
        floors = {it["style"]: it for it in _items(m, kind="floor")}
        assert set(floors) == {"office", "warehouse"}
        assert len(floors["office"]["cells"]) == 5 and floors["warehouse"]["cells"] == [(2, 1)]
        assert {it["style"] for it in _items(m, kind="ceiling")} == {"office", "warehouse"}


class TestSplitRun:
    @pytest.mark.parametrize("n,pieces", [(1, [1]), (2, [2]), (3, [3]), (4, [2, 2]), (5, [3, 2]),
                                          (6, [3, 3]), (7, [3, 2, 2]), (8, [3, 3, 2])])
    def test_pieces(self, n, pieces):
        assert arch.split_run(n) == pieces


class TestWalls:
    def test_run_merged_into_kit_pieces(self):
        """A 5 m wall = one 3 m + one 2 m piece (two panels each), the 2 m one scaled."""
        m = _map(_block(0, 0, 2, 5), vedges=_vline(2, 0, 5))
        walls = sorted(_items(m, kind="wall"), key=lambda it: (it["name"]))
        assert len(walls) == 4 and {w["asset"] for w in walls} == {KIT["wall"]}
        a3 = [w for w in walls if w["name"].endswith("_0_a")][0]
        a2 = [w for w in walls if w["name"].endswith("_1_a")][0]
        assert _near(a3["pos"], (2 * CELL, 0, 0)) and "panel" not in a3      # the kit panel
        assert _near(a2["pos"], (2 * CELL, 3 * CELL, 0))
        assert a2["panel"] == (2 * CELL, 0.0, 3.0)                              # a 2 m face
        b2 = [w for w in walls if w["name"].endswith("_1_b")][0]
        assert _near(b2["pos"], (2 * CELL, 5 * CELL, 0)) and b2["yaw"] == 180

    def test_each_face_takes_its_room_style(self):
        m = _map(_block(0, 0, 2, 1), vedges={(1, 0): EDGE_WALL},
                 styles={"0,0": "hospital", "1,0": "warehouse"})
        a, b = sorted(_items(m, kind="wall"), key=lambda it: it["name"])
        assert a["style"] == "warehouse"        # panel A faces +X = cell (1,0)
        assert b["style"] == "hospital"         # panel B faces -X = cell (0,0)

    def test_run_breaks_where_a_face_style_changes(self):
        cells = _block(0, 0, 2, 4)
        styles = {"1,%d" % j: ("hospital" if j < 2 else "office") for j in range(4)}
        m = _map(cells, vedges=_vline(1, 0, 4), styles=styles)
        assert len(arch.runs(m)) == 2

    def test_hedge_faces(self):
        m = _map({(0, 0): 1, (0, 1): 1}, hedges={(0, 1): EDGE_WALL},
                 styles={"0,0": "hospital", "0,1": "residential"})
        a, b = sorted(_items(m, kind="wall"), key=lambda it: it["name"])
        assert a["yaw"] == 270 and a["style"] == "hospital"      # -Y side = cell (0,0)
        assert b["yaw"] == 90 and b["style"] == "residential"


class TestCaps:
    def test_straight_run_has_no_inner_caps(self):
        m = _map({(0, 0): 1}, vedges=_vline(0, 0, 3))
        names = {c["name"] for c in _items(m, kind="cap")}
        assert names == {"Cap_0_0_S", "Cap_0_3_N"}

    def test_l_corner_closes_the_two_open_sides(self):
        m = _map({(0, 0): 1}, vedges={(0, 0): 1}, hedges={(0, 0): 1})   # N + E at (0,0)
        caps = {c["name"]: c for c in _items(m, kind="cap") if c["name"].startswith("Cap_0_0_")}
        assert set(caps) == {"Cap_0_0_S", "Cap_0_0_W"}
        assert _near(caps["Cap_0_0_S"]["pos"], (0, -WALL_HALF, 0))
        assert _near(caps["Cap_0_0_W"]["pos"], (-WALL_HALF, 0, 0))

    def test_door_leaves_capped_wall_ends(self):
        m = _map(_block(0, 0, 2, 3), vedges={(1, 0): EDGE_WALL, (1, 1): EDGE_DOOR,
                                             (1, 2): EDGE_WALL})
        names = {c["name"] for c in _items(m, kind="cap")}
        assert {"Cap_1_1_N", "Cap_1_2_S"} <= names        # both sides of the doorway


class TestDoors:
    def _door(self, **extra):
        m = _map(_block(0, 0, 2, 3), vedges={(1, 0): EDGE_WALL, (1, 1): EDGE_DOOR,
                                             (1, 2): EDGE_WALL}, **extra)
        d = {it["name"].split("_")[-1]: it for it in _items(m, kind="door")}
        return m, d

    def test_door_on_one_1m_edge(self):
        m, d = self._door()
        assert d["frame"]["asset"] == KIT["door_frame"]
        assert _near(d["frame"]["pos"], (CELL, 1.5 * CELL, 0))
        walls = [w for w in _items(m, kind="wall") if w["name"].startswith("Wall")]
        assert len(walls) == 4 and all(w["panel"][0] == CELL for w in walls)

    def test_open_by_default_hinged_at_frame(self):
        _, d = self._door()
        assert _near(d["leaf"]["pos"], (CELL + DOOR_HINGE[0], 1.5 * CELL + DOOR_HINGE[1], 0))
        assert d["leaf"]["yaw"] == DOOR_OPEN_DEG

    def test_closed_override(self):
        _, d = self._door(door_state={"v:1,1": "closed"})
        assert d["leaf"]["yaw"] == 0
        _, d = self._door(door_default="closed")
        assert d["leaf"]["yaw"] == 0

    def test_handle_follows_leaf(self):
        _, d = self._door()
        hx = d["handle"]["pos"][0] - d["leaf"]["pos"][0]
        hy = d["handle"]["pos"][1] - d["leaf"]["pos"][1]
        assert abs(math.hypot(hx, hy) - math.hypot(-0.026, -0.896)) < 1e-6
        assert d["handle"]["yaw"] == d["leaf"]["yaw"]

    def test_opening_is_a_gap(self):
        m = _map({(0, 0): 1, (1, 0): 1}, vedges={(1, 0): EDGE_OPENING})
        assert _items(m, kind="door") == []
        assert {it["name"][:6] for it in _items(m, kind="wall")} == {"Lintel", "Soffit"}

    def test_adjacent_doors_stay_single(self):
        m = _map(_block(0, 0, 2, 2), vedges=_vline(1, 0, 2, EDGE_DOOR))
        assert len([it for it in _items(m, kind="door") if it["name"].endswith("frame")]) == 2


class TestWindowGlass:
    def test_3m_window(self):
        m = _map(_block(0, 0, 3, 1), hedges={(i, 0): EDGE_WINDOW for i in range(3)})
        (w,) = _items(m, kind="window")
        assert w["asset"] == KIT["window"] and w["yaw"] == 270

    def test_window_rest_is_glazing(self):
        m = _map(_block(0, 0, 5, 1), hedges={(i, 0): EDGE_WINDOW for i in range(5)})
        assets = [it["asset"] for it in _items(m, kind="window")]
        assert assets == [KIT["window"], KIT["glass_2m"]]

    def test_glass_run(self):
        m = _map({(0, 0): 1}, vedges=_vline(0, 0, 3, EDGE_GLASS))
        g = sorted(_items(m, kind="glass"), key=lambda it: it["pos"][1])
        assert [it["asset"] for it in g] == [KIT["glass_2m"], KIT["glass_1m"]]
        assert _near(g[1]["pos"], (0, 2.0, 0))

    def test_legacy_window_structure(self):
        m = _map({(0, 0): 1}, vedges=_vline(0, 0, 3), structure={"wall": "SM_Window_3m_B"})
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


class TestLegacyMaps:
    LEGACY = {"grid": [2, 1], "cells": {"0,0": 2, "1,0": 1}, "styles": {"1,0": "hospital"},
              "vedges": {"0,0": EDGE_WALL, "1,0": EDGE_DOOR, "2,0": EDGE_WINDOW},
              "hedges": {"0,0": EDGE_GLASS}, "door_state": {"v:1,0": "closed"},
              "door_flip": {"v:1,0": True}, "furniture": [{"asset": "X", "x": 4.0, "y": 1.0}]}

    def test_upgrade(self):
        m = map_format.ensure(self.LEGACY)
        k = int(LEGACY_CELL / CELL)
        assert m["cell"] == CELL and m["grid"] == [2 * k, k]
        assert len(m["cells"]) == 2 * k * k
        assert [c for c, s in m["cells"].items() if s == 2] == ["1,1"]       # one lamp, centre
        assert m["styles"]["5,2"] == "hospital"
        assert m["vedges"]["3,1"] == EDGE_DOOR and m["vedges"]["3,0"] == EDGE_WALL
        assert all(m["vedges"]["6,%d" % j] == EDGE_WINDOW for j in range(k))
        assert m["door_state"] == {"v:3,1": "closed"} and m["door_flip"] == {"v:3,1": True}
        assert m["furniture"] == self.LEGACY["furniture"]
        assert map_format.ensure(m) is m

    def test_door_stays_where_it_was(self):
        old = arch.door_leaves(dict(self.LEGACY, door_state={}))         # read as 1 m: wrong
        new = arch.door_leaves(map_format.ensure(dict(self.LEGACY, door_state={})))
        (x0, y0, _x1, _y1), = new
        assert abs(x0 - (LEGACY_CELL - DOOR_HINGE[0])) < 1e-6                # flipped frame
        assert abs(y0 - (LEGACY_CELL / 2 - DOOR_HINGE[1])) < 1e-6
        assert old != new


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(MAPS_DIR, "*.json"))))
def test_saved_maps_plan(path):
    with open(path, encoding="utf-8") as fh:
        m = map_format.ensure(json.load(fh))
    items = arch.plan_structure(m)
    assert items and all(it["asset"] for it in items)
    n_edges = sum(1 for v in list(m["vedges"].values()) + list(m["hedges"].values()) if v)
    assert len(arch.bev_edges(m)) == n_edges


def test_door_flip_swings_into_other_room():
    m = _map(_block(0, 0, 2, 1), vedges={(1, 0): EDGE_DOOR})
    (x0, _, x1, _), = arch.door_leaves(m)
    assert x1 > x0                                   # default: into the +X room
    m["door_flip"] = {"v:1,0": True}
    (x0, _, x1, _), = arch.door_leaves(m)
    assert x1 < x0                                   # flipped: into the -X room
    frame = [it for it in _items(m, kind="door") if it["name"].endswith("frame")][0]
    assert frame["yaw"] == 180


class TestLintelHinge:
    def _m(self, **extra):
        return _map(_block(0, 0, 2, 3), vedges={(1, 0): EDGE_WALL, (1, 1): EDGE_DOOR,
                                                (1, 2): EDGE_WALL}, **extra)

    def test_lintel_fills_above_the_door(self):
        lin = sorted(_items(self._m(styles={"1,1": "hospital"}), kind="wall"),
                     key=lambda it: it["name"])
        lin = [it for it in lin if it["name"].startswith("Lintel")]
        assert len(lin) == 2
        a, b = lin
        assert a["panel"] == (CELL, arch.LINTEL_Z, 3.0)                     # up to the ceiling
        assert a["style"] == "hospital" and b["style"] == "office"          # like the wall faces

    def test_mirrored_hinge_other_jamb_same_room(self):
        m = self._m()
        (h0, t0) = arch.leaf_segment(m, "v", 1, 1)
        m["door_hinge"] = {"v:1,1": True}
        (h1, t1) = arch.leaf_segment(m, "v", 1, 1)
        assert abs(h0[1] - h1[1] - 2 * DOOR_HINGE[1]) < 1e-9                # other jamb
        assert t0[0] > CELL + 0.5 and t1[0] > CELL + 0.5                     # same room (+X)
        frame = [it for it in _items(m, kind="door") if it["name"].endswith("frame")][0]
        assert frame["yaw"] == 0                                             # frame unchanged

    def test_leaf_against_a_side_wall_is_blocked_and_fixed(self):
        """A wall right beside the hinge jamb, perpendicular, on the swing side."""
        m = self._m(hedges={(1, 2): EDGE_WALL})       # wall along y = 2 from x = 1 to 2
        m["door_hinge"] = {}
        blocked = arch.door_swing_blocked(m, "v", 1, 1)
        m2 = dict(m, door_hinge={"v:1,1": True})
        assert blocked != arch.door_swing_blocked(m2, "v", 1, 1)
        flip, mir = arch.best_door_setup(m, "v", 1, 1)
        md = dict(m, door_flip={"v:1,1": True} if flip else {},
                  door_hinge={"v:1,1": True} if mir else {})
        assert not arch.door_swing_blocked(md, "v", 1, 1)
        assert flip is False                         # keeps the room it swings into
