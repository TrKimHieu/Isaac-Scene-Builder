"""
build_furniture_shapes.py - Auto-extract shapes for FURNITURE (props used
in scenes) from white-background BEV renders.

For each furniture that has a render:
  - Bounding BOX: w, h (m) from the non-white region (auto-fit).
  - Bounding SPHERE: r (m) = radius of an origin-centered circle enclosing the object.
  - MESH footprint: cut (object=black, bg=white) -> mesh_shapes/<asset>.png.
Write everything to data/props_shapes.json (default shape = bbox) so
scene_editor.py uses it as the default when placing props.

Only handles furniture in the sb.FURNITURE palette (= placeable furniture).
Usage:
    python src/build_furniture_shapes.py
"""
import os
import glob

import scene_builder as sb
import bev_export as bev
import shape_tools as st
from config import FURNITURE, EXTRA_FURNITURE, PROP_DIRS, RENDER_DIR, MESH_DIR


def _extra_prop_names():
    out = []
    for d in PROP_DIRS[1:]:
        if os.path.isdir(d):
            out += [os.path.splitext(os.path.basename(p))[0]
                    for p in sorted(glob.glob(os.path.join(d, "*.usd")))]
    return out


def main():
    names = [n for (n, _r) in FURNITURE] + EXTRA_FURNITURE + _extra_prop_names()
    seen = set()
    palette = [n for n in names if sb.asset_exists(n) and not (n in seen or seen.add(n))]
    done, missing, blank = [], [], []

    for name in palette:
        p = os.path.join(RENDER_DIR, name + ".png")
        if not os.path.isfile(p):
            missing.append(name)
            continue
        img = st.Image.open(p).convert("RGB")
        box = st.auto_bbox(img)
        if box is None:
            blank.append(name)
            continue
        W = img.width
        w, h = st.bbox_to_wh(box, W)
        rpx = st.radius_from_center_px(img)
        r = st.radius_to_m(rpx, W)
        mask = st.cut_shape(img, None)
        st.save_shape_png(mask, name, MESH_DIR)
        rel = "mesh_shapes/%s.png" % name
        bev.save_prop_shape(name, "bbox", w, h, r, mesh=rel)
        done.append((name, w, h, r))

    print("=== Extracted shapes for %d furniture ===" % len(done))
    print("%-24s %8s %8s %8s" % ("asset", "W(m)", "H(m)", "R(m)"))
    for name, w, h, r in done:
        print("%-24s %8.3f %8.3f %8.3f" % (name, w, h, r))
    if blank:
        print("\n[skipped - white image, no footprint]:", ", ".join(blank))
    if missing:
        print("\n[missing render]:", ", ".join(missing))
    print("\nDa ghi:", bev.SHAPES_JSON)
    print("Mesh footprint -> ", MESH_DIR)


if __name__ == "__main__":
    main()
