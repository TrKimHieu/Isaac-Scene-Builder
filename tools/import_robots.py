"""
import_robots.py - Bring robot footprints into data/robots/ (<id>.json + <id>.svg).

Sources:
  * navsim presets (navsim/src/navsim/robots/presets/*.json): TurtleBot3 Burger / Waffle Pi,
    TurtleBot 4 / 4 Lite - footprint outline, height, drive, limits, LiDAR.
  * JetAuto Pro: navsim preset for height / drive / limits / LiDAR, but its footprint there is
    only a 0.324 x 0.26 m box centred on the base - the outline is traced from the robot's own
    mesh instead (JetRobots/assets/JetAuto/jetauto_pro.usd, arm folded).
  * JetBot is not in navsim: outline traced from the NVIDIA jetbot.usd mesh
    (JetRobots/assets/JetBot/jetbot.usd), limits from the Isaac example.

Mesh outline = top-down projection of every mesh of the robot (all heights), holes filled,
outer contour traced at OUTLINE_MPP and simplified to OUTLINE_EPS.
Robot frame: x forward, y left, origin = rotation centre (as in navsim).

Usage:
    python tools/import_robots.py [--navsim ../navsim] [--jetrobots ../JetRobots]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import robots  # noqa: E402

NAVSIM_IDS = ["jetauto_pro", "turtlebot3_burger", "turtlebot3_waffle_pi", "turtlebot4",
              "turtlebot4_lite"]
MESH_OUTLINE = {"jetauto_pro": os.path.join("assets", "JetAuto", "jetauto_pro.usd"),
                "jetbot": os.path.join("assets", "JetBot", "jetbot.usd")}
OUTLINE_MPP = 0.002     # raster resolution of the traced outline (m/px)
OUTLINE_EPS = 0.002     # Douglas-Peucker tolerance (m)
ROBOT_EXTENT = 1.5      # triangles farther than this from the origin (ground planes) are dropped

JETBOT = {
    "schema_version": "1.0",
    "id": "jetbot",
    "name": "NVIDIA JetBot",
    "drive": "differential",
    "limits": {"v_max": 0.2, "v_min": -0.2, "w_max": 2.0},
    "lidar": None,
    "sources": {
        "height": {"kind": "measured", "method": "Mesh z range of jetbot.usd (wheels to antennas)."},
        "limits": {"kind": "estimated",
                   "method": "Isaac jetbot differential example (wheel_radius 0.03, wheel_base 0.1125)."},
    },
}


def _trace(mask):
    """Outer boundary of a filled boolean mask (rows = y) as pixel-corner points, from the
    chained pixel edges that keep the object on one side; the longest loop wins."""
    m = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), bool)
    m[1:-1, 1:-1] = mask
    nxt = {}
    ys, xs = np.nonzero(m)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if not m[y - 1, x]:
            nxt.setdefault((x, y), []).append((x + 1, y))
        if not m[y, x + 1]:
            nxt.setdefault((x + 1, y), []).append((x + 1, y + 1))
        if not m[y + 1, x]:
            nxt.setdefault((x + 1, y + 1), []).append((x, y + 1))
        if not m[y, x - 1]:
            nxt.setdefault((x, y + 1), []).append((x, y))
    best = []
    while nxt:
        start = min(nxt)
        loop, cur = [start], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            nx_ = outs.pop()
            if not outs:
                del nxt[cur]
            if nx_ == start:
                break
            loop.append(nx_)
            cur = nx_
        if len(loop) > len(best):
            best = loop
    return [(x - 1, y - 1) for x, y in best]


def _dp(pts, eps):
    """Douglas-Peucker on an open polyline."""
    if len(pts) < 3:
        return list(pts)
    a, b = np.asarray(pts[0], float), np.asarray(pts[-1], float)
    P = np.asarray(pts, float)
    d = b - a
    n = float(np.hypot(*d))
    if n:
        dist = np.abs(d[0] * (P[:, 1] - a[1]) - d[1] * (P[:, 0] - a[0])) / n
    else:
        dist = np.hypot(P[:, 0] - a[0], P[:, 1] - a[1])
    k = int(dist.argmax())
    if dist[k] <= eps:
        return [pts[0], pts[-1]]
    return _dp(pts[:k + 1], eps)[:-1] + _dp(pts[k:], eps)


def mesh_outline(path, mpp=OUTLINE_MPP, eps=OUTLINE_EPS):
    """(outline [[x, y], ...] CCW in the robot frame, height m) of a robot USD."""
    from usd_runtime import pxr_available
    if not pxr_available():
        raise RuntimeError("OpenUSD (pxr) not available")
    from slice_footprints import mesh_triangles
    T = mesh_triangles(path)
    T = T[(np.abs(T[..., :2]) < ROBOT_EXTENT).all(axis=(1, 2))]       # drop ground planes
    if not len(T):
        raise RuntimeError("no robot meshes in %s" % path)
    lo = T[..., :2].reshape(-1, 2).min(0) - 4 * mpp
    hi = T[..., :2].reshape(-1, 2).max(0) + 4 * mpp
    W, H = (np.ceil((hi - lo) / mpp)).astype(int) + 1
    img = Image.new("L", (int(W), int(H)), 0)
    d = ImageDraw.Draw(img)
    for tri in (T[..., :2] - lo) / mpp:
        d.polygon([tuple(p) for p in tri], fill=255, outline=255)
    ImageDraw.floodfill(img, (0, 0), 128)                               # outside
    loop = _trace(np.asarray(img) != 128)                               # body + holes
    k = min(range(len(loop)), key=lambda i: loop[i])
    loop = loop[k:] + loop[:k]
    simp = _dp(loop + [loop[0]], eps / mpp)[:-1]
    pts = [[round(float(lo[0] + x * mpp), 4), round(float(lo[1] + y * mpp), 4)] for x, y in simp]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts.reverse()
    z = T[..., 2]
    return pts, round(float(z.max() - z.min()), 3)


def from_navsim(path):
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    spec["sources"] = dict(spec.get("sources") or {})
    spec["sources"]["import"] = {"kind": "navsim", "file": os.path.basename(path)}
    return spec


def write(spec, out_dir):
    """data/robots/<id>.json + .svg"""
    spec = robots.normalize(spec)
    base = os.path.join(out_dir, spec["id"])
    with open(base + ".json", "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=1)
    with open(base + ".svg", "w", encoding="utf-8") as fh:
        fh.write(robots.footprint_svg(spec))
    print("  %-22s %-9s %3d pts  r_circ %.3f  h %.3f m" % (
        spec["id"], spec["footprint"]["type"], len(spec["footprint"]["points"]),
        spec["r_circ"], spec["height"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--navsim", default=os.path.join(ROOT, "..", "navsim"))
    ap.add_argument("--jetrobots", default=os.path.join(ROOT, "..", "JetRobots"))
    ap.add_argument("--out", default=robots.ROBOTS_DIR)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    presets = os.path.join(args.navsim, "src", "navsim", "robots", "presets")
    print("navsim presets: %s" % os.path.abspath(presets))
    specs = {}
    for rid in NAVSIM_IDS:
        p = os.path.join(presets, rid + ".json")
        if os.path.isfile(p):
            specs[rid] = from_navsim(p)
        else:
            print("  [skip] %s not found" % rid)
    specs["jetbot"] = json.loads(json.dumps(JETBOT))

    for rid, rel in MESH_OUTLINE.items():
        if rid not in specs:
            continue
        usd = os.path.join(args.jetrobots, rel)
        try:
            pts, height = mesh_outline(usd)
        except Exception as exc:  # noqa: BLE001
            print("  [mesh] %s: %s" % (rid, exc))
            if "footprint" not in specs[rid]:
                specs.pop(rid)
            continue
        spec = specs[rid]
        old = spec.get("footprint")
        spec["footprint"] = {"type": "polygon", "points": pts}
        spec.setdefault("height", height)
        src = dict(spec.get("sources") or {})
        src["footprint"] = {"kind": "measured", "file": rel.replace(os.sep, "/"),
                            "method": "Top-down outline of the robot meshes (all heights), traced at "
                                      "%.0f mm, simplified to %.0f mm." % (OUTLINE_MPP * 1000,
                                                                         OUTLINE_EPS * 1000)}
        if old:
            src["footprint"]["replaces"] = old
        spec["sources"] = src
        print("  [mesh] %s outline: %d pts from %s" % (rid, len(pts), os.path.abspath(usd)))

    for rid in robots.ORDER:
        if rid in specs:
            write(specs[rid], args.out)


if __name__ == "__main__":
    main()
