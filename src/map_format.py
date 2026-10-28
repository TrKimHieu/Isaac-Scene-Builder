"""
map_format.py - Map JSON versions: the grid cell size a map was drawn with.

Maps carry "cell" (m). Maps saved before the 1 m grid have no "cell" key and use
LEGACY_CELL (3 m); upgrade() turns them into CELL maps (every old cell -> k x k new cells,
k = 3) without moving anything in the world:

  * floor cells and room styles fill the k x k block; a ceiling light stays only at the
    block's centre cell (one lamp per old 3 x 3 m cell, as before)
  * an old 3 m edge becomes k collinear 1 m edges of the same type, except a door /
    opening, which sits on the middle one with walls on both sides (where the old
    SM_Wall_3m_door pair had its opening)
  * door_state / door_flip keys move to that middle edge
  * furniture, robot, rooms metadata are in meters / scaled (unchanged in the world)

Call ensure() wherever a map comes in from a file; maps built in memory by this version
always carry "cell".
"""
import copy

from config import CELL, LEGACY_CELL


def cell_of(map_data):
    return float(map_data.get("cell") or LEGACY_CELL)


def is_current(map_data):
    return abs(cell_of(map_data) - CELL) < 1e-9


def _ij(key):
    if isinstance(key, (tuple, list)):           # in-memory maps may use (i, j) keys
        return int(key[0]), int(key[1])
    i, j = key.split(",")
    return int(i), int(j)


def upgrade(map_data):
    """Copy of a legacy map on the CELL grid (the map itself is not changed)."""
    old = cell_of(map_data)
    k = int(round(old / CELL))
    if abs(k * CELL - old) > 1e-9 or k < 1:
        raise ValueError("cannot convert a %.3g m grid to %.3g m cells" % (old, CELL))
    md = copy.deepcopy(map_data)
    md["cell"] = CELL
    if k == 1:
        return md
    mid = k // 2
    nx, ny = map_data["grid"]
    md["grid"] = [int(nx) * k, int(ny) * k]

    cells, styles = {}, {}
    for key, s in (map_data.get("cells") or {}).items():
        i, j = _ij(key)
        if not s:
            continue
        for a in range(k):
            for b in range(k):
                light = s == 2 and a == mid and b == mid
                cells["%d,%d" % (i * k + a, j * k + b)] = 2 if light else 1
    for key, st in (map_data.get("styles") or {}).items():
        i, j = _ij(key)
        for a in range(k):
            for b in range(k):
                styles["%d,%d" % (i * k + a, j * k + b)] = st
    md["cells"] = cells
    md["styles"] = styles

    from config import EDGE_WALL, EDGE_DOOR, EDGE_OPENING
    for name, axis in (("vedges", "v"), ("hedges", "h")):
        out = {}
        for key, t in (map_data.get(name) or {}).items():
            i, j = _ij(key)
            t = int(t)
            for a in range(k):
                ni, nj = (i * k, j * k + a) if axis == "v" else (i * k + a, j * k)
                part = t
                if t in (EDGE_DOOR, EDGE_OPENING) and a != mid:
                    part = EDGE_WALL
                out["%d,%d" % (ni, nj)] = part
        md[name] = out

    for name in ("door_state", "door_flip"):
        moved = {}
        for key, v in (map_data.get(name) or {}).items():
            axis, ij = key.split(":")
            i, j = _ij(ij)
            ni, nj = (i * k, j * k + mid) if axis == "v" else (i * k + mid, j * k)
            moved["%s:%d,%d" % (axis, ni, nj)] = v
        if moved or name in map_data:
            md[name] = moved

    rooms = []
    for rm in map_data.get("rooms") or []:
        rm = dict(rm)
        if "rect" in rm:
            i0, j0, i1, j1 = rm["rect"]
            rm["rect"] = [i0 * k, j0 * k, i1 * k + k - 1, j1 * k + k - 1]
        rooms.append(rm)
    if "rooms" in map_data:
        md["rooms"] = rooms
    return md


def ensure(map_data):
    """The map on the CELL grid (itself when it already is)."""
    return map_data if is_current(map_data) else upgrade(map_data)
