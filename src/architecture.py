"""
architecture.py - Pure layout of the building shell (no USD / no pygame).

Turns map_data into a flat list of placements (asset, position, yaw, style slot) that
scene_builder.py instantiates, and describes edges for the BEV exporter.

Map additions (all optional, old maps load unchanged):
  "styles":       {"i,j": "hospital", ...}   room style per floor cell (default DEFAULT_STYLE)
  "default_style": "office"
  "door_default": "open" | "closed"
  "door_state":   {"v:i,j": "closed", "h:i,j": "open"}   per-door override
  edge values in vedges/hedges: 1 wall, 2 door, 3 window, 4 glass wall, 5 opening (no leaf)

Geometry (Office kit, see config.KIT): a vedge (i,j) runs from (iC, jC) along +Y, a hedge
(i,j) from (iC, jC) along +X (C = CELL). A wall is two back-to-back panels; each panel faces
one room and takes that room's wall style. Free wall ends get an end cap; corners / T /
crossings get a post closed by end caps on the open sides.
"""
import math

from config import (CELL, WALL_H, FLOOR, CEILING, LIGHT_MESH, KIT, WALL_HALF, DOOR_HINGE,
                    DOOR_HANDLE, DOOR_OPEN_DEG, DOOR_DEFAULT, STYLES, DEFAULT_STYLE,
                    EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING)
from utils import ikey

THICK = (EDGE_WALL, EDGE_DOOR, EDGE_OPENING)      # double-panel edges (22.4 cm)
# unit direction + yaw that maps a module's local +Y onto it
DIRS = {"N": ((0.0, 1.0), 0.0), "S": ((0.0, -1.0), 180.0),
        "E": ((1.0, 0.0), -90.0), "W": ((-1.0, 0.0), 90.0)}
# yaw that turns an end cap's outward face (local -Y) towards a direction
CAP_YAW = {"S": 0.0, "N": 180.0, "E": 90.0, "W": -90.0}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def edge_key(kind, i, j):
    """'v:i,j' / 'h:i,j' - key of an edge in door_state."""
    return "%s:%d,%d" % ("v" if kind in ("v", "vedge") else "h", i, j)


def _rot(v, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def _add(p, v, k=1.0):
    return (p[0] + v[0] * k, p[1] + v[1] * k)


def cell_styles(map_data):
    """{(i,j): style} for every floor cell (unknown names fall back to the default)."""
    default = map_data.get("default_style") or DEFAULT_STYLE
    if default not in STYLES:
        default = DEFAULT_STYLE
    painted = ikey(map_data.get("styles"))
    out = {}
    for (i, j), s in ikey(map_data.get("cells")).items():
        if s >= 1:
            st = painted.get((i, j), default)
            out[(i, j)] = st if st in STYLES else default
    return out


def door_is_open(map_data, kind, i, j):
    st = (map_data.get("door_state") or {}).get(edge_key(kind, i, j))
    return (st or map_data.get("door_default") or DOOR_DEFAULT) != "closed"


def edges(map_data):
    """[(kind 'v'|'h', i, j, edge_type)] for every non-empty edge, legacy remapped.

    Legacy maps could set structure.wall to a window module for the whole map: plain
    walls (1) are then built as windows.
    """
    wall_override = (map_data.get("structure") or {}).get("wall")
    as_window = bool(wall_override) and "Window" in wall_override
    out = []
    for kind, key in (("v", "vedges"), ("h", "hedges")):
        for (i, j), t in sorted(ikey(map_data.get(key)).items()):
            t = int(t)
            if t <= 0:
                continue
            if t == EDGE_WALL and as_window:
                t = EDGE_WINDOW
            out.append((kind, i, j, t))
    return out


def edge_frame(kind, i, j):
    """(start point, direction name, right cell, left cell) of an edge.

    'right' = the side a module's local +X faces once rotated onto the edge.
    """
    p0 = (i * CELL, j * CELL)
    if kind == "v":                       # along +Y; +X side is cell (i, j)
        return p0, "N", (i, j), (i - 1, j)
    return p0, "E", (i, j - 1), (i, j)    # along +X; local +X -> -Y side is cell (i, j-1)


# ----------------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------------
def plan_structure(map_data):
    """Placements for floors, ceilings, walls, doors, windows, glass and wall caps.

    Each item: {"name", "asset", "pos": (x, y, z), "yaw", "slot": "floor"|"ceiling"|"wall"
    |None, "style": str|None, "kind"}. 'slot'+'style' select the material override.
    """
    struct = map_data.get("structure") or {}
    floor_p = struct.get("floor", FLOOR)
    ceiling_p = struct.get("ceiling", CEILING)
    window_p = struct.get("wall") if "Window" in (struct.get("wall") or "") else KIT["window"]
    styles = cell_styles(map_data)
    items = []

    def put(name, asset, pos, yaw=0.0, slot=None, style=None, kind="struct"):
        items.append({"name": name, "asset": asset, "pos": (pos[0], pos[1], pos[2]),
                      "yaw": float(yaw) % 360.0, "slot": slot, "style": style, "kind": kind})

    # floors + ceilings (+ light fixture handled by the builder)
    for (i, j), st in sorted(styles.items()):
        put("Floor_%d_%d" % (i, j), floor_p, (i * CELL, j * CELL, 0.0), 0, "floor", st, "floor")
        put("Ceiling_%d_%d" % (i, j), ceiling_p, (i * CELL, j * CELL, WALL_H), 0, "ceiling",
            st, "ceiling")

    def face_style(cell):
        return styles.get(cell)

    vertex_dirs = {}
    for kind, i, j, t in edges(map_data):
        p0, dname, right, left = edge_frame(kind, i, j)
        u, yaw = DIRS[dname]
        tag = "%s%d_%d" % (kind.upper(), i, j)
        p1 = _add(p0, u, CELL)
        if t in THICK:
            a, b = (i, j), ((i, j + 1) if kind == "v" else (i + 1, j))
            vertex_dirs.setdefault(a, set()).add(dname)
            vertex_dirs.setdefault(b, set()).add(OPPOSITE[dname])
            panel = KIT["wall"] if t == EDGE_WALL else KIT["wall_door"]
            # panel A faces the right cell, panel B (180 deg, from the far end) the left one
            put("Wall%s_a" % tag, panel, p0 + (0.0,), yaw, "wall", face_style(right) or
                face_style(left), "wall")
            put("Wall%s_b" % tag, panel, p1 + (0.0,), yaw + 180, "wall", face_style(left) or
                face_style(right), "wall")
            if t == EDGE_DOOR:
                mid = _add(p0, u, CELL / 2.0)
                put("Door%s_frame" % tag, KIT["door_frame"], mid + (0.0,), yaw, kind="door")
                hinge = _add(mid, _rot(DOOR_HINGE, yaw))
                leaf_yaw = yaw + (DOOR_OPEN_DEG if door_is_open(map_data, kind, i, j) else 0.0)
                put("Door%s_leaf" % tag, KIT["door_leaf"], hinge + (0.0,), leaf_yaw, kind="door")
                h = _rot(DOOR_HANDLE[:2], leaf_yaw)
                put("Door%s_handle" % tag, KIT["door_handle"],
                    (hinge[0] + h[0], hinge[1] + h[1], DOOR_HANDLE[2]), leaf_yaw, kind="door")
        elif t == EDGE_WINDOW:
            put("Window%s" % tag, window_p, p0 + (0.0,), yaw, kind="window")
        elif t == EDGE_GLASS:
            put("Glass%s_a" % tag, KIT["glass_2m"], p0 + (0.0,), yaw, kind="glass")
            put("Glass%s_b" % tag, KIT["glass_1m"], _add(p0, u, 2.0) + (0.0,), yaw, kind="glass")

    # wall caps: free ends + corner / T / cross posts
    for (vi, vj), dirs in sorted(vertex_dirs.items()):
        v = (vi * CELL, vj * CELL)
        if len(dirs) == 2 and dirs in ({"N", "S"}, {"E", "W"}):
            continue                                           # straight run, no seam
        if len(dirs) == 1:
            d = OPPOSITE[next(iter(dirs))]                     # cap faces away from the wall
            caps = [(d, v)]
        else:
            caps = [(d, _add(v, DIRS[d][0], WALL_HALF)) for d in "NESW" if d not in dirs]
        for d, pos in caps:
            put("Cap_%d_%d_%s" % (vi, vj, d), KIT["wall_end"], pos + (0.0,), CAP_YAW[d],
                "wall", _cap_style(styles, vi, vj, d), "cap")
    return items


def _cap_style(styles, vi, vj, d):
    """Style of a room touching the cap's side (cells around vertex (vi, vj))."""
    around = {"N": [(vi - 1, vj), (vi, vj)], "S": [(vi - 1, vj - 1), (vi, vj - 1)],
              "E": [(vi, vj - 1), (vi, vj)], "W": [(vi - 1, vj - 1), (vi - 1, vj)]}[d]
    for c in around + [(vi - 1, vj - 1), (vi, vj - 1), (vi - 1, vj), (vi, vj)]:
        if c in styles:
            return styles[c]
    return None


def lights(map_data):
    """[(i, j, x, y)] cells with a ceiling light."""
    out = []
    for (i, j), s in sorted(ikey(map_data.get("cells")).items()):
        if s == 2:
            out.append((i, j, (i + 0.5) * CELL, (j + 0.5) * CELL))
    return out


def bev_edges(map_data):
    """[(kind_name, x0, y0, x1, y1)] for the BEV: 'wall', 'door' (open), 'door_closed',
    'window', 'glass', 'opening'."""
    out = []
    for kind, i, j, t in edges(map_data):
        p0, dname, _r, _l = edge_frame(kind, i, j)
        p1 = _add(p0, DIRS[dname][0], CELL)
        if t == EDGE_DOOR:
            name = "door" if door_is_open(map_data, kind, i, j) else "door_closed"
        else:
            name = {EDGE_WALL: "wall", EDGE_WINDOW: "window", EDGE_GLASS: "glass",
                    EDGE_OPENING: "opening"}.get(t, "wall")
        out.append((name, p0[0], p0[1], p1[0], p1[1]))
    return out


DOOR_LEAF_W = 0.94          # SM_DoorB_Door leaf width (m)


def door_leaves(map_data):
    """[(x0, y0, x1, y1)] of every OPEN door leaf (hinge -> free edge): a real obstacle
    standing in the room next to the opening."""
    out = []
    for kind, i, j, t in edges(map_data):
        if t != EDGE_DOOR or not door_is_open(map_data, kind, i, j):
            continue
        p0, dname, _r, _l = edge_frame(kind, i, j)
        u, yaw = DIRS[dname]
        hinge = _add(_add(p0, u, CELL / 2.0), _rot(DOOR_HINGE, yaw))
        tip = _add(hinge, _rot((0.0, -1.0), yaw + DOOR_OPEN_DEG), DOOR_LEAF_W)
        out.append((hinge[0], hinge[1], tip[0], tip[1]))
    return out


def required_assets(map_data):
    """Every structural asset name the plan needs (for an existence check)."""
    names = {it["asset"] for it in plan_structure(map_data)}
    if lights(map_data):
        names.add((map_data.get("structure") or {}).get("light", LIGHT_MESH))
    return sorted(names)
