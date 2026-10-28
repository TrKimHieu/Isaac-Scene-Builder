"""Tests for config.py — centralized constants."""
from config import (
    PROJECT_ROOT, SRC_DIR, ASSETS_DIR, OUTPUT_DIR, SCENES_DIR, BEV_DIR,
    MAPS_DIR, SHAPES_JSON, CATALOG_DIR, MESH_DIR, RENDER_DIR,
    CELL, KIT_M, WALL_H, FLOOR, CEILING, WALL, WALL_DOOR, LIGHT_MESH, REQUIRED,
    FURNITURE, FURNITURE_CATEGORIES, EXTRA_FURNITURE, STRUCTURE_CHOICES,
    BEV_SCALE, WALL_M, DOOR_GAP, UNKNOWN, FREE, OCC,
    WHITE_TOL, SAT_TOL,
)
import os


def test_project_root_exists():
    assert os.path.isdir(PROJECT_ROOT)


def test_src_dir_exists():
    assert os.path.isdir(SRC_DIR)


def test_cell_is_positive():
    assert CELL > 0


def test_wall_h_equals_cell():
    assert WALL_H == KIT_M          # one kit module tall; cells are 1 m


def test_required_assets_listed():
    assert len(REQUIRED) == 5
    for name in REQUIRED:
        assert isinstance(name, str) and len(name) > 0


def test_furniture_catalog():
    assert len(FURNITURE) > 0
    for name, radius in FURNITURE:
        assert isinstance(name, str)
        assert isinstance(radius, float)
        assert 0.1 <= radius <= 5.0


def test_furniture_categories_cover_all():
    categorized = set()
    for items in FURNITURE_CATEGORIES.values():
        categorized.update(items)
    for name, _ in FURNITURE:
        assert name in categorized, "Furniture %s not in any category" % name


def test_bev_constants():
    assert BEV_SCALE > 0
    assert 0 < WALL_M < 1.0
    assert len(DOOR_GAP) == 2
    assert FREE > OCC
    assert UNKNOWN != FREE


def test_structure_choices_nonempty():
    for key in ("wall", "floor"):
        assert len(STRUCTURE_CHOICES[key]) > 0


def test_extra_furniture_no_overlap_with_furniture():
    base_names = {n for n, _ in FURNITURE}
    for n in EXTRA_FURNITURE:
        assert n not in base_names, "EXTRA overlaps FURNITURE: %s" % n


def test_thresholds_positive():
    assert WHITE_TOL > 0
    assert SAT_TOL > 0


def test_project_path():
    from config import project_path
    p = project_path("data")
    assert os.path.isdir(p)
