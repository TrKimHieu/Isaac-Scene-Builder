"""Tests for bev_export.py — scene rows, CSV, shape helpers."""
import os
import csv

from config import CELL, FREE, OCC, UNKNOWN
from bev_export import scene_rows, norm_furni, default_shape, ROW_FIELDS


def _make_map(cells=None, vedges=None, hedges=None, furniture=None, nx=4, ny=4):
    return {
        "cell": CELL,
        "grid": [nx, ny],
        "cells": cells or {},
        "vedges": vedges or {},
        "hedges": hedges or {},
        "furniture": furniture or [],
    }


class TestSceneRows:
    def test_floor_row(self):
        m = _make_map(cells={(0, 0): 1})
        nx, ny, rows = scene_rows(m)
        assert nx == 4
        floors = [r for r in rows if r["kind"] == "floor"]
        assert len(floors) == 1
        assert floors[0]["shape"] == "box"

    def test_light_row(self):
        m = _make_map(cells={(0, 0): 2})
        _, _, rows = scene_rows(m)
        lights = [r for r in rows if r["kind"] == "light"]
        assert len(lights) == 1

    def test_wall_rows(self):
        m = _make_map(vedges={"1,0": 1})
        _, _, rows = scene_rows(m)
        walls = [r for r in rows if r["kind"] == "wall"]
        assert len(walls) == 1

    def test_door_rows(self):
        m = _make_map(hedges={"0,1": 2})
        _, _, rows = scene_rows(m)
        doors = [r for r in rows if r["kind"] == "door"]
        assert len(doors) == 1

    def test_prop_row(self):
        m = _make_map(furniture=[{"asset": "SM_Chair", "x": 1.5, "y": 1.5, "yaw": 45}])
        _, _, rows = scene_rows(m)
        props = [r for r in rows if r["kind"] == "prop"]
        assert len(props) == 1
        assert props[0]["name"] == "SM_Chair"
        assert props[0]["yaw"] == 45

    def test_empty_map(self):
        m = _make_map()
        nx, ny, rows = scene_rows(m)
        assert len(rows) == 0

    def test_row_fields(self):
        m = _make_map(cells={(0, 0): 1})
        _, _, rows = scene_rows(m)
        for r in rows:
            for field in ROW_FIELDS:
                assert field in r


class TestNormFurni:
    def test_minimal(self):
        f = {"asset": "SM_Chair"}
        n = norm_furni(f)
        assert n["asset"] == "SM_Chair"
        assert "x" in n and "y" in n and "yaw" in n
        assert "shape" in n and "w" in n and "h" in n and "r" in n

    def test_explicit_override(self):
        f = {"asset": "SM_Chair", "w": 2.0, "h": 3.0, "r": 1.0, "shape": "sphere"}
        n = norm_furni(f)
        assert n["w"] == 2.0
        assert n["h"] == 3.0
        assert n["r"] == 1.0
        assert n["shape"] == "sphere"


class TestDefaultShape:
    def test_returns_all_keys(self):
        d = default_shape("SM_Chair")
        assert "shape" in d and "w" in d and "h" in d and "r" in d
        assert d["shape"] in ("bbox", "sphere", "mesh")

    def test_known_asset(self):
        d = default_shape("SM_Chair")
        assert d["r"] > 0

    def test_unknown_asset(self):
        d = default_shape("NonExistent_asset_999")
        assert d["shape"] == "bbox"
        assert d["w"] > 0
