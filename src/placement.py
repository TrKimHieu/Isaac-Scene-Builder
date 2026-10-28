"""
placement.py - Furniture placement geometry for the editor (pure, no pygame).

All in map meters (x right, y down on the plan - the USD world X/Y), yaw in degrees with the
same convention as utils.bbox_corners / the editor drawing.

  footprint(f)            convex polygon of a placed prop (bbox / sphere / mesh -> its w x h box)
  wall_obstacles(map)     axis-aligned rectangles of walls, doorways, windows, glass, open door
                          leaves (doorways count: a prop may not block a door)
  collides(poly, ...)     SAT overlap test; touching (flush) is not a collision
  magnet(f, ...)          slide a prop flush against the nearest wall / prop face within reach
  settle(f, ...)          snap -> magnet -> nearest free spot; what the editor uses for every move
"""
import math

import architecture as arch
from config import CELL, WALL_HALF
from utils import bbox_corners

GLASS_HALF = 0.05        # half thickness of a glass partition (m)
LEAF_HALF = 0.03         # half thickness of an open door leaf (m)
TOUCH = 0.002            # penetration below this is "touching", not overlapping (m)
MAGNET = 0.25            # reach of the wall / prop magnet (m)
SEARCH = 0.6             # how far settle() looks for a free spot (m)
SNAP_STEPS = (0.5, 0.25, 0.1, 0.05, 0.0)       # 0 = free


def footprint(f):
    """Convex polygon [(x, y), ...] of a prop dict {x, y, yaw, shape, w, h, r}."""
    x, y, yaw = float(f["x"]), float(f["y"]), float(f.get("yaw", 0.0))
    if f.get("shape") == "sphere":
        r = float(f.get("r", 0.4))
        return [(x + r * math.cos(2 * math.pi * k / 16), y + r * math.sin(2 * math.pi * k / 16))
                for k in range(16)]
    return bbox_corners(x, y, float(f.get("w", 0.8)), float(f.get("h", 0.8)), yaw)


def aabb(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _rect(x0, y0, x1, y1, half):
    """Axis-aligned rectangle around an axis-aligned segment, `half` thick on each side."""
    return (min(x0, x1) - half, min(y0, y1) - half, max(x0, x1) + half, max(y0, y1) + half)


def wall_obstacles(map_data):
    """[(xmin, ymin, xmax, ymax), ...] of every edge (doorways included) and open door leaf."""
    out = []
    for kind, x0, y0, x1, y1 in arch.bev_edges(map_data):
        half = GLASS_HALF if kind == "glass" else WALL_HALF
        if x0 == x1:                    # a wall end is only half a panel past the grid line
            out.append((x0 - half, min(y0, y1), x0 + half, max(y0, y1)))
        else:
            out.append((min(x0, x1), y0 - half, max(x0, x1), y0 + half))
    for x0, y0, x1, y1 in arch.door_leaves(map_data):     # (bounding box if swung at an angle)
        out.append(_rect(x0, y0, x1, y1, LEAF_HALF))
    return out


def rect_poly(r):
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _axes(poly):
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L > 1e-9:
            yield (-ey / L, ex / L)


def penetration(a, b):
    """Smallest overlap depth of two convex polygons along their separating-axis candidates;
    <= 0 when they are apart."""
    depth = float("inf")
    for ax in list(_axes(a)) + list(_axes(b)):
        pa = [p[0] * ax[0] + p[1] * ax[1] for p in a]
        pb = [p[0] * ax[0] + p[1] * ax[1] for p in b]
        d = min(max(pa), max(pb)) - max(min(pa), min(pb))
        if d <= 0:
            return d
        depth = min(depth, d)
    return depth


def collides(poly, walls, others=(), floor=None):
    """True if `poly` overlaps a wall rect, another prop polygon, or leaves the floor."""
    box = aabb(poly)
    for r in walls:
        if box[0] < r[2] and box[2] > r[0] and box[1] < r[3] and box[3] > r[1]:
            if penetration(poly, rect_poly(r)) > TOUCH:
                return True
    for o in others:
        ob = aabb(o)
        if box[0] < ob[2] and box[2] > ob[0] and box[1] < ob[3] and box[3] > ob[1]:
            if penetration(poly, o) > TOUCH:
                return True
    if floor is not None and not on_floor(poly, floor):
        return True
    return False


def contains(poly, x, y, pad=0.0):
    """Point inside a convex polygon, or within `pad` m of its edges."""
    n = len(poly)
    sign = 0
    inside = True
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        c = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if c != 0:
            s = 1 if c > 0 else -1
            if sign and s != sign:
                inside = False
                break
            sign = s
    if inside:
        return True
    for i in range(n):                   # near an edge
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        if math.hypot(ax + t * dx - x, ay + t * dy - y) <= pad:
            return True
    return False


def on_floor(poly, cells):
    """Every corner of the polygon (pulled 1 mm inwards) lies on a floor cell
    (cells: {(i, j): state})."""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    for x, y in poly:
        L = math.hypot(cx - x, cy - y) or 1.0
        x, y = x + (cx - x) / L * 0.001, y + (cy - y) / L * 0.001
        if not cells.get((int(math.floor(x / CELL)), int(math.floor(y / CELL)))):
            return False
    return True


def snap(v, step):
    return round(v / step) * step if step > 0 else v


def magnet(f, walls, others=(), reach=MAGNET):
    """(x, y, what) with the prop slid flush against the nearest face (per axis) within
    `reach`; what = "wall" / "prop" / None. Faces come from wall rects and from the bounding
    boxes of the other props; a face only pulls when the prop runs alongside it."""
    poly = footprint(f)
    x0, y0, x1, y1 = aabb(poly)
    faces = [(r, "wall") for r in walls] + [(aabb(o), "prop") for o in others]
    best_x, best_y = None, None
    for (rx0, ry0, rx1, ry1), what in faces:
        if min(y1, ry1) - max(y0, ry0) > 0.05:          # side by side along x
            for d in (rx0 - x1, rx1 - x0):              # touch its left face / its right face
                if abs(d) <= reach and (best_x is None or abs(d) < abs(best_x[0])):
                    best_x = (d, what)
        if min(x1, rx1) - max(x0, rx0) > 0.05:          # side by side along y
            for d in (ry0 - y1, ry1 - y0):
                if abs(d) <= reach and (best_y is None or abs(d) < abs(best_y[0])):
                    best_y = (d, what)
    x, y, what = float(f["x"]), float(f["y"]), None
    if best_x:
        x += best_x[0]
        what = best_x[1]
    if best_y:
        y += best_y[0]
        what = what or best_y[1]
    return x, y, what


def settle(f, raw_x, raw_y, walls, others=(), step=0.1, use_magnet=True, no_overlap=True,
           floor=None):
    """Where a prop dropped at (raw_x, raw_y) ends up: grid snap -> magnet -> if it then
    overlaps something, the nearest free spot within SEARCH (on the same grid).
    Returns (x, y, ok, what): ok False = no free spot (x, y is the snapped point);
    what = "wall" / "prop" when the magnet pulled it flush."""
    g = dict(f)
    g["x"], g["y"] = snap(raw_x, step), snap(raw_y, step)
    what = None
    if use_magnet:
        mx, my, what = magnet(g, walls, others)
        trial = dict(g, x=mx, y=my)
        if not no_overlap or not collides(footprint(trial), walls, others, floor):
            g = trial
        else:
            what = None
    if not no_overlap or not collides(footprint(g), walls, others, floor):
        return g["x"], g["y"], True, what
    # nearest free spot: rings of candidates around the snapped point
    d = step if step > 0 else 0.05
    best = None
    n = int(math.ceil(SEARCH / d))
    for ring in range(1, n + 1):
        for i in range(-ring, ring + 1):
            for j in range(-ring, ring + 1):
                if max(abs(i), abs(j)) != ring:
                    continue
                c = dict(g, x=g["x"] + i * d, y=g["y"] + j * d)
                if not collides(footprint(c), walls, others, floor):
                    dist = math.hypot(c["x"] - raw_x, c["y"] - raw_y)
                    if best is None or dist < best[0]:
                        best = (dist, c)
        if best is not None:
            c = best[1]
            if use_magnet:                               # free again: re-apply the magnet
                mx, my, w = magnet(c, walls, others)
                t = dict(c, x=mx, y=my)
                if not collides(footprint(t), walls, others, floor):
                    return mx, my, True, w
            return c["x"], c["y"], True, None
    return g["x"], g["y"], False, None


def wall_gap(f, walls):
    """Distance (m) from the prop's bounding box to the nearest wall face beside it."""
    x0, y0, x1, y1 = aabb(footprint(f))
    best = None
    for rx0, ry0, rx1, ry1 in walls:
        if min(y1, ry1) - max(y0, ry0) > 0:
            for d in (rx0 - x1, x0 - rx1):
                if d >= -TOUCH and (best is None or d < best):
                    best = d
        if min(x1, rx1) - max(x0, rx0) > 0:
            for d in (ry0 - y1, y0 - ry1):
                if d >= -TOUCH and (best is None or d < best):
                    best = d
    return None if best is None else max(0.0, best)
