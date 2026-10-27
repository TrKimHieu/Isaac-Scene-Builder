"""
bev_export.py - Export BEV (Bird's Eye View) from map_data: CSV + SVG (vector) + raster (PNG/PGM/YAML).

No pygame dependency. Uses Pillow for raster (PNG/PGM), plain text for SVG/CSV.
Reuses scene_builder for FURNITURE / CELL / parse_map.

Three-level grayscale convention (ROS map_server):
    205 = outside / unknown
    254 = free floor, walkable (free)
      0 = occupied: walls + objects (occupied)

Each prop has one of 3 shapes:
    bbox   -> w x h rectangle (m), rotated by yaw
    sphere -> circle of radius r (m)
    mesh   -> real top-down footprint (falls back to bbox if missing)

map_data schema: see scene_builder.py. Each furniture item may also carry
optional keys: "shape" ("bbox"|"sphere"|"mesh"), "w", "h", "r".
"""
import os
import csv
import json

import scene_builder as sb
import shape_tools as st
import architecture as arch

from config import (CELL, BEV_DIR, MESH_DIR, SHAPES_JSON, FURNITURE,
                    BEV_SCALE, WALL_M, DOOR_GAP, UNKNOWN, FREE, OCC, SLICE_Z, slice_dir)
from utils import load_prop_shapes, bbox_corners

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None


FOOT = dict(FURNITURE)


# Re-export for backward compatibility
def _bbox_corners(cx, cy, w, h, yaw_deg):
    return bbox_corners(cx, cy, w, h, yaw_deg)


# ----------------------------------------------------------------------------
# Shape helpers
# ----------------------------------------------------------------------------
def save_prop_shape(asset, shape, w, h, r, mesh=None, mesh_mpp=None, color=None):
    """Write/update the shape parameters of one asset in props_shapes.json.

    mesh_mpp: meters/pixel of the mesh PNG (its framing); color: colored top-down PNG.
    """
    shapes_dir = os.path.dirname(os.path.abspath(SHAPES_JSON))
    if not os.path.isdir(shapes_dir):
        os.makedirs(shapes_dir)
    data = load_prop_shapes()
    entry = {"shape": shape, "w": round(float(w), 3), "h": round(float(h), 3),
             "r": round(float(r), 3)}
    if mesh:
        entry["mesh"] = mesh
    if mesh_mpp:
        entry["mesh_mpp"] = round(float(mesh_mpp), 6)
    if color:
        entry["color"] = color
    data[asset] = entry
    with open(SHAPES_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return SHAPES_JSON


def default_shape(asset):
    """Default shape for one asset.

    Prefer manually-measured values in props_shapes.json; otherwise use a
    square bounding box = 2 x footprint radius from the FURNITURE table.
    """
    m = load_prop_shapes().get(asset)
    if m:
        r = float(m.get("r", FOOT.get(asset, 0.4)))
        return {"shape": m.get("shape", "bbox"),
                "w": float(m.get("w", 2.0 * r)),
                "h": float(m.get("h", 2.0 * r)), "r": r}
    r = FOOT.get(asset, 0.4)
    return {"shape": "bbox", "w": 2.0 * r, "h": 2.0 * r, "r": r}


def norm_furni(f):
    """Return a furniture dict with all shape fields filled (keep existing values)."""
    out = default_shape(f.get("asset", ""))
    out.update({"asset": f.get("asset", ""), "x": float(f.get("x", 0.0)),
                "y": float(f.get("y", 0.0)), "yaw": float(f.get("yaw", 0.0))})
    for k in ("shape", "w", "h", "r"):
        if f.get(k) is not None:
            out[k] = f[k]
    return out


# ----------------------------------------------------------------------------
# Scene -> list of rows (shared by CSV/SVG/raster)
# ----------------------------------------------------------------------------
ROW_FIELDS = ["kind", "name", "x", "y", "yaw", "shape", "w", "h", "r", "x2", "y2"]


def scene_rows(map_data):
    """Return a list of dicts (per ROW_FIELDS) describing the whole scene in meters."""
    nx, ny, cells, vedges, hedges, furniture = sb.parse_map(map_data)
    rows = []

    def row(**kw):
        r = {k: "" for k in ROW_FIELDS}
        r.update(kw)
        rows.append(r)

    # Floor (name = room style) + light
    styles = arch.cell_styles(map_data)
    for (i, j), s in sorted(cells.items()):
        if s < 1:
            continue
        cx, cy = (i + 0.5) * CELL, (j + 0.5) * CELL
        row(kind="floor", name=styles.get((i, j), ""), x=cx, y=cy, shape="box", w=CELL, h=CELL)
        if s == 2:
            row(kind="light", x=cx, y=cy)

    # Edges: wall / door (open) / door_closed / window / glass / opening
    for kind, x0, y0, x1, y1 in arch.bev_edges(map_data):
        row(kind=kind, x=x0, y=y0, x2=x1, y2=y1)
    for x0, y0, x1, y1 in arch.door_leaves(map_data):       # open leaves are obstacles
        row(kind="door_leaf", x=x0, y=y0, x2=x1, y2=y1)

    # Furniture
    for f in furniture:
        nf = norm_furni(f)
        row(kind="prop", name=nf["asset"], x=nf["x"], y=nf["y"], yaw=nf["yaw"],
            shape=nf["shape"], w=nf["w"], h=nf["h"], r=nf["r"])

    return nx, ny, rows


# ----------------------------------------------------------------------------
# CSV
# ----------------------------------------------------------------------------
def write_csv(map_data, path):
    _, _, rows = scene_rows(map_data)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ROW_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


# ----------------------------------------------------------------------------
# Shared geometry
# ----------------------------------------------------------------------------
EDGE_KINDS = ("wall", "door", "door_closed", "window", "glass", "opening")
GAP_KINDS = ("door", "opening")          # passable: drawn with the 0.94 m opening free
SVG_EDGE_COLOR = {"wall": "#000000", "door": "#000000", "opening": "#000000",
                  "door_closed": "#7a4a1d", "window": "#1d4e89", "glass": "#3aa0c8",
                  "door_leaf": "#7a4a1d"}
LEAF_M = 0.06                           # drawn thickness of an open door leaf (m)


def _edge_segments(r):
    """Solid segments of an edge row (gap kinds leave the door opening free)."""
    x0, y0 = float(r["x"]), float(r["y"])
    x1, y1 = float(r["x2"]), float(r["y2"])
    if r["kind"] in GAP_KINDS:
        return _door_segments(x0, y0, x1, y1)
    return [((x0, y0), (x1, y1))]


def _door_segments(x0, y0, x1, y1):
    """Split a wall-door segment into 2 solid parts (with a gap in the middle)."""
    f0, f1 = DOOR_GAP
    ax, ay = x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0
    bx, by = x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1
    return [((x0, y0), (ax, ay)), ((bx, by), (x1, y1))]


# ----------------------------------------------------------------------------
# SVG (vector)
# ----------------------------------------------------------------------------
def write_svg(map_data, path, scale=BEV_SCALE, margin_m=WALL_M):
    nx, ny, rows = scene_rows(map_data)
    m = margin_m * scale
    W = nx * CELL * scale + 2 * m
    H = ny * CELL * scale + 2 * m
    wall_px = max(1.0, WALL_M * scale)

    def X(x):
        return m + x * scale

    def Y(y):
        return m + y * scale

    out = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
               'viewBox="0 0 %g %g">' % (int(W), int(H), W, H))
    out.append('<rect x="0" y="0" width="%g" height="%g" fill="#cdcdcd"/>' % (W, H))
    for r in rows:
        if r["kind"] != "floor":
            continue
        cx, cy = float(r["x"]), float(r["y"])
        out.append('<rect x="%g" y="%g" width="%g" height="%g" fill="#fefefe"/>'
                   % (X(cx - CELL / 2), Y(cy - CELL / 2), CELL * scale, CELL * scale))
    for r in rows:
        if r["kind"] not in EDGE_KINDS + ("door_leaf",):
            continue
        width = max(1.0, LEAF_M * scale) if r["kind"] == "door_leaf" else wall_px
        for (ax, ay), (bx, by) in _edge_segments(r):
            out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" '
                       'stroke-width="%g" stroke-linecap="butt"/>'
                       % (X(ax), Y(ay), X(bx), Y(by), SVG_EDGE_COLOR[r["kind"]], width))
    for r in rows:
        if r["kind"] != "prop":
            continue
        cx, cy = float(r["x"]), float(r["y"])
        shape = r["shape"] or "bbox"
        if shape == "sphere":
            rr = float(r["r"]) * scale
            out.append('<circle cx="%g" cy="%g" r="%g" fill="#000000"/>' % (X(cx), Y(cy), rr))
        else:
            w, h = float(r["w"]), float(r["h"])
            pts = bbox_corners(cx, cy, w, h, float(r["yaw"]))
            pstr = " ".join("%g,%g" % (X(px), Y(py)) for px, py in pts)
            if shape == "mesh":
                out.append('<polygon points="%s" fill="none" stroke="#000000" '
                           'stroke-width="%g" stroke-dasharray="4"/>' % (pstr, max(1.0, wall_px / 2)))
            else:
                out.append('<polygon points="%s" fill="#000000"/>' % pstr)
    out.append('</svg>')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return int(W), int(H)


# ----------------------------------------------------------------------------
# Raster (PNG + PGM + YAML)
# ----------------------------------------------------------------------------
def write_raster(map_data, path_png, scale=BEV_SCALE, margin_m=WALL_M, slice_z=None):
    """Occupancy raster. PNG = editor orientation (row grows with +Y); the PGM + YAML pair
    is flipped so ROS map_server's map frame == the USD world frame (x, y).

    slice_z=(z0, z1): props are stamped with their height-sliced footprint
    (tools/slice_footprints.py) instead of the editor shape -> what a robot of that
    height really hits. Props without a slice mask fall back to their shape.
    """
    if Image is None:
        raise RuntimeError("Pillow (PIL) is not installed - cannot export raster.")
    nx, ny, rows = scene_rows(map_data)
    m = int(round(margin_m * scale))
    W = int(nx * CELL * scale) + 2 * m
    H = int(ny * CELL * scale) + 2 * m
    wall_px = max(1, int(round(WALL_M * scale)))

    def X(x):
        return m + x * scale

    def Y(y):
        return m + y * scale

    img = Image.new("L", (W, H), UNKNOWN)
    d = ImageDraw.Draw(img)

    for r in rows:
        if r["kind"] != "floor":
            continue
        cx, cy = float(r["x"]), float(r["y"])
        d.rectangle([X(cx - CELL / 2), Y(cy - CELL / 2),
                     X(cx + CELL / 2), Y(cy + CELL / 2)], fill=FREE)
    for r in rows:
        if r["kind"] not in EDGE_KINDS + ("door_leaf",):
            continue
        width = max(1, int(round(LEAF_M * scale))) if r["kind"] == "door_leaf" else wall_px
        for (ax, ay), (bx, by) in _edge_segments(r):
            d.line([X(ax), Y(ay), X(bx), Y(by)], fill=OCC, width=width)
    sdir = slice_dir(slice_z) if slice_z else None
    for r in rows:
        if r["kind"] != "prop":
            continue
        cx, cy = float(r["x"]), float(r["y"])
        shape = r["shape"] or "bbox"
        if sdir and _slice_stamp(sdir, r["name"], img, X(cx), Y(cy), float(r["yaw"]), scale):
            continue
        if shape == "sphere":
            rr = float(r["r"]) * scale
            d.ellipse([X(cx) - rr, Y(cy) - rr, X(cx) + rr, Y(cy) + rr], fill=OCC)
        elif shape == "mesh" and _mesh_stamp(r["name"], img, X(cx), Y(cy), float(r["yaw"]), scale):
            pass
        else:
            w, h = float(r["w"]), float(r["h"])
            pts = [(X(px), Y(py)) for px, py in bbox_corners(cx, cy, w, h, float(r["yaw"]))]
            d.polygon(pts, fill=OCC)

    img.save(path_png)
    stem, _ = os.path.splitext(path_png)
    pgm_path = stem + ".pgm"
    img.transpose(Image.FLIP_TOP_BOTTOM).save(pgm_path)       # ROS: first row = max y
    _write_yaml(stem + ".yaml", os.path.basename(pgm_path), 1.0 / scale, m, ny, scale)
    return W, H


def _slice_stamp(sdir, name, img, px, py, yaw, scale):
    """Stamp the height-sliced footprint slice_<z>/<name>.png (sidecar gives its mpp)."""
    if not name:
        return False
    p = os.path.join(sdir, name + ".png")
    try:
        with open(os.path.splitext(p)[0] + ".json", encoding="utf-8") as fh:
            mpp = float(json.load(fh)["mpp"])
    except Exception:
        return False
    return _mesh_stamp(name, img, px, py, yaw, scale, path=p, mpp=mpp)


def _mesh_stamp(name, img, px, py, yaw, scale, path=None, mpp=None):
    """Stamp a footprint mask (default mesh_shapes/<name>.png) onto img at (px,py)."""
    if not name:
        return False
    p = path or os.path.join(MESH_DIR, name + ".png")
    if not os.path.isfile(p):
        return False
    try:
        src = Image.open(p).convert("L")
        if mpp is None:
            mpp = st.mesh_mpp(load_prop_shapes().get(name), src.width)
        stamp = src.resize((max(1, int(round(src.width * mpp * scale))),
                            max(1, int(round(src.height * mpp * scale)))), Image.NEAREST)
        stamp = stamp.rotate(-yaw, expand=True, fillcolor=255)
        mask = stamp.point(lambda v: 255 if v < 128 else 0)
        occ = Image.new("L", stamp.size, OCC)
        img.paste(occ, (int(px - stamp.width / 2), int(py - stamp.height / 2)), mask)
        return True
    except Exception:
        return False


def _write_yaml(path, image_name, resolution, margin_px, ny, scale):
    # PGM is written flipped (first row = max y) -> map frame == USD world frame
    origin_x = -margin_px / scale
    origin_y = -margin_px / scale
    _ = ny
    txt = (
        "# BEV map for ROS map_server. Map frame == the USD scene world frame (x, y).\n"
        "image: %s\n"
        "resolution: %.6f\n"
        "origin: [%.4f, %.4f, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
    ) % (image_name, resolution, origin_x, origin_y)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(txt)


# ----------------------------------------------------------------------------
# Export tong hop
# ----------------------------------------------------------------------------
def export_scene(map_data, stem="scene", scale=BEV_SCALE):
    """Export CSV + SVG + PNG/PGM/YAML of one scene into its own output/bev/<stem>/.

    Each scene gets its own folder with the full {stem}.csv/.svg/.png/.pgm/.yaml.
    """
    if not os.path.isdir(MESH_DIR):
        os.makedirs(MESH_DIR)
    scene_dir = os.path.join(BEV_DIR, stem)   # moi scene 1 folder
    os.makedirs(scene_dir, exist_ok=True)

    csv_path = os.path.join(scene_dir, stem + ".csv")
    svg_path = os.path.join(scene_dir, stem + ".svg")
    png_path = os.path.join(scene_dir, stem + ".png")

    n_rows = write_csv(map_data, csv_path)
    write_svg(map_data, svg_path, scale=scale)
    W, H = write_raster(map_data, png_path, scale=scale)
    occ = None
    if os.path.isdir(slice_dir(SLICE_Z)):        # height-sliced occupancy (robot body)
        occ = os.path.join(scene_dir, "%s_occ_%.2f-%.2f.png" % (stem, SLICE_Z[0], SLICE_Z[1]))
        write_raster(map_data, occ, scale=scale, slice_z=SLICE_Z)
    import nav_export
    nav = nav_export.write_nav(map_data, scene_dir, stem,  # robot spawn / waypoints
                               os.path.splitext(os.path.basename(occ))[0] + ".yaml" if occ else None)

    nx, ny, rows = scene_rows(map_data)
    stats = {
        "dir": scene_dir,
        "csv": csv_path, "svg": svg_path, "png": png_path,
        "pgm": os.path.join(scene_dir, stem + ".pgm"),
        "yaml": os.path.join(scene_dir, stem + ".yaml"),
        "size": (W, H), "rows": n_rows, "occ": occ, "nav": nav,
        "floor": sum(1 for r in rows if r["kind"] == "floor"),
        "wall": sum(1 for r in rows if r["kind"] in EDGE_KINDS),
        "prop": sum(1 for r in rows if r["kind"] == "prop"),
    }
    return stats


if __name__ == "__main__":
    import glob
    from config import MAPS_DIR
    files = sorted(glob.glob(os.path.join(MAPS_DIR, "map*.json")))
    if files:
        with open(files[-1], encoding="utf-8") as fh:
            md = json.load(fh)
        print(export_scene(md, stem="bev_demo"))
    else:
        print("No map to demo.")
