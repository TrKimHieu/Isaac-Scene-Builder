"""
robots.py - Robot models (footprint, height, drive) from data/robots/<id>.json.

Imported by tools/import_robots.py from navsim presets (JetAuto Pro, TurtleBot 3/4) and the
NVIDIA jetbot.usd mesh (JetBot). Robot frame: x forward, y left, origin = rotation centre.

map_data["robot"]["model"] picks the robot of a map (default DEFAULT_ROBOT); the editor
draws its footprint at the spawn, the generator keeps paths wide enough for it and the
Nav2 export writes its footprint.
"""
import glob
import json
import math
import os

from config import PROJECT_ROOT

ROBOTS_DIR = os.path.join(PROJECT_ROOT, "data", "robots")
DEFAULT_ROBOT = "jetauto_pro"
ORDER = ["jetauto_pro", "jetbot", "turtlebot3_burger", "turtlebot3_waffle_pi", "turtlebot4",
         "turtlebot4_lite"]
SHORT = {"jetauto_pro": "JetAuto Pro", "jetbot": "JetBot", "turtlebot3_burger": "TB3 Burger",
         "turtlebot3_waffle_pi": "TB3 Waffle Pi", "turtlebot4": "TurtleBot 4",
         "turtlebot4_lite": "TB4 Lite"}
CLEARANCE = 0.05     # extra margin kept around the robot when planning (m)

_cache = None


def normalize(spec):
    """Footprint as a polygon (rectangle/circle converted) + r_circ / r_insc."""
    spec = dict(spec)
    fp = dict(spec["footprint"])
    if fp["type"] == "rectangle":
        L, W = fp["length"] / 2.0, fp["width"] / 2.0
        fp["points"] = [[L, -W], [L, W], [-L, W], [-L, -W]]
    elif fp["type"] == "circle":
        r = fp["radius"]
        fp["points"] = [[round(r * math.cos(a), 4), round(r * math.sin(a), 4)]
                        for a in (2 * math.pi * k / 24 for k in range(24))]
    spec["footprint"] = fp
    pts = fp["points"]
    spec["r_circ"] = round(max(math.hypot(x, y) for x, y in pts), 4)
    spec["r_insc"] = round(_inradius(pts), 4)
    return spec


def _inradius(pts):
    """Distance from the origin to the nearest footprint edge."""
    best = 1e9
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def load_robots(refresh=False):
    """{id: spec} in ORDER (unknown ids after)."""
    global _cache
    if _cache is None or refresh:
        specs = {}
        for p in glob.glob(os.path.join(ROBOTS_DIR, "*.json")):
            with open(p, encoding="utf-8") as fh:
                s = normalize(json.load(fh))
            specs[s["id"]] = s
        rank = {k: i for i, k in enumerate(ORDER)}
        _cache = dict(sorted(specs.items(), key=lambda kv: (rank.get(kv[0], 99), kv[0])))
    return _cache


def get(rid=None):
    """Spec of `rid` (falls back to DEFAULT_ROBOT, then any robot); None if none imported."""
    specs = load_robots()
    return specs.get(rid or DEFAULT_ROBOT) or specs.get(DEFAULT_ROBOT) or next(iter(specs.values()), None)


def model_of(map_data):
    return ((map_data or {}).get("robot") or {}).get("model") or DEFAULT_ROBOT


def label(rid):
    return SHORT.get(rid) or (get(rid) or {}).get("name", rid)


def plan_radius(spec):
    """Radius kept free around obstacles when checking reachability."""
    return (spec["r_circ"] if spec else 0.23) + CLEARANCE


def place(spec, x, y, yaw_deg):
    """Footprint corners in world coordinates for a pose (yaw in degrees)."""
    a = math.radians(yaw_deg)
    c, s = math.cos(a), math.sin(a)
    return [(x + c * px - s * py, y + s * px + c * py) for px, py in spec["footprint"]["points"]]


def convex_hull(pts):
    """Convex hull (CCW) of 2D points."""
    pts = sorted(set((float(x), float(y)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def nav2_polygon(spec, max_pts=16):
    """Footprint for Nav2: the convex hull of the outline (covers notches between wheels),
    thinned to max_pts by dropping the hull points whose removal loses the least area."""
    hull = convex_hull(spec["footprint"]["points"])
    while len(hull) > max_pts:
        def loss(i):
            (ax, ay), (bx, by), (cx, cy) = hull[i - 1], hull[i], hull[(i + 1) % len(hull)]
            return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
        hull.pop(min(range(len(hull)), key=loss))
    return hull


def nav2_footprint(spec):
    """Nav2 costmap `footprint` string."""
    return "[" + ", ".join("[%.3f, %.3f]" % (x, y) for x, y in nav2_polygon(spec)) + "]"


def footprint_svg(spec, px_per_m=1000):
    """Top-down SVG of the footprint (x forward = right, y left = up) with heading arrow."""
    pts = spec["footprint"]["points"]
    r = spec["r_circ"] * 1.15
    size = 2 * r * px_per_m

    def tr(x, y):
        return (x + r) * px_per_m, (r - y) * px_per_m
    poly = " ".join("%.1f,%.1f" % tr(x, y) for x, y in pts)
    cx, cy = tr(0, 0)
    tip = tr(spec["r_insc"] * 0.85, 0)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{s:.0f}" height="{s:.0f}" '
        'viewBox="0 0 {s:.1f} {s:.1f}">\n'
        '  <title>{name} footprint ({id}) - {w:.3f} x {l:.3f} m, r_circ {rc:.3f} m</title>\n'
        '  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="none" stroke="#c9bfae" '
        'stroke-dasharray="6 6" stroke-width="2"/>\n'
        '  <polygon points="{poly}" fill="#4e6a8a" stroke="#1c1f24" stroke-width="3"/>\n'
        '  <line x1="{cx:.1f}" y1="{cy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="#f3f0e9" '
        'stroke-width="6" stroke-linecap="round"/>\n'
        '  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="#a6814a"/>\n'
        '</svg>\n').format(
            s=size, name=spec.get("name", spec["id"]), id=spec["id"], poly=poly, cx=cx, cy=cy,
            tx=tip[0], ty=tip[1], rr=spec["r_circ"] * px_per_m, rc=spec["r_circ"],
            w=max(p[1] for p in pts) - min(p[1] for p in pts),
            l=max(p[0] for p in pts) - min(p[0] for p in pts))
