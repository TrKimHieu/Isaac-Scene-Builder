"""
build_furniture_shapes.py - Tu dong trich xuat shape cho cac FURNITURE (prop dung
trong scene) tu anh BEV render nen trang.

Voi moi furniture co anh render:
  - Bounding BOX: w, h (met) tu vung khong-trang (auto-fit).
  - Bounding SPHERE: r (met) = ban kinh hinh tron tam-tai-goc bao het object.
  - MESH footprint: cat (object=den, nen=trang) -> mesh_shapes/<asset>.png.
Ghi tat ca vao data/props_shapes.json (shape mac dinh = bbox) de
scene_editor.py dung lam mac dinh khi dat prop.

Chi xu ly furniture trong palette sb.FURNITURE (= furniture co the dat vao scene).
Cach dung:
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

    print("=== Da trich xuat shape cho %d furniture ===" % len(done))
    print("%-24s %8s %8s %8s" % ("asset", "W(m)", "H(m)", "R(m)"))
    for name, w, h, r in done:
        print("%-24s %8.3f %8.3f %8.3f" % (name, w, h, r))
    if blank:
        print("\n[bo qua - anh trang, khong footprint]:", ", ".join(blank))
    if missing:
        print("\n[thieu anh render]:", ", ".join(missing))
    print("\nDa ghi:", bev.SHAPES_JSON)
    print("Mesh footprint -> ", MESH_DIR)


if __name__ == "__main__":
    main()
