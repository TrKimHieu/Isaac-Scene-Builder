"""
slice_footprints.py - Height-sliced occupancy footprint of every prop, from its real mesh.

For each prop, every triangle is clipped to the slab z0 <= z <= z1 (m above the prop's
origin, i.e. above the floor once placed) and the clipped part is projected to XY and rasterized. The mask uses the same
convention as the top-down captures (square frame centered on the prop origin, row grows
with +Y, object = 0 / free = 255), so the BEV exporter stamps it the same way:
    output/mesh_shapes/slice_<z0>-<z1>/<asset>.png  +  <asset>.json {frame_m, mpp, z}

Needs OpenUSD only (usd_runtime: Isaac Sim's bundled USD, no Kit start).
    python tools/slice_footprints.py                 # library + Office palette, z 0.05-0.50
    python tools/slice_footprints.py --z 0.05 1.80   # a taller robot
    python tools/slice_footprints.py AV_Steam SM_ChairOffice
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from usd_runtime import pxr_available  # noqa: E402
from config import SLICE_Z, SLICE_MPP, slice_dir, FURNITURE, EXTRA_FURNITURE  # noqa: E402
import shape_tools as st  # noqa: E402
import scene_builder as sb  # noqa: E402
from utils import load_library  # noqa: E402


def mesh_triangles(path):
    """World-space triangles (N, 3, 3) in meters, Z-up, of all renderable meshes."""
    from pxr import Usd, UsdGeom
    stage = Usd.Stage.Open(path)
    mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    up_y = UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    tris = []
    for pr in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if not pr.IsA(UsdGeom.Mesh):
            continue
        img = UsdGeom.Imageable(pr)
        if img.ComputeVisibility() == UsdGeom.Tokens.invisible or \
                img.ComputePurpose() in (UsdGeom.Tokens.guide, UsdGeom.Tokens.proxy):
            continue
        m = UsdGeom.Mesh(pr)
        pts = m.GetPointsAttr().Get()
        cnt = m.GetFaceVertexCountsAttr().Get()
        idx = m.GetFaceVertexIndicesAttr().Get()
        if not pts or not cnt or not idx:
            continue
        P = np.asarray(pts, dtype=np.float64)
        M = np.asarray(cache.GetLocalToWorldTransform(pr), dtype=np.float64)   # row-vector
        P = np.c_[P, np.ones(len(P))] @ M
        P = P[:, :3] * mpu
        if up_y:                                 # Y-up -> Z-up (rotate +90 deg about X)
            P = np.c_[P[:, 0], -P[:, 2], P[:, 1]]
        cnt = np.asarray(cnt)
        idx = np.asarray(idx)
        starts = np.r_[0, np.cumsum(cnt)[:-1]]
        for k in range(3, int(cnt.max()) + 1):   # fan-triangulate polygons by size
            sel = starts[cnt == k]
            if not len(sel):
                continue
            for f in range(1, k - 1):
                tris.append(np.stack([P[idx[sel]], P[idx[sel + f]], P[idx[sel + f + 1]]], 1))
    if not tris:
        return np.zeros((0, 3, 3))
    return np.concatenate(tris)


def _clip_poly(poly, z, keep_above):
    """Sutherland-Hodgman against the plane Z = z on one triangle/polygon (list of xyz)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ina = a[2] >= z if keep_above else a[2] <= z
        inb = b[2] >= z if keep_above else b[2] <= z
        if ina:
            out.append(a)
        if ina != inb:
            t = (z - a[2]) / (b[2] - a[2])
            out.append(a + (b - a) * t)
    return out


def slice_mask(tris, z0, z1, mpp=SLICE_MPP):
    """(mask PIL 'L' object=0, frame_m) of the triangles' part inside z0..z1 (m above the
    prop origin = the floor once placed, as scene_builder places props at z=0)."""
    if not len(tris):
        return None, None
    T = tris
    zmin, zmax = T[..., 2].min(1), T[..., 2].max(1)
    hit = (zmax >= z0) & (zmin <= z1)
    T = T[hit]
    if not len(T):
        return None, None
    lo, hi = T[..., :2].reshape(-1, 2).min(0), T[..., :2].reshape(-1, 2).max(0)
    frame = st.pick_frame((lo[0], lo[1], 0), (hi[0], hi[1], 0))
    W = int(round(frame / mpp))
    img = Image.new("L", (W, W), 255)
    d = ImageDraw.Draw(img)

    def px(p):
        return ((p[0] + frame / 2) / mpp, (p[1] + frame / 2) / mpp)
    zmin, zmax = T[..., 2].min(1), T[..., 2].max(1)
    inside = (zmin >= z0) & (zmax <= z1)
    for tri in T[inside]:                          # fully inside the slab
        d.polygon([px(p) for p in tri], fill=0, outline=0)
    for tri in T[~inside]:                         # crosses z0 and/or z1: clip
        poly = list(tri)
        poly = _clip_poly(poly, z0, True)
        if len(poly) >= 2:
            poly = _clip_poly(poly, z1, False)
        if len(poly) >= 2:
            d.polygon([px(p) for p in poly], fill=0, outline=0)
    return img, frame


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--z", nargs=2, type=float, default=list(SLICE_Z), metavar=("Z0", "Z1"))
    ap.add_argument("--mpp", type=float, default=SLICE_MPP)
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
    if not pxr_available():
        raise SystemExit("OpenUSD not found: install Isaac Sim (C:\\isaacsim / $ISAACSIM)")
    names = args.names or (list(dict.fromkeys([n for n, _ in FURNITURE] + list(EXTRA_FURNITURE)))
                           + sorted(load_library()))
    out_dir = slice_dir(args.z)
    os.makedirs(out_dir, exist_ok=True)
    done, empty, fail = 0, [], []
    t0 = time.time()
    for k, name in enumerate(names, 1):
        png = os.path.join(out_dir, name + ".png")
        if args.skip_existing and os.path.isfile(png):
            continue
        path = sb.asset_abs(name)
        if not path:
            fail.append(name)
            continue
        try:
            img, frame = slice_mask(mesh_triangles(path), args.z[0], args.z[1], args.mpp)
        except Exception as e:                      # keep going; report at the end
            fail.append("%s (%s)" % (name, e))
            continue
        if img is None:                             # nothing in the slab (e.g. wall lamp)
            img, frame = Image.new("L", (300, 300), 255), 3.0
            empty.append(name)
        img.save(png)
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"frame_m": frame, "mpp": frame / img.width, "z": list(args.z)}, fh)
        done += 1
        if k % 25 == 0:
            print("  %d/%d (%.0f s)" % (k, len(names), time.time() - t0), flush=True)
    print("Slice z=%.2f..%.2f m: %d mask -> %s" % (args.z[0], args.z[1], done, out_dir))
    if empty:
        print("  khong co gi trong dai do cao (%d): %s" % (len(empty), ", ".join(empty[:15])))
    if fail:
        print("  loi (%d): %s" % (len(fail), ", ".join(fail[:10])))


if __name__ == "__main__":
    main()
