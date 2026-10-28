"""Tests for placement.py: footprints, wall obstacles, overlap, wall magnet, settle."""
import pytest

import placement as pl
from config import CELL, WALL_HALF, EDGE_WALL, EDGE_DOOR


ROOM = 3            # one 3 x 3 m room of 1 m cells, walled on all four sides


def _map(**kw):
    m = {"cell": CELL, "grid": [ROOM + 1, ROOM + 1], "furniture": [],
         "cells": {"%d,%d" % (i, j): 1 for i in range(ROOM) for j in range(ROOM)},
         "vedges": {"%d,%d" % (i, j): EDGE_WALL for i in (0, ROOM) for j in range(ROOM)},
         "hedges": {"%d,%d" % (i, j): EDGE_WALL for i in range(ROOM) for j in (0, ROOM)}}
    for k, v in kw.items():
        m[k].update(v)
    return m


def _prop(x, y, w=1.0, h=0.5, yaw=0.0, shape="bbox"):
    return {"asset": "T", "x": x, "y": y, "w": w, "h": h, "r": 0.3, "yaw": yaw, "shape": shape}


def test_footprint_box_and_sphere():
    xs = [p[0] for p in pl.footprint(_prop(1, 1, 2, 1, yaw=90))]
    assert abs(max(xs) - min(xs) - 1.0) < 1e-9          # rotated: the 1 m side now along x
    assert len(pl.footprint(_prop(1, 1, shape="sphere"))) == 16


def test_walls_include_doorway():
    walls = pl.wall_obstacles(_map(vedges={"%d,1" % ROOM: EDGE_DOOR}))
    door = [r for r in walls if abs(r[0] - (ROOM * CELL - WALL_HALF)) < 1e-9 and r[1] == CELL]
    assert door and door[0][3] == 2 * CELL                    # whole edge, gap included


def test_flush_is_not_overlap_but_penetration_is():
    walls = pl.wall_obstacles(_map())
    flush = _prop(WALL_HALF + 0.5, 1.5)                  # left side touches the wall face
    assert not pl.collides(pl.footprint(flush), walls)
    assert pl.collides(pl.footprint(_prop(WALL_HALF + 0.45, 1.5)), walls)


def test_props_overlap():
    a = pl.footprint(_prop(1.5, 1.5))
    assert pl.collides(pl.footprint(_prop(1.9, 1.5)), [], [a])
    assert not pl.collides(pl.footprint(_prop(2.5, 1.5)), [], [a])      # exactly touching


def test_magnet_pulls_flush_to_wall():
    walls = pl.wall_obstacles(_map())
    x, y, what = pl.magnet(_prop(WALL_HALF + 0.5 + 0.18, 1.5), walls)
    assert what == "wall" and abs(x - (WALL_HALF + 0.5)) < 1e-9 and y == 1.5


def test_magnet_into_corner():
    walls = pl.wall_obstacles(_map())
    x, y, _ = pl.magnet(_prop(0.75, 0.45), walls)
    assert abs(x - (WALL_HALF + 0.5)) < 1e-9 and abs(y - (WALL_HALF + 0.25)) < 1e-9


def test_settle_against_wall_with_coarse_grid():
    """A 0.5 m grid alone can never put a 1 m desk against the wall (face at 0.112 m);
    the magnet does."""
    walls = pl.wall_obstacles(_map())
    x, y, ok, what = pl.settle(_prop(0, 0), 0.6, 1.5, walls, step=0.5)
    assert ok and what == "wall" and abs(x - (WALL_HALF + 0.5)) < 1e-9


def test_settle_moves_out_of_a_prop():
    walls = pl.wall_obstacles(_map())
    other = pl.footprint(_prop(1.5, 1.5))
    x, y, ok, _ = pl.settle(_prop(0, 0), 1.6, 1.5, walls, [other], step=0.1, use_magnet=False)
    assert ok and not pl.collides(pl.footprint(_prop(x, y)), walls, [other])
    assert abs(x - 1.6) <= pl.SEARCH + 1e-9 and abs(y - 1.5) <= pl.SEARCH + 1e-9


def test_settle_reports_no_room():
    walls = pl.wall_obstacles(_map())
    big = _prop(0, 0, w=2.9, h=2.9)
    _, _, ok, _ = pl.settle(big, 1.5, 1.5, walls, step=0.1)
    assert not ok


def test_free_mode_allows_overlap():
    walls = pl.wall_obstacles(_map())
    x, y, ok, _ = pl.settle(_prop(0, 0), 0.3, 1.5, walls, step=0, use_magnet=False,
                            no_overlap=False)
    assert ok and (x, y) == (0.3, 1.5)


def test_floor_limit():
    cells = {(i, j): 1 for i in range(ROOM) for j in range(ROOM)}
    assert pl.on_floor(pl.footprint(_prop(1.5, 1.5)), cells)
    assert not pl.on_floor(pl.footprint(_prop(2.9, 1.5)), cells)


@pytest.mark.parametrize("step", [0.5, 0.25, 0.1, 0.05])
def test_snap(step):
    assert abs(pl.snap(1.234, step) / step - round(pl.snap(1.234, step) / step)) < 1e-9


def test_contains_with_pad():
    poly = pl.footprint(_prop(1.0, 1.0, w=1.0, h=0.5))
    assert pl.contains(poly, 1.4, 1.2)
    assert not pl.contains(poly, 1.6, 1.0)
    assert pl.contains(poly, 1.53, 1.0, pad=0.05)
