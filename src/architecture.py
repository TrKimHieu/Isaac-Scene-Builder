"""
architecture.py - Pure layout of the building shell (no USD / no pygame).

Turns map_data into a flat list of placements (asset, position, yaw, style slot) that
scene_builder.py instantiates, and describes edges for the BEV exporter.

Map additions (all optional, old maps load unchanged):
  "styles":       {"i,j": "hospital", ...}   room style per floor cell (default DEFAULT_STYLE)
  "default_style": "office"
  "door_default": "open" | "closed"
  "door_state":   {"v:i,j": "closed", "h:i,j": "open"}   per-door override
  "door_flip":    {"v:i,j": true}   door turned 180 deg (swings into the other room)
  "door_hinge":   {"v:i,j": true}   hinge on the other jamb (same room, mirrored swing)
  edge values in vedges/hedges: 1 wall, 2 door, 3 window, 4 glass wall, 5 opening (no leaf)

Geometry (Office kit, see config.KIT): a vedge (i,j) runs from (iC, jC) along +Y, a hedge
(i,j) from (iC, jC) along +X (C = CELL = 1 m). The kit is built on 3 m modules, so
collinear edges of one type are merged into runs and filled with kit pieces:
  * wall run: two back-to-back SM_Wall_3m panels per piece; pieces are 3 m, the rest a 2 m
    or 1 m "panel" item - the same face + baseboard built as a mesh by the builder with UVs
    in meters, so the wall texture keeps its scale. Each panel faces one room and takes that
    room's wall style (a run breaks where a face style changes).
  * window run: SM_Window_3m per 3 m, the rest SM_Glass_2m / 1m.
  * glass run: SM_Glass_2m + SM_Glass_1m.
  * door: one 1 m edge holding the SM_DoorB frame (1.05 m, its jambs cover the wall ends)
    + leaf + handle; opening: a 1 m gap. Both leave the wall ends free (end caps) and get
    a lintel above (wall panels from LINTEL_Z to the ceiling, the room's wall style; an
    opening also gets a soffit under it).
Free wall ends get an end cap; corners / T / crossings get a post closed by end caps on
the open sides. Floors and ceilings are one mesh per room style (builder), textured like
the 3 m kit tiles.
"""
import math

from config import (CELL, KIT_M, WALL_H, FLOOR, CEILING, LIGHT_MESH, KIT, WALL_HALF, DOOR_HINGE,
                    DOOR_HANDLE, DOOR_OPEN_DEG, DOOR_DEFAULT, STYLES, DEFAULT_STYLE,
                    EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING)
from utils import ikey

THICK = (EDGE_WALL,)                  # double-panel edges (22.4 cm); doors are gaps now
# unit direction + yaw that maps a module's local +Y onto it
LINTEL_Z = 2.10           # lintel bottom: 2 cm into the SM_DoorB header (2.07..2.123 m)
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


def door_flipped(map_data, kind, i, j):
    """True -> the door is turned 180 deg and swings into the other room."""
    return bool((map_data.get("door_flip") or {}).get(edge_key(kind, i, j)))


def door_yaw(map_data, kind, i, j, yaw):
    """Frame yaw of a door on an edge whose modules use `yaw` (adds 180 when flipped)."""
    return yaw + (180.0 if door_flipped(map_data, kind, i, j) else 0.0)


def door_mirrored(map_data, kind, i, j):
    """True -> hinge on the other jamb (the leaf still swings into the same room)."""
    return bool((map_data.get("door_hinge") or {}).get(edge_key(kind, i, j)))


def door_pose(map_data, kind, i, j, opened=None):
    """(frame mid, frame yaw, hinge xy, leaf yaw) of the door on edge (kind, i, j).
    The leaf (SM_DoorB_Door, local -Y from the hinge) swings into the room on the frame's
    local +X side; mirrored = hinged on the other jamb, turned 180 and swung the other way.
    opened: None = its own state, True / False to force."""
    p0, dname, _r, _l = edge_frame(kind[0], i, j)
    u, yaw = DIRS[dname]
    dyaw = door_yaw(map_data, kind[0], i, j, yaw)
    mid = _add(p0, u, CELL / 2.0)
    m = door_mirrored(map_data, kind[0], i, j)
    hinge = _add(mid, _rot((DOOR_HINGE[0], -DOOR_HINGE[1] if m else DOOR_HINGE[1]), dyaw))
    closed = dyaw + (180.0 if m else 0.0)
    is_open = door_is_open(map_data, kind[0], i, j) if opened is None else opened
    leaf = closed + ((-DOOR_OPEN_DEG if m else DOOR_OPEN_DEG) if is_open else 0.0)
    return mid, dyaw, hinge, leaf


def leaf_segment(map_data, kind, i, j, opened=None, angle=None):
    """(hinge, tip) of the leaf; angle: degrees opened (overrides the door state)."""
    mid, dyaw, hinge, leaf = door_pose(map_data, kind, i, j, opened)
    if angle is not None:
        m = door_mirrored(map_data, kind[0], i, j)
        leaf = dyaw + (180.0 if m else 0.0) + (-angle if m else angle)
    return hinge, _add(hinge, _rot((0.0, -1.0), leaf), DOOR_LEAF_W)


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
def split_run(n):
    """Kit piece lengths (cells) filling a run of n 1 m edges: 3 m pieces, the rest as one
    2 m piece or 2 + 2 instead of 3 + 1 (a 1 m piece only for a 1 m run)."""
    k = int(round(KIT_M / CELL))
    if n <= 0:
        return []
    if n % k == 0:
        return [k] * (n // k)
    if n % k == 1 and n > k:
        return [k] * ((n - 4) // k) + [2, 2]
    return [k] * (n // k) + [n % k]


def runs(map_data, styles=None):
    """Collinear edges merged: [(kind, i, j, edge_type, n)] - n edges from edge (kind, i, j)
    on. Walls break where either face changes room style; doors are always single."""
    styles = cell_styles(map_data) if styles is None else styles
    by_line = {}
    for kind, i, j, t in edges(map_data):
        line, pos = (i, j) if kind == "v" else (j, i)
        by_line.setdefault((kind, line), []).append((pos, t))
    out = []
    for (kind, line), items in sorted(by_line.items()):
        items.sort()
        cur = None
        for pos, t in items:
            i, j = (line, pos) if kind == "v" else (pos, line)
            _p, _d, right, left = edge_frame(kind, i, j)
            face = (styles.get(right), styles.get(left)) if t == EDGE_WALL else None
            if (cur and t == cur[3] and pos == cur[5] + 1 and face == cur[6]
                    and t not in (EDGE_DOOR, EDGE_OPENING)):
                cur[4] += 1
                cur[5] = pos
                continue
            if cur:
                out.append(tuple(cur[:5]))
            cur = [kind, i, j, t, 1, pos, face]
        if cur:
            out.append(tuple(cur[:5]))
    return out


def plan_structure(map_data):
    """Placements for floors, ceilings, walls, doors, windows, glass and wall caps.

    Each item: {"name", "asset", "pos": (x, y, z), "yaw", "slot": "floor"|"ceiling"|"wall"
    |None, "style": str|None, "kind", "scale": (sx, sy, sz)}; 'slot'+'style' select the
    material override. Items with "cells" (floor / ceiling), "panel" (length, z0, z1: a wall
    face shorter than the kit's) or "quad" (soffit) are meshes built by the builder; their
    asset is only the material source.
    """
    struct = map_data.get("structure") or {}
    floor_p = struct.get("floor", FLOOR)
    ceiling_p = struct.get("ceiling", CEILING)
    window_p = struct.get("wall") if "Window" in (struct.get("wall") or "") else KIT["window"]
    styles = cell_styles(map_data)
    items = []

    def put(name, asset, pos, yaw=0.0, slot=None, style=None, kind="struct", **kw):
        it = {"name": name, "asset": asset, "pos": (pos[0], pos[1], pos[2]),
              "yaw": float(yaw) % 360.0, "slot": slot, "style": style, "kind": kind,
              "scale": (1.0, 1.0, 1.0)}
        it.update(kw)
        items.append(it)

    # floors + ceilings: one mesh per room style (+ light fixture handled by the builder)
    by_style = {}
    for ij, st in sorted(styles.items()):
        by_style.setdefault(st, []).append(ij)
    for st, cells in sorted(by_style.items()):
        put("Floor_%s" % st, floor_p, (0.0, 0.0, 0.0), 0, "floor", st, "floor", cells=cells)
        put("Ceiling_%s" % st, ceiling_p, (0.0, 0.0, WALL_H), 0, "ceiling", st, "ceiling",
            cells=cells)

    def face_style(cell):
        return styles.get(cell)

    vertex_dirs = {}
    for kind, i, j, t in edges(map_data):
        if t in THICK:
            _p0, dname, _r, _l = edge_frame(kind, i, j)
            a, b = (i, j), ((i, j + 1) if kind == "v" else (i + 1, j))
            vertex_dirs.setdefault(a, set()).add(dname)
            vertex_dirs.setdefault(b, set()).add(OPPOSITE[dname])

    for kind, i, j, t, n in runs(map_data, styles):
        p0, dname, right, left = edge_frame(kind, i, j)
        u, yaw = DIRS[dname]
        tag = "%s%d_%d" % (kind.upper(), i, j)
        if t == EDGE_WALL:
            s = 0
            for k, L in enumerate(split_run(n)):
                a0, a1 = _add(p0, u, s * CELL), _add(p0, u, (s + L) * CELL)
                # a full 3 m piece is the kit panel itself, a shorter one a panel mesh
                extra = {} if abs(L * CELL - KIT_M) < 1e-9 else {"panel": (L * CELL, 0.0, WALL_H)}
                # panel A faces the right cell, panel B (180 deg, from the far end) the left one
                put("Wall%s_%d_a" % (tag, k), KIT["wall"], a0 + (0.0,), yaw, "wall",
                    face_style(right) or face_style(left), "wall", **extra)
                put("Wall%s_%d_b" % (tag, k), KIT["wall"], a1 + (0.0,), yaw + 180, "wall",
                    face_style(left) or face_style(right), "wall", **extra)
                s += L
        elif t in (EDGE_DOOR, EDGE_OPENING):
            # lintel: the two wall faces above the opening, up to the ceiling
            p1 = _add(p0, u, CELL)
            put("Lintel%s_a" % tag, KIT["wall"], p0 + (0.0,), yaw, "wall",
                face_style(right) or face_style(left), "wall", panel=(CELL, LINTEL_Z, WALL_H))
            put("Lintel%s_b" % tag, KIT["wall"], p1 + (0.0,), yaw + 180, "wall",
                face_style(left) or face_style(right), "wall", panel=(CELL, LINTEL_Z, WALL_H))
            if t == EDGE_OPENING:                       # its underside (no door header)
                n = (u[1], -u[0])
                quad = [_add(p0, n, -WALL_HALF), _add(p0, n, WALL_HALF),
                        _add(p1, n, WALL_HALF), _add(p1, n, -WALL_HALF)]
                put("Soffit%s" % tag, KIT["wall"], (0.0, 0.0, LINTEL_Z), 0, "wall",
                    face_style(right) or face_style(left), "wall", quad=quad)
                continue
            mid, dyaw, hinge, leaf_yaw = door_pose(map_data, kind, i, j)
            put("Door%s_frame" % tag, KIT["door_frame"], mid + (0.0,), dyaw, kind="door")
            put("Door%s_leaf" % tag, KIT["door_leaf"], hinge + (0.0,), leaf_yaw, kind="door")
            h = _rot(DOOR_HANDLE[:2], leaf_yaw)
            put("Door%s_handle" % tag, KIT["door_handle"],
                (hinge[0] + h[0], hinge[1] + h[1], DOOR_HANDLE[2]), leaf_yaw, kind="door")
        elif t == EDGE_WINDOW:
            k_m = int(round(KIT_M / CELL))
            for k in range(n // k_m):
                put("Window%s_%d" % (tag, k), window_p, _add(p0, u, k * KIT_M) + (0.0,), yaw,
                    kind="window")
            s = (n // k_m) * k_m
            for k, L in enumerate(_glass_pieces(n - s)):     # the rest of the run: glazing
                put("Window%s_g%d" % (tag, k), KIT["glass_%dm" % L],
                    _add(p0, u, s * CELL) + (0.0,), yaw, kind="window")
                s += L
        elif t == EDGE_GLASS:
            s = 0
            for k, L in enumerate(_glass_pieces(n)):
                put("Glass%s_%d" % (tag, k), KIT["glass_%dm" % L], _add(p0, u, s * CELL) + (0.0,),
                    yaw, kind="glass")
                s += L

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


def _glass_pieces(n):
    """Glass panel lengths (m) for n 1 m edges: 2 m panels, a 1 m one for an odd rest."""
    m = int(round(n * CELL))
    return [2] * (m // 2) + [1] * (m % 2)


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
        hinge, tip = leaf_segment(map_data, kind, i, j)
        out.append((hinge[0], hinge[1], tip[0], tip[1]))
    return out


def door_swing_blocked(map_data, kind, i, j, walls=None):
    """True if the leaf, swinging open, runs into a wall / window / glass / door leaf
    beside the door (sampled along the leaf at a few opening angles). walls: rects as in
    placement.wall_obstacles (computed when None)."""
    if walls is None:
        import placement
        walls = placement.wall_obstacles(dict(map_data, door_state={}, door_default="closed"))
    for ang in (30.0, 60.0, 90.0, DOOR_OPEN_DEG):
        (hx, hy), (tx, ty) = leaf_segment(map_data, kind, i, j, angle=ang)
        for f in (0.25, 0.5, 0.75, 1.0):          # the hinge end touches its own jamb
            x, y = hx + (tx - hx) * f, hy + (ty - hy) * f
            for x0, y0, x1, y1 in walls:
                if x0 + 0.01 < x < x1 - 0.01 and y0 + 0.01 < y < y1 - 0.01:
                    return True
    return False


def best_door_setup(map_data, kind, i, j):
    """(flip, mirror) for the door that keeps its current swing room if possible and does
    not run into a wall; None if every way is blocked."""
    key = edge_key(kind, i, j)
    flip0 = door_flipped(map_data, kind, i, j)
    mir0 = door_mirrored(map_data, kind, i, j)
    import placement
    walls = placement.wall_obstacles(dict(map_data, door_state={}, door_default="closed"))
    for flip, mir in ((flip0, mir0), (flip0, not mir0), (not flip0, mir0), (not flip0, not mir0)):
        md = dict(map_data, door_flip={key: True} if flip else {},
                  door_hinge={key: True} if mir else {})
        if not door_swing_blocked(md, kind, i, j, walls):
            return flip, mir
    return None


def fit_doors(map_data):
    """Map data with every door whose leaf would run into a wall re-hinged / turned
    (best_door_setup); doors that are already clear are left as they are."""
    md = dict(map_data, door_flip=dict(map_data.get("door_flip") or {}),
              door_hinge=dict(map_data.get("door_hinge") or {}))
    import placement
    walls = placement.wall_obstacles(dict(md, door_state={}, door_default="closed"))
    for kind, i, j, t in edges(md):
        if t != EDGE_DOOR or not door_swing_blocked(md, kind, i, j, walls):
            continue
        best = best_door_setup(md, kind, i, j)
        if best:
            key = edge_key(kind, i, j)
            md["door_flip"].pop(key, None)
            md["door_hinge"].pop(key, None)
            if best[0]:
                md["door_flip"][key] = True
            if best[1]:
                md["door_hinge"][key] = True
    return md


def required_assets(map_data):
    """Every structural asset name the plan needs (for an existence check)."""
    names = {it["asset"] for it in plan_structure(map_data)}
    if lights(map_data):
        names.add((map_data.get("structure") or {}).get("light", LIGHT_MESH))
    return sorted(names)
