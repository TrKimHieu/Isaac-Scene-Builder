"""Tests for utils.py — shared helpers."""
import math
import os
import tempfile

from utils import safe_name, ikey, bbox_corners, meters_per_pixel, load_prop_shapes, save_prop_shapes


class TestSafeName:
    def test_ascii(self):
        assert safe_name("HelloWorld") == "HelloWorld"

    def test_spaces(self):
        assert safe_name("hello world") == "hello_world"

    def test_special_chars(self):
        assert safe_name("a@b#c!d") == "a_b_c_d"

    def test_empty(self):
        assert safe_name("") == ""

    def test_numbers(self):
        assert safe_name("item_123") == "item_123"


class TestIkey:
    def test_string_keys(self):
        d = {"0,1": "a", "2,3": "b"}
        result = ikey(d)
        assert result[(0, 1)] == "a"
        assert result[(2, 3)] == "b"

    def test_tuple_keys(self):
        d = {(0, 1): "a", (2, 3): "b"}
        result = ikey(d)
        assert result[(0, 1)] == "a"
        assert result[(2, 3)] == "b"

    def test_empty(self):
        assert ikey(None) == {}
        assert ikey({}) == {}

    def test_mixed(self):
        d = {"0,1": "a", (2, 3): "b"}
        result = ikey(d)
        assert len(result) == 2


class TestBboxCorners:
    def test_zero_rotation(self):
        pts = bbox_corners(0, 0, 2, 2, 0)
        assert len(pts) == 4
        # corners should be at (+-1, +-1)
        xs = sorted(p[0] for p in pts)
        ys = sorted(p[1] for p in pts)
        assert abs(xs[0] - (-1)) < 1e-9
        assert abs(xs[-1] - 1) < 1e-9
        assert abs(ys[0] - (-1)) < 1e-9
        assert abs(ys[-1] - 1) < 1e-9

    def test_90_rotation(self):
        pts = bbox_corners(0, 0, 4, 2, 90)
        # After 90 deg: (dx,dy)->(-dy,dx) => corners (±2,±1) -> (±1,±2)
        xs = sorted(p[0] for p in pts)
        assert abs(xs[0] - (-1)) < 1e-6
        assert abs(xs[-1] - 1) < 1e-6

    def test_center_offset(self):
        pts = bbox_corners(10, 20, 2, 2, 0)
        cx = sum(p[0] for p in pts) / 4
        cy = sum(p[1] for p in pts) / 4
        assert abs(cx - 10) < 1e-9
        assert abs(cy - 20) < 1e-9

    def test_360_same_as_zero(self):
        pts0 = bbox_corners(5, 5, 3, 2, 0)
        pts360 = bbox_corners(5, 5, 3, 2, 360)
        for p0, p360 in zip(pts0, pts360):
            assert abs(p0[0] - p360[0]) < 1e-9
            assert abs(p0[1] - p360[1]) < 1e-9


class TestMetersPerPixel:
    def test_basic(self):
        mpp = meters_per_pixel(100, 3.0)
        assert abs(mpp - 0.03) < 1e-9

    def test_non_default_cell(self):
        mpp = meters_per_pixel(200, 6.0)
        assert abs(mpp - 0.03) < 1e-9
