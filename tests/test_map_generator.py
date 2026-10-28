"""Tests for map_generator.py (procedural maps) and its metrics."""
import json

import numpy as np
import pytest

import architecture as arch
import map_generator as mg
from config import CELL, EDGE_DOOR
from utils import bbox_corners


@pytest.fixture(scope="module")
def assets():
    a = mg.Assets()
    if not a.dims:
        pytest.skip("no measured assets (data/props_shapes.json)")
    return a


SIZES = {"office": (6, 5), "hospital": (6, 5), "warehouse": (6, 5), "residential": (4, 4)}


@pytest.fixture(scope="module", params=mg.THEMES)
def gen(request, assets):
    th = request.param
    return th, mg.generate_map(3, th, size=SIZES[th], density=0.2, assets=assets)


def test_deterministic(assets):
    a = mg.generate_map(11, "residential", size=(4, 4), density=0.2, assets=assets)
    b = mg.generate_map(11, "residential", size=(4, 4), density=0.2, assets=assets)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_rooms_tile_the_floor(gen):
    _, md = gen
    cells = {tuple(map(int, k.split(","))) for k in md["cells"]}
    covered = set()
    for rm in md["rooms"]:
        i0, j0, i1, j1 = rm["rect"]
        room = {(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)}
        assert not (room & covered)
        covered |= room
    assert covered == cells
    assert set(md["styles"]) == set(md["cells"])


def test_closed_shell_and_doors(gen):
    _, md = gen
    ve, he = __import__("scene_builder").boundary_edges(
        {tuple(map(int, k.split(","))): v for k, v in md["cells"].items()})
    walls = {("v",) + e for e in ve} | {("h",) + e for e in he}
    have = {(k, i, j) for k, i, j, t in arch.edges(md)}
    assert walls <= have                                  # building is closed
    assert sum(1 for *_e, t in arch.edges(md) if t == EDGE_DOOR) >= len(md["rooms"]) - 1


def test_furniture_inside_and_disjoint(gen):
    _, md = gen
    nx, ny = md["grid"]
    g = mg.Grid(md, nx, ny)
    total = np.zeros_like(g.free, dtype=int)
    from PIL import Image, ImageFilter
    for f in md["furniture"]:
        m = g.poly_mask(bbox_corners(f["x"], f["y"], f["w"], f["h"], f["yaw"]))
        # shrink by one pixel: JSON rounding may move an edge across one raster pixel
        m = np.asarray(Image.fromarray(np.where(m, 255, 0).astype("uint8"))
                       .filter(ImageFilter.MinFilter(3))) > 0
        assert not (m & ~g.free).any(), f["asset"]       # on the floor
        assert not (m & g.walls).any(), f["asset"]        # not in a wall
        total += m
    assert total.max() <= 1                               # no two items overlap


def test_robot_route_reachable(gen):
    th, md = gen
    m = mg.map_metrics(md)
    assert m["reachable_ratio"] >= mg.MIN_REACH - 0.02
    assert m["waypoints"] == len(md["rooms"])
    sp = md["robot"]["spawn"]
    assert 0 < sp["x"] < md["grid"][0] * CELL and 0 < sp["y"] < md["grid"][1] * CELL


def test_density_tracks_target(assets):
    lo = mg.map_metrics(mg.generate_map(5, "warehouse", size=(6, 5), density=0.08, assets=assets))
    hi = mg.map_metrics(mg.generate_map(5, "warehouse", size=(6, 5), density=0.3, assets=assets))
    assert hi["density"] > lo["density"]


def test_theme_contents(gen):
    th, md = gen
    names = " ".join(f["asset"] for f in md["furniture"])
    if th == "hospital":
        assert "HospitalBed" in names or "Gurney" in names
    if th == "warehouse":
        assert any(k in names for k in ("Rack", "Shelving", "Pallet", "Crate"))
    types = {r["type"] for r in md["rooms"]}
    assert types


def test_split_parts():
    import random
    rng = random.Random(0)
    for n in range(2, 20):
        parts = mg._split(n, rng)
        assert sum(parts) == n and all(p >= 2 for p in parts)


def test_entrance_swings_inwards(gen):
    _, md = gen
    for x0, y0, x1, y1 in arch.door_leaves(md):
        tx, ty = x1, y1                               # free edge of every open leaf
        i, j = int(tx // CELL), int(ty // CELL)
        assert "%d,%d" % (i, j) in md["cells"], (x0, y0, x1, y1)
