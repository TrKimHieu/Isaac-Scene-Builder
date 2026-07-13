"""Tests for scene_builder.py — map parsing, boundary detection, utilities."""
import os
import sys

from config import CELL
from utils import ikey


def _make_map(cells=None, vedges=None, hedges=None, furniture=None, nx=4, ny=4):
    return {
        "grid": [nx, ny],
        "cells": cells or {},
        "vedges": vedges or {},
        "hedges": hedges or {},
        "furniture": furniture or [],
    }


class TestParseMap:
    def test_basic(self):
        import scene_builder as sb
        m = _make_map(
            cells={"0,0": 1, "1,1": 2},
            vedges={"1,0": 1},
            hedges={"0,1": 2},
            furniture=[{"asset": "SM_Chair", "x": 1.5, "y": 1.5}],
        )
        nx, ny, cells, vedges, hedges, furn = sb.parse_map(m)
        assert nx == 4
        assert ny == 4
        assert cells[(0, 0)] == 1
        assert cells[(1, 1)] == 2
        assert vedges[(1, 0)] == 1
        assert hedges[(0, 1)] == 2
        assert len(furn) == 1
        assert furn[0]["asset"] == "SM_Chair"

    def test_empty_map(self):
        import scene_builder as sb
        m = _make_map()
        nx, ny, cells, vedges, hedges, furn = sb.parse_map(m)
        assert nx == 4 and ny == 4
        assert len(cells) == 0
        assert len(furn) == 0


class TestBoundaryEdges:
    def test_single_cell(self):
        import scene_builder as sb
        cells = {(0, 0): 1}
        ve, he = sb.boundary_edges(cells)
        # single cell: 4 boundary edges
        assert len(ve) == 2  # left=0,1 and right=1,1
        assert len(he) == 2  # bottom=0,0 and top=0,1

    def test_two_adjacent_cells(self):
        import scene_builder as sb
        cells = {(0, 0): 1, (1, 0): 1}
        ve, he = sb.boundary_edges(cells)
        # shared edge at x=1 is NOT a boundary
        # boundary: x=0 and x=2
        assert len(ve) == 2  # (0,0) and (2,0)
        assert len(he) == 4  # 2 top + 2 bottom

    def test_empty_cells(self):
        import scene_builder as sb
        ve, he = sb.boundary_edges({})
        assert len(ve) == 0
        assert len(he) == 0

    def test_l_shape(self):
        import scene_builder as sb
        cells = {(0, 0): 1, (1, 0): 1, (0, 1): 1}
        ve, he = sb.boundary_edges(cells)
        # L-shape has more boundary edges than rectangle
        assert len(ve) > 2
        assert len(he) > 2


class TestNextScenePath:
    def test_returns_path(self):
        import scene_builder as sb
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = sb.next_scene_path(directory=td, stem="test")
            assert p.endswith("test1.usd")
            assert os.path.basename(p) == "test1.usd"

    def test_increments(self):
        import scene_builder as sb
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # create test1.usd
            open(os.path.join(td, "test1.usd"), "w").close()
            p = sb.next_scene_path(directory=td, stem="test")
            assert "test2.usd" in p

    def test_skips_gap(self):
        import scene_builder as sb
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "test1.usd"), "w").close()
            open(os.path.join(td, "test3.usd"), "w").close()
            p = sb.next_scene_path(directory=td, stem="test")
            assert "test2.usd" in p
