"""Tests for scene_editor.py Editor logic (non-GUI parts)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _make_editor_data(nx=4, ny=4):
    return {
        "grid": [nx, ny],
        "cells": {},
        "vedges": {},
        "hedges": {},
        "furniture": [],
        "structure": {},
        "cur_yaw": 0.0,
        "place_shape": "bbox",
    }


class TestMapData:
    def test_map_data_roundtrip(self):
        data = _make_editor_data(5, 5)
        data["cells"] = {"0,0": 1, "1,1": 2}
        data["vedges"] = {"1,0": 1}
        data["hedges"] = {"0,1": 2}
        data["furniture"] = [{"asset": "SM_Chair", "x": 1.5, "y": 1.5, "yaw": 0}]
        from utils import ikey
        cells = ikey(data["cells"])
        assert cells[(0, 0)] == 1
        assert cells[(1, 1)] == 2


class TestValidateMap:
    def test_validate_empty(self):
        from scene_editor import Editor
        e = Editor.__new__(Editor)
        e.cells = {}
        e.vedges = {}
        e.hedges = {}
        e.furniture = []
        e.nx = 4
        e.ny = 4
        warnings = e.validate_map()
        assert len(warnings) > 0
        assert any("san" in w.lower() for w in warnings)

    def test_validate_out_of_bounds_furniture(self):
        from scene_editor import Editor
        e = Editor.__new__(Editor)
        e.cells = {(0, 0): 1}
        e.vedges = {}
        e.hedges = {}
        e.furniture = [{"asset": "SM_Chair", "x": 999, "y": 999}]
        e.nx = 4
        e.ny = 4
        warnings = e.validate_map()
        assert any("ngoai luoi" in w for w in warnings)


class TestFilteredPalette:
    def test_all_category(self):
        from scene_editor import Editor
        e = Editor.__new__(Editor)
        e.palette = [("SM_Chair", 0.5), ("SM_Sofa", 1.1), ("SM_Printer", 0.4)]
        e._pal_cat = "Tat ca"
        e._pal_filter = ""
        fp = e.filtered_palette()
        assert len(fp) == 3

    def test_search_filter(self):
        from scene_editor import Editor
        e = Editor.__new__(Editor)
        e.palette = [("SM_Chair", 0.5), ("SM_Sofa", 1.1), ("SM_Printer", 0.4)]
        e._pal_cat = "Tat ca"
        e._pal_filter = "chair"
        fp = e.filtered_palette()
        assert len(fp) == 1
        assert fp[0][0] == "SM_Chair"

    def test_category_filter(self):
        from scene_editor import Editor
        from config import FURNITURE_CATEGORIES
        e = Editor.__new__(Editor)
        # use real palette names
        all_names = []
        for cat, items in FURNITURE_CATEGORIES.items():
            for n in items:
                all_names.append((n, 0.5))
        e.palette = all_names
        # pick first category
        cat_name = list(FURNITURE_CATEGORIES.keys())[0]
        e._pal_cat = cat_name
        e._pal_filter = ""
        fp = e.filtered_palette()
        expected = FURNITURE_CATEGORIES[cat_name]
        assert len(fp) == len(expected)

    def test_combined_filter(self):
        from scene_editor import Editor
        e = Editor.__new__(Editor)
        e.palette = [("SM_Chair", 0.5), ("SM_Sofa", 1.1), ("SM_Printer", 0.4)]
        e._pal_cat = "Tat ca"
        e._pal_filter = "sofa"
        fp = e.filtered_palette()
        assert len(fp) == 1
        assert fp[0][0] == "SM_Sofa"
