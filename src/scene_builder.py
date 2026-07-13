"""
scene_builder.py - Loi build USD tu map_data (KHONG phu thuoc pygame).

Dung chung cho scene_editor.py (GUI) va test headless.
Sinh Scene .usd tham chieu props trong assets/office/Props/, Z-up, 1 unit = 1 met.

map_data schema (xem plan):
{
  "grid":   [nx, ny],
  "cells":  {"i,j": 0|1|2},          # 0 rong | 1 san | 2 san+den
  "vedges": {"i,j": 0|1|2},          # canh DOC tai X=i*3, Y[j*3..(j+1)*3]; 0 none|1 wall|2 door
  "hedges": {"i,j": 0|1|2},          # canh NGANG tai Y=j*3, X[i*3..(i+1)*3]
  "furniture": [{"asset","x","y","yaw"}]
}
"""
import os
import re
import glob

from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf

from config import (PROJECT_ROOT, PROP_DIRS, PROPS_REL, CELL, WALL_H,
                    FLOOR, CEILING, WALL, WALL_DOOR, LIGHT_MESH, REQUIRED,
                    STRUCTURE_CHOICES, FURNITURE, SCENES_DIR,
                    LIGHT_RADIUS, LIGHT_INTENSITY, LIGHT_COLOR,
                    LIGHT_EXPOSURE, LIGHT_CONE_ANGLE, LIGHT_CONE_SOFTNESS)
from utils import safe_name, load_prop_shapes, ikey


# Re-export for backward compatibility
_ikey = ikey
_safe = safe_name
_load_prop_shapes = load_prop_shapes


# ----------------------------------------------------------------------------
# Asset helpers
# ----------------------------------------------------------------------------
def _asset_dir(name):
    """Tra duong dan tuyet doi thu muc chua <name>.usd, hoac None neu khong thay."""
    for d in PROP_DIRS:
        if os.path.isfile(os.path.join(d, name + ".usd")):
            return d
    return None


def asset_exists(name):
    return _asset_dir(name) is not None


def asset_abs(name):
    """Duong dan tuyet doi toi prop (hoac None)."""
    d = _asset_dir(name)
    return os.path.join(d, name + ".usd") if d else None


def asset_path(name):
    """Duong dan tuong doi tu file Scene toi prop (portable), dung dung thu muc."""
    d = _asset_dir(name)
    if d:
        rel = os.path.relpath(d, PROJECT_ROOT).replace("\\", "/")
        return "./%s/%s.usd" % (rel, name)
    return "./%s/%s.usd" % (PROPS_REL, name)


def _extra_furniture():
    """Furniture ngoai danh sach curated:
      (a) moi asset da do shape trong props_shapes.json (bat ky thu muc), va
      (b) moi *.usd trong assets/extra/.
    Ban kinh: props_shapes.json[name].r -> mac dinh 0.5.
    """
    known = {n for n, _ in FURNITURE}
    shapes = load_prop_shapes()
    out, seen = [], set()

    def add(n):
        if n in known or n in seen or not asset_exists(n):
            return
        seen.add(n)
        out.append((n, float(shapes.get(n, {}).get("r", 0.5))))

    for n in sorted(shapes.keys()):             # (a) da dang ky qua props_shapes.json
        add(n)
    for d in PROP_DIRS[1:]:                      # (b) tha vao assets/extra/
        if os.path.isdir(d):
            for f in sorted(glob.glob(os.path.join(d, "*.usd"))):
                add(os.path.splitext(os.path.basename(f))[0])
    return out


def available_furniture():
    """Palette = curated (ton tai) + prop da dang ky (props_shapes.json) + assets/extra/."""
    base = [(n, r) for (n, r) in FURNITURE if asset_exists(n)]
    return base + _extra_furniture()


def check_required():
    missing = [n for n in REQUIRED if not asset_exists(n)]
    return missing


def next_scene_path(directory=None, stem="scene"):
    """Tra ve duong dan sceneX.usd voi X tang dan (X nho nhat chua dung)."""
    if directory is None:
        directory = SCENES_DIR
    pat = re.compile(r"^%s(\d+)\.usd$" % re.escape(stem), re.IGNORECASE)
    used = set()
    for f in glob.glob(os.path.join(directory, "%s*.usd" % stem)):
        m = pat.match(os.path.basename(f))
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return os.path.join(directory, "%s%d.usd" % (stem, n))


# ----------------------------------------------------------------------------
# Parse map_data
# ----------------------------------------------------------------------------
def parse_map(m):
    nx, ny = m["grid"]
    return (
        int(nx), int(ny),
        ikey(m.get("cells")),
        ikey(m.get("vedges")),
        ikey(m.get("hedges")),
        list(m.get("furniture", [])),
    )


def boundary_edges(cells):
    """Tinh cac canh bien cua tap o san (mot ben la san, ben kia khong).

    cells: dict (i,j)->state. Tra ve (set_vedges, set_hedges).
    - vedge (i,j): giua o trai (i-1,j) va o phai (i,j)
    - hedge (i,j): giua o duoi (i,j-1) va o tren (i,j)
    """
    floor = {ij for ij, s in cells.items() if s >= 1}
    ve, he = set(), set()
    for (i, j) in floor:
        for vi in (i, i + 1):                       # canh trai & phai cua o
            left = (vi - 1, j) in floor
            right = (vi, j) in floor
            if left != right:
                ve.add((vi, j))
        for hj in (j, j + 1):                        # canh duoi & tren cua o
            below = (i, hj - 1) in floor
            above = (i, hj) in floor
            if below != above:
                he.add((i, hj))
    return ve, he


# ----------------------------------------------------------------------------
# Can chinh prop cau truc (theo bbox that -> tu thich ung khi doi prop)
# ----------------------------------------------------------------------------
_BBOX_CACHE = {}
_MPU_CACHE = {}


def asset_mpu(name):
    """metersPerUnit cua prop (cache). Prop cm (0.01) can scale khi reference vao
    stage met. Prop Office bake san scale nen mpu=1.0."""
    if name in _MPU_CACHE:
        return _MPU_CACHE[name]
    v = 1.0
    p = asset_abs(name)
    if p:
        try:
            st = Usd.Stage.Open(p)
            v = UsdGeom.GetStageMetersPerUnit(st) or 1.0
        except Exception:
            v = 1.0
    _MPU_CACHE[name] = v
    return v


def _prop_bbox(name):
    """(min, max) bbox the gioi cua prop (Gf.Vec3), cache. None neu loi."""
    if name in _BBOX_CACHE:
        return _BBOX_CACHE[name]
    res = None
    p = asset_abs(name)
    if p:
        try:
            st = Usd.Stage.Open(p)
            cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                     [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
            prim = st.GetDefaultPrim() or st.GetPseudoRoot()
            rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            res = (rng.GetMin(), rng.GetMax())
        except Exception:
            res = None
    _BBOX_CACHE[name] = res
    return res


def _wall_align(name):
    """(cx, ymin): tam-do-day theo X va diem dau chieu dai theo Y cua prop tuong.

    Fallback (0.106, 0.0) khop SM_Wall_3m khi khong doc duoc bbox.
    """
    bb = _prop_bbox(name)
    if not bb:
        return 0.106, 0.0
    mn, mx = bb
    return (mn[0] + mx[0]) / 2.0, mn[1]


def _tile_align(name):
    """(xmin, ymin): goc cua tile san/tran (thuong (0,0))."""
    bb = _prop_bbox(name)
    if not bb:
        return 0.0, 0.0
    return bb[0][0], bb[0][1]


# ----------------------------------------------------------------------------
# Dat prim
# ----------------------------------------------------------------------------
def place(stage, path, asset_name, translate, rot_z=0.0, scale=1.0):
    """Xform mang transform, ben trong /Geo reference toi prop.

    Tu chuan hoa don vi: nhan scale voi metersPerUnit cua prop (prop cm -> 0.01)
    de moi prop hien dung kich thuoc met trong stage met.
    """
    xf = UsdGeom.Xform.Define(stage, path)
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if rot_z:
        xf.AddRotateZOp().Set(float(rot_z))
    eff = float(scale) * asset_mpu(asset_name)
    if abs(eff - 1.0) > 1e-9:
        xf.AddScaleOp().Set(Gf.Vec3f(eff, eff, eff))
    geo = stage.DefinePrim(path + "/Geo")
    geo.GetReferences().AddReference(asset_path(asset_name))
    return xf


def add_light(stage, base_path, cx, cy, light_mesh=None):
    """Vo den (mesh) + nguon sang SphereLight 'da bat' tai tam o."""
    if light_mesh is None:
        light_mesh = LIGHT_MESH
    place(stage, base_path + "_Fixture", light_mesh, (cx, cy, WALL_H - 0.02))
    light = UsdLux.SphereLight.Define(stage, base_path)
    light.CreateRadiusAttr(LIGHT_RADIUS)
    light.CreateIntensityAttr(LIGHT_INTENSITY)
    light.CreateColorAttr(Gf.Vec3f(*LIGHT_COLOR))
    light.CreateExposureAttr(LIGHT_EXPOSURE)
    shaping = UsdLux.ShapingAPI.Apply(light.GetPrim())
    shaping.CreateShapingConeAngleAttr(LIGHT_CONE_ANGLE)
    shaping.CreateShapingConeSoftnessAttr(LIGHT_CONE_SOFTNESS)
    UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(cx, cy, WALL_H - 0.25))


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------
def build_scene(map_data, out_path):
    """Dung Scene .usd (USDA text) tu map_data. Tra ve dict thong ke."""
    struct = dict(map_data.get("structure") or {})
    floor_p = struct.get("floor", FLOOR)
    ceiling_p = struct.get("ceiling", CEILING)
    wall_p = struct.get("wall", WALL)
    door_p = struct.get("wall_door", WALL_DOOR)
    light_p = struct.get("light", LIGHT_MESH)

    missing = [n for n in (floor_p, ceiling_p, wall_p, door_p, light_p)
               if not asset_exists(n)]
    if missing:
        raise RuntimeError("Thieu module cau truc: %s (trong %s)" % (missing, PROP_DIRS))

    nx, ny, cells, vedges, hedges, furniture = parse_map(map_data)

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Scope.Define(stage, "/World/Structure")
    UsdGeom.Scope.Define(stage, "/World/Lights")
    UsdGeom.Scope.Define(stage, "/World/Furniture")

    stats = {"floor": 0, "ceiling": 0, "light": 0, "wall": 0, "door": 0,
             "furniture": 0, "skipped": []}

    fxo, fyo = _tile_align(floor_p)
    cxo, cyo = _tile_align(ceiling_p)
    wcx, wym = _wall_align(wall_p)
    dcx, dym = _wall_align(door_p)

    # San + tran (+ den)
    for (i, j), s in sorted(cells.items()):
        if s < 1:
            continue
        place(stage, "/World/Structure/Floor_%d_%d" % (i, j), floor_p,
              (i * CELL - fxo, j * CELL - fyo, 0.0))
        place(stage, "/World/Structure/Ceiling_%d_%d" % (i, j), ceiling_p,
              (i * CELL - cxo, j * CELL - cyo, WALL_H))
        stats["floor"] += 1
        stats["ceiling"] += 1
        if s == 2:
            cx, cy = (i + 0.5) * CELL, (j + 0.5) * CELL
            add_light(stage, "/World/Lights/Lamp_%d_%d" % (i, j), cx, cy, light_p)
            stats["light"] += 1

    # Tuong doc (vedge)
    for (i, j), s in sorted(vedges.items()):
        if s == 0:
            continue
        a, cx, ym = (door_p, dcx, dym) if s == 2 else (wall_p, wcx, wym)
        place(stage, "/World/Structure/WallV_%d_%d" % (i, j), a,
              (i * CELL - cx, j * CELL - ym, 0.0), rot_z=0)
        stats["door" if s == 2 else "wall"] += 1

    # Tuong ngang (hedge)
    for (i, j), s in sorted(hedges.items()):
        if s == 0:
            continue
        a, cx, ym = (door_p, dcx, dym) if s == 2 else (wall_p, wcx, wym)
        place(stage, "/World/Structure/WallH_%d_%d" % (i, j), a,
              (i * CELL - ym, j * CELL + cx, 0.0), rot_z=-90)
        stats["door" if s == 2 else "wall"] += 1

    # Noi that
    for idx, f in enumerate(furniture):
        name = f["asset"]
        if not asset_exists(name):
            stats["skipped"].append(name)
            continue
        path = "/World/Furniture/%s_%d" % (safe_name(name), idx)
        place(stage, path, name, (float(f["x"]), float(f["y"]), 0.0),
              rot_z=float(f.get("yaw", 0.0)))
        stats["furniture"] += 1

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    text = stage.GetRootLayer().ExportToString()
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    stats["out"] = out_path
    return stats


if __name__ == "__main__":
    cells = {}
    for i in range(3):
        for j in range(2):
            cells[(i, j)] = 1
    cells[(1, 0)] = 2  # den
    ve, he = boundary_edges(cells)
    vedges = {e: 1 for e in ve}
    hedges = {e: 1 for e in he}
    md = {
        "grid": [3, 2],
        "cells": {"%d,%d" % k: v for k, v in cells.items()},
        "vedges": {"%d,%d" % k: v for k, v in vedges.items()},
        "hedges": {"%d,%d" % k: v for k, v in hedges.items()},
        "furniture": [
            {"asset": "SM_SecretaryDeskA", "x": 3.0, "y": 3.0, "yaw": 0},
            {"asset": "SM_ChairOffice", "x": 4.5, "y": 3.0, "yaw": 180},
        ],
    }
    print(build_scene(md, os.path.join(SCENES_DIR, "scene_demo.usd")))
