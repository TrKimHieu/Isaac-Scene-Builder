"""
utils.py - Shared helper functions for Isaac Scene Builder.
"""
import os
import math
import json

from config import SHAPES_JSON


# ===========================================================================
# String / naming
# ===========================================================================
def safe_name(s):
    """Convert arbitrary string to a valid USD prim name."""
    import re
    return re.sub(r"[^A-Za-z0-9_]", "_", str(s))


# ===========================================================================
# Props shapes
# ===========================================================================
def load_prop_shapes():
    """Read props_shapes.json. Returns empty dict on failure."""
    try:
        with open(SHAPES_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


_LIBRARY = None


def load_library(reload=False):
    """Curated asset library (data/asset_manifest.json) -> {id: entry}.

    Only entries whose root file is on disk are returned; each entry gets an 'abs' path.
    """
    global _LIBRARY
    if _LIBRARY is not None and not reload:
        return _LIBRARY
    from config import ASSET_MANIFEST, LIBRARY_DIR
    out = {}
    try:
        with open(ASSET_MANIFEST, encoding="utf-8") as fh:
            assets = json.load(fh).get("assets", [])
    except Exception:
        assets = []
    for a in assets:
        p = os.path.join(LIBRARY_DIR, *a["root"].split("/"))
        if os.path.isfile(p):
            out[a["id"]] = dict(a, abs=p)
    _LIBRARY = out
    return out


def save_prop_shapes(data):
    """Write the full props_shapes dict to disk."""
    with open(SHAPES_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


# ===========================================================================
# Map key conversion
# ===========================================================================
def ikey(d):
    """Convert string keys 'i,j' -> tuple(int,int)."""
    out = {}
    for k, v in (d or {}).items():
        if isinstance(k, (tuple, list)):
            out[(int(k[0]), int(k[1]))] = v
        else:
            a, b = str(k).split(",")
            out[(int(a), int(b))] = v
    return out


# ===========================================================================
# Geometry helpers
# ===========================================================================
def bbox_corners(cx, cy, w, h, yaw_deg):
    """4 corners of a rectangle (center cx,cy) rotated by yaw_deg
    in screen coordinates (y-down)."""
    a = math.radians(yaw_deg)
    ca, sa = math.cos(a), math.sin(a)
    hw, hh = w / 2.0, h / 2.0
    pts = []
    for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        rx = cx + dx * ca - dy * sa
        ry = cy + dx * sa + dy * ca
        pts.append((rx, ry))
    return pts


def meters_per_pixel(img_w, cell=3.0):
    """Meters per pixel given image width and cell size in meters."""
    return float(cell) / float(img_w)
