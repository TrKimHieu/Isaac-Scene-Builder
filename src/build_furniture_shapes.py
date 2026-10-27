"""
build_furniture_shapes.py - Auto-extract shapes for FURNITURE (props used
in scenes) from white-background BEV renders.

For each furniture that has a render (output/mesh_shapes/renders/<asset>.png):
  - Bounding BOX: w, h (m) from the non-white region (auto-fit).
  - Bounding SPHERE: r (m) = radius of an origin-centered circle enclosing the object.
  - MESH footprint: cut (object=black, bg=white) -> mesh_shapes/<asset>.png.
  - COLOR top-down: the render's own colors on the object, transparent elsewhere
    -> mesh_shapes/color/<asset>.png (same framing as the mesh mask).
Scale = frame_m / image width, frame_m from the render's <asset>.json sidecar
(renders without one are the legacy 3x3 m CELL frame).
Write everything to data/props_shapes.json (default shape = bbox) so
scene_editor.py uses it as the default when placing props.

Handles the curated palette, EXTRA_FURNITURE, assets/extra/ and the asset library.
Usage:
    python src/build_furniture_shapes.py            # every prop that has a render
    python src/build_furniture_shapes.py AV_Boat    # only these
"""
import os
import sys
import glob

import scene_builder as sb
import bev_export as bev
import shape_tools as st
from config import (FURNITURE, EXTRA_FURNITURE, PROP_DIRS, RENDER_DIR, MESH_DIR,
                    COLOR_DIR)
from utils import load_library


def _extra_prop_names():
    out = []
    for d in PROP_DIRS[1:]:
        if os.path.isdir(d):
            out += [os.path.splitext(os.path.basename(p))[0]
                    for p in sorted(glob.glob(os.path.join(d, "*.usd")))]
    return out


def measure(name, render_png):
    """Measure one render -> (w, h, r, frame_m) and write mesh + color PNGs; None if blank."""
    img = st.Image.open(render_png).convert("RGB")
    box = st.auto_bbox(img)
    if box is None:
        return None
    W = img.width
    frame_m = st.render_frame_m(render_png)
    w, h = st.bbox_to_wh(box, W, frame_m)
    r = st.radius_to_m(st.radius_from_center_px(img), W, frame_m)
    st.save_shape_png(st.cut_shape(img, None), name, MESH_DIR)
    os.makedirs(COLOR_DIR, exist_ok=True)
    st.color_cutout(img, None).save(os.path.join(COLOR_DIR, name + ".png"))
    bev.save_prop_shape(name, "bbox", w, h, r, mesh="mesh_shapes/%s.png" % name,
                        mesh_mpp=frame_m / float(W),
                        color="mesh_shapes/color/%s.png" % name)
    return w, h, r, frame_m


def main():
    if len(sys.argv) > 1:
        names = sys.argv[1:]
    else:
        names = ([n for (n, _r) in FURNITURE] + EXTRA_FURNITURE + _extra_prop_names()
                 + sorted(load_library()))
    seen = set()
    palette = [n for n in names if sb.asset_exists(n) and not (n in seen or seen.add(n))]
    done, missing, blank = [], [], []

    for name in palette:
        p = os.path.join(RENDER_DIR, name + ".png")
        if not os.path.isfile(p):
            missing.append(name)
            continue
        res = measure(name, p)
        if res is None:
            blank.append(name)
            continue
        done.append((name,) + res)

    print("=== Extracted shapes for %d furniture ===" % len(done))
    print("%-36s %7s %7s %7s %7s" % ("asset", "W(m)", "H(m)", "R(m)", "frame"))
    for name, w, h, r, f in done:
        print("%-36s %7.3f %7.3f %7.3f %6.1fm" % (name, w, h, r, f))
    if blank:
        print("\n[skipped - white image, no footprint]:", ", ".join(blank))
    if missing:
        print("\n[missing render] %d: %s" % (len(missing), ", ".join(missing[:30])
                                             + (" ..." if len(missing) > 30 else "")))
    print("\nDa ghi:", bev.SHAPES_JSON)
    print("Mesh footprint -> ", MESH_DIR)
    print("Color top-down -> ", COLOR_DIR)


if __name__ == "__main__":
    main()
