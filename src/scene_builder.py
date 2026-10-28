"""
scene_builder.py - Core USD builder from map_data (no pygame dependency).

Shared by scene_editor.py (GUI) and headless tests.
Generate a Scene .usd referencing props in assets/office/Props/, Z-up, 1 unit = 1 m.

map_data schema (see plan):
{
  "grid":   [nx, ny],
  "cells":  {"i,j": 0|1|2},          # 0 empty | 1 floor | 2 floor+light
  "vedges": {"i,j": 0|1|2},          # VERTICAL edge at X=i*3, Y[j*3..(j+1)*3]; 0 none|1 wall|2 door
  "hedges": {"i,j": 0|1|2},          # HORIZONTAL edge at Y=j*3, X[i*3..(i+1)*3]
  "furniture": [{"asset","x","y","yaw"}]
}
"""
import os
import re
import glob
import math

from usd_runtime import pxr_available

if pxr_available():   # installed pxr, or Isaac Sim's bundled OpenUSD (no Kit start needed)
    from pxr import Usd, UsdGeom, UsdLux, UsdShade, UsdPhysics, Gf, Sdf
    try:
        from pxr import UsdSemantics
    except ImportError:
        UsdSemantics = None
else:                 # editor / BEV / shape tools work without OpenUSD; writing .usd needs it
    Usd = UsdGeom = UsdLux = UsdShade = UsdPhysics = UsdSemantics = Gf = Sdf = None

from config import (PROJECT_ROOT, PROP_DIRS, PROPS_REL, CELL, WALL_H,
                    FLOOR, CEILING, WALL, WALL_DOOR, LIGHT_MESH, REQUIRED,
                    STRUCTURE_CHOICES, FURNITURE, FURNITURE_CATEGORIES,
                    LIBRARY_CATEGORY_TABS, SCENES_DIR, STYLES, LIBRARY_DIR,
                    LIGHT_RADIUS, LIGHT_INTENSITY, LIGHT_COLOR,
                    LIGHT_EXPOSURE, LIGHT_CONE_ANGLE, LIGHT_CONE_SOFTNESS)
from utils import safe_name, load_prop_shapes, load_library, ikey
import robots


# Re-export for backward compatibility
_ikey = ikey
_safe = safe_name
_load_prop_shapes = load_prop_shapes


# ----------------------------------------------------------------------------
# Asset helpers
# ----------------------------------------------------------------------------
def _asset_dir(name):
    """Return the (relative) dir containing <name>.usd, or None if not found."""
    for d in PROP_DIRS:
        if os.path.isfile(os.path.join(d, name + ".usd")):
            return d
    return None


def asset_exists(name):
    return asset_abs(name) is not None


def asset_abs(name):
    """Absolute path to the prop (or None): flat PROP_DIRS first, then the asset library."""
    d = _asset_dir(name)
    if d:
        return os.path.join(d, name + ".usd")
    lib = load_library().get(name)
    return lib["abs"] if lib else None


def asset_path(name, base_dir=None):
    """Path to the prop relative to base_dir = the directory of the Scene file that
    references it (USD anchors relative asset paths to the referencing layer).

    base_dir None -> relative to PROJECT_ROOT (only correct for scenes saved there).
    """
    base = base_dir or PROJECT_ROOT
    p = asset_abs(name) or os.path.join(PROJECT_ROOT, PROPS_REL, name + ".usd")
    try:
        rel = os.path.relpath(p, base)
    except ValueError:                       # other drive on Windows: keep absolute
        return p.replace("\\", "/")
    rel = rel.replace("\\", "/")
    return rel if rel.startswith("../") else "./" + rel


def _stage_dir(stage):
    """Directory of the stage's root layer file, or None for in-memory stages."""
    real = stage.GetRootLayer().realPath
    return os.path.dirname(os.path.abspath(real)) if real else None


def _library_radius(entry):
    """Footprint radius guess from manifest dims (Poly Haven) -> 0.5 default."""
    dims = entry.get("dims_m")
    if dims:
        return round(0.5 * math.hypot(dims[0], dims[1]), 2)
    return 0.5


def _extra_furniture():
    """Furniture outside the curated list:
      (a) any asset already measured in props_shapes.json (any dir),
      (b) moi *.usd trong assets/extra/, and
      (c) the curated asset library (data/asset_manifest.json, assets/library/).
    Radius: props_shapes.json[name].r -> library dims -> default 0.5.
    """
    known = {n for n, _ in FURNITURE}
    shapes = load_prop_shapes()
    library = load_library()
    out, seen = [], set()

    def add(n):
        if n in known or n in seen or not asset_exists(n):
            return
        seen.add(n)
        r = shapes.get(n, {}).get("r")
        if r is None:
            r = _library_radius(library[n]) if n in library else 0.5
        out.append((n, float(r)))

    for n in sorted(shapes.keys()):             # (a) registered via props_shapes.json
        add(n)
    for d in PROP_DIRS[1:]:                      # (b) dropped into assets/extra/
        if os.path.isdir(d):
            for f in sorted(glob.glob(os.path.join(d, "*.usd"))):
                add(os.path.splitext(os.path.basename(f))[0])
    for n in sorted(library):                    # (c) asset library
        add(n)
    return out


def available_furniture():
    """Palette = curated (existing) + registered props (props_shapes.json) + assets/extra/."""
    base = [(n, r) for (n, r) in FURNITURE if asset_exists(n)]
    return base + _extra_furniture()


def palette_categories():
    """Editor palette tabs: curated FURNITURE_CATEGORIES + library assets by category."""
    cats = {k: list(v) for k, v in FURNITURE_CATEGORIES.items()}
    for n, e in sorted(load_library().items()):
        cats.setdefault(LIBRARY_CATEGORY_TABS.get(e.get("category"), "Other"), []).append(n)
    return cats


def check_required():
    missing = [n for n in REQUIRED if not asset_exists(n)]
    return missing


def next_scene_path(directory=None, stem="scene"):
    """Return path sceneX.usd with increasing X (smallest unused X)."""
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
    """Compute boundary edges of the floor set (floor on one side, not the other).

    cells: dict (i,j)->state. Tra ve (set_vedges, set_hedges).
    - vedge (i,j): giua o trai (i-1,j) va o phai (i,j)
    - hedge (i,j): giua o duoi (i,j-1) va o tren (i,j)
    """
    floor = {ij for ij, s in cells.items() if s >= 1}
    ve, he = set(), set()
    for (i, j) in floor:
        for vi in (i, i + 1):                       # left & right edges of the cell
            left = (vi - 1, j) in floor
            right = (vi, j) in floor
            if left != right:
                ve.add((vi, j))
        for hj in (j, j + 1):                        # bottom & top edges of the cell
            below = (i, hj - 1) in floor
            above = (i, hj) in floor
            if below != above:
                he.add((i, hj))
    return ve, he


# ----------------------------------------------------------------------------
# Align structural props (from real bbox -> adapts when props are swapped)
# ----------------------------------------------------------------------------
_BBOX_CACHE = {}
_MPU_CACHE = {}
_UP_CACHE = {}


def asset_up_axis(name):
    """'Y' or 'Z' (cached). Y-up props (some ArchVis / Poly Haven assets) get rotated
    +90 deg about X when placed so they stand upright in the Z-up scene."""
    if name in _UP_CACHE:
        return _UP_CACHE[name]
    v = "Z"
    p = asset_abs(name)
    if p:
        try:
            v = str(UsdGeom.GetStageUpAxis(Usd.Stage.Open(p))) or "Z"
        except Exception:
            v = "Z"
    _UP_CACHE[name] = v
    return v


def asset_mpu(name):
    """metersPerUnit of the prop (cached). cm props (0.01) need scaling when referenced into
    a meter stage. Office props bake the scale so mpu=1.0."""
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
    """(min, max) world bbox of the prop (Gf.Vec3), cached. None on error."""
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
    """(cx, ymin): thickness center along X and the length-start along Y of a wall prop.

    Fallback (0.106, 0.0) matches SM_Wall_3m when the bbox cannot be read.
    """
    bb = _prop_bbox(name)
    if not bb:
        return 0.106, 0.0
    mn, mx = bb
    return (mn[0] + mx[0]) / 2.0, mn[1]


def _tile_align(name):
    """(xmin, ymin): corner of the floor/ceiling tile (usually (0,0))."""
    bb = _prop_bbox(name)
    if not bb:
        return 0.0, 0.0
    return bb[0][0], bb[0][1]


# ----------------------------------------------------------------------------
# Dat prim
# ----------------------------------------------------------------------------
def place(stage, path, asset_name, translate, rot_z=0.0, scale=1.0, base_dir=None):
    """Xform holding the transform, with /Geo referencing the prop.

    base_dir: directory the Scene file will be saved in (asset paths are made relative to
    it); defaults to the stage's own file location.

    Auto unit-normalize: multiply scale by the prop metersPerUnit (cm props -> 0.01)
    so every prop shows at true meter size in a meter stage.
    """
    xf = UsdGeom.Xform.Define(stage, path)
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if rot_z:
        xf.AddRotateZOp().Set(float(rot_z))
    if asset_up_axis(asset_name) == "Y":
        xf.AddRotateXOp(opSuffix="upAxis").Set(90.0)
    eff = float(scale) * asset_mpu(asset_name)
    if abs(eff - 1.0) > 1e-9:
        xf.AddScaleOp().Set(Gf.Vec3f(eff, eff, eff))
    geo = stage.DefinePrim(path + "/Geo")
    geo.GetReferences().AddReference(asset_path(asset_name, base_dir or _stage_dir(stage)))
    return xf


def _style_material(stage, looks, style, slot, base_dir):
    """UsdShade material for a room style + slot (wall/floor/ceiling), created once per
    scene under /World/Looks; None when the style keeps the kit material or the MDL
    is not downloaded (tools/asset_library.py fetch)."""
    if not style or not slot:
        return None
    key = (style, slot)
    if key in looks:
        return looks[key]
    rel = (STYLES.get(style) or {}).get(slot)
    mdl = os.path.join(LIBRARY_DIR, "nvidia", *rel.split("/")) if rel else None
    if not mdl or not os.path.isfile(mdl):
        looks[key] = None
        return None
    path = "/World/Looks/%s_%s" % (safe_name(style), slot)
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, path + "/Shader")
    sh.CreateImplementationSourceAttr(UsdShade.Tokens.sourceAsset)
    try:
        ref = os.path.relpath(mdl, base_dir).replace("\\", "/")
    except ValueError:
        ref = mdl.replace("\\", "/")
    sh.SetSourceAsset(Sdf.AssetPath(ref if ref.startswith("../") else "./" + ref), "mdl")
    sh.SetSourceAssetSubIdentifier(os.path.splitext(os.path.basename(mdl))[0], "mdl")
    out = sh.CreateOutput("out", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput("mdl").ConnectToSource(out)
    looks[key] = mat
    return mat


def add_light(stage, base_path, cx, cy, light_mesh=None, base_dir=None):
    """Light fixture (mesh) + an already-on SphereLight source at the cell center."""
    if light_mesh is None:
        light_mesh = LIGHT_MESH
    place(stage, base_path + "_Fixture", light_mesh, (cx, cy, WALL_H - 0.02),
          base_dir=base_dir)
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
# ----------------------------------------------------------------------------
# Simulation readiness: semantics, colliders, robot markers
# ----------------------------------------------------------------------------
STRUCT_CLASS = {"floor": "floor", "ceiling": "ceiling", "wall": "wall", "cap": "wall",
                "door": "door", "window": "window", "glass": "glass_wall"}
_OFFICE_CLASS = {"Desks": "table", "Chairs": "seating", "Cabinets": "storage",
                 "Machines": "appliance", "Decor": "decor"}


def semantic_class(asset):
    """Semantic class of a furniture asset: library category, Office palette category,
    else 'furniture'."""
    lib = load_library().get(asset)
    if lib and lib.get("category"):
        return lib["category"]
    for cat, names in FURNITURE_CATEGORIES.items():
        if asset in names:
            return _OFFICE_CLASS.get(cat, "furniture")
    return "furniture"


def set_semantic(prim, cls):
    """Replicator semantic label (taxonomy 'class') on prim (inherited by its subtree)."""
    if UsdSemantics is None or not cls:
        return
    api = UsdSemantics.LabelsAPI.Apply(prim, "class")
    api.CreateLabelsAttr().Set([cls])


def add_colliders(stage, root_prim):
    """Static triangle-mesh colliders on every mesh under root_prim (a referenced prop).

    Instanced sub-trees are de-instanced first (instance proxies cannot be edited).
    Returns the number of collider meshes.
    """
    changed = True
    while changed:
        changed = False
        for pr in Usd.PrimRange(root_prim):
            if pr.IsInstance():
                pr.SetInstanceable(False)
                changed = True
                break
    n = 0
    for pr in Usd.PrimRange(root_prim):
        if pr.IsA(UsdGeom.Mesh):
            UsdPhysics.CollisionAPI.Apply(pr)
            UsdPhysics.MeshCollisionAPI.Apply(pr).CreateApproximationAttr(UsdPhysics.Tokens.none)
            n += 1
    return n


def add_robot_markers(stage, robot):
    """/World/Robot/Spawn (+ Footprint of the robot model) + /World/Robot/Waypoints/WP_xx
    (guide-purpose markers)."""
    if not robot:
        return 0
    UsdGeom.Scope.Define(stage, "/World/Robot")
    n = 0
    sp = robot.get("spawn")
    if sp:
        xf = UsdGeom.Xform.Define(stage, "/World/Robot/Spawn")
        xf.AddTranslateOp().Set(Gf.Vec3d(float(sp["x"]), float(sp["y"]), 0.0))
        xf.AddRotateZOp().Set(float(sp.get("yaw", 0.0)))
        cone = UsdGeom.Cone.Define(stage, "/World/Robot/Spawn/Marker")
        cone.CreateRadiusAttr(0.2)
        cone.CreateHeightAttr(0.4)
        cone.CreateAxisAttr("X")                     # points along the robot heading
        cone.CreatePurposeAttr(UsdGeom.Tokens.guide)
        xf.GetPrim().SetCustomDataByKey("robot:role", "spawn")
        spec = robots.get(robot.get("model"))
        if spec:                                     # footprint outline of the robot model
            xf.GetPrim().SetCustomDataByKey("robot:model", spec["id"])
            pts = [Gf.Vec3f(float(x), float(y), 0.01) for x, y in spec["footprint"]["points"]]
            curve = UsdGeom.BasisCurves.Define(stage, "/World/Robot/Spawn/Footprint")
            curve.CreateTypeAttr(UsdGeom.Tokens.linear)
            curve.CreateWrapAttr(UsdGeom.Tokens.periodic)
            curve.CreatePointsAttr(pts)
            curve.CreateCurveVertexCountsAttr([len(pts)])
            curve.CreateWidthsAttr([0.01])
            curve.CreatePurposeAttr(UsdGeom.Tokens.guide)
        n += 1
    UsdGeom.Scope.Define(stage, "/World/Robot/Waypoints")
    for k, wp in enumerate(robot.get("waypoints") or []):
        path = "/World/Robot/Waypoints/WP_%02d" % k
        xf = UsdGeom.Xform.Define(stage, path)
        xf.AddTranslateOp().Set(Gf.Vec3d(float(wp[0]), float(wp[1]), 0.0))
        s = UsdGeom.Sphere.Define(stage, path + "/Marker")
        s.CreateRadiusAttr(0.12)
        s.CreatePurposeAttr(UsdGeom.Tokens.guide)
        xf.GetPrim().SetCustomDataByKey("robot:waypoint_index", k)
        n += 1
    return n


def _new_stage(out_path):
    """File-backed USDA stage at out_path (relative references resolve while building)."""
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    layer = Sdf.Layer.Find(out_path)
    if layer:
        layer.Clear()
    else:
        layer = Sdf.Layer.CreateNew(out_path, args={"format": "usda"})
    return Usd.Stage.Open(layer)


def build_scene(map_data, out_path, physics=True, semantics=True):
    """Dung Scene .usd (USDA text) tu map_data. Tra ve dict thong ke.

    physics: PhysicsScene + static triangle-mesh colliders on floors, walls, doors,
             windows, glass and furniture (ceilings / lights excluded).
    semantics: UsdSemantics class labels (floor, wall, door, window, glass_wall, ceiling,
             furniture category) for Replicator segmentation / bounding boxes.
    """
    if Usd is None:
        raise RuntimeError("OpenUSD (pxr) is not available: install Isaac Sim (C:\\isaacsim "
                           "or $ISAACSIM) or usd-core to build .usd scenes")
    import architecture as arch
    struct = dict(map_data.get("structure") or {})
    light_p = struct.get("light", LIGHT_MESH)
    missing = [n for n in arch.required_assets(map_data) if not asset_exists(n)]
    if missing:
        raise RuntimeError("Thieu module cau truc: %s (trong %s)" % (missing, PROP_DIRS))

    nx, ny, cells, vedges, hedges, furniture = parse_map(map_data)

    out_dir = os.path.dirname(os.path.abspath(out_path))   # asset paths relative to here
    stage = _new_stage(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    for scope in ("Structure", "Doors", "Lights", "Furniture", "Looks"):
        UsdGeom.Scope.Define(stage, "/World/" + scope)
    if physics:
        scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
        scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
        scene.CreateGravityMagnitudeAttr(9.81)

    stats = {"floor": 0, "ceiling": 0, "light": 0, "wall": 0, "door": 0, "window": 0,
             "glass": 0, "cap": 0, "furniture": 0, "skipped": [], "styles": {},
             "colliders": 0, "labeled": 0, "robot_markers": 0}
    looks = {}

    # Shell: floors, ceilings, wall panels, caps, doors, windows, glass
    for it in arch.plan_structure(map_data):
        parent = "/World/Doors/" if it["kind"] == "door" else "/World/Structure/"
        xf = place(stage, parent + it["name"], it["asset"], it["pos"], rot_z=it["yaw"],
                   base_dir=out_dir)
        geo = stage.GetPrimAtPath(xf.GetPath().AppendChild("Geo"))
        mat = _style_material(stage, looks, it["style"], it["slot"], out_dir)
        if mat is not None:
            UsdShade.MaterialBindingAPI.Apply(geo).Bind(
                mat, UsdShade.Tokens.strongerThanDescendants)
        k = it["kind"]
        if semantics:
            set_semantic(xf.GetPrim(), STRUCT_CLASS.get(k))
            stats["labeled"] += 1
        if physics and k != "ceiling":
            stats["colliders"] += add_colliders(stage, geo)
        if k in stats:
            stats[k] += 1
        if it["style"] and it["slot"] == "floor":
            stats["styles"][it["style"]] = stats["styles"].get(it["style"], 0) + 1
    stats["door"] //= 3                                # frame + leaf + handle per door
    stats["wall"] //= 2                                # two panels per wall edge
    for i, j, cx, cy in arch.lights(map_data):
        add_light(stage, "/World/Lights/Lamp_%d_%d" % (i, j), cx, cy, light_p,
                  base_dir=out_dir)
        stats["light"] += 1

    # Furniture
    for idx, f in enumerate(furniture):
        name = f["asset"]
        if not asset_exists(name):
            stats["skipped"].append(name)
            continue
        path = "/World/Furniture/%s_%d" % (safe_name(name), idx)
        xf = place(stage, path, name, (float(f["x"]), float(f["y"]), 0.0),
                   rot_z=float(f.get("yaw", 0.0)), base_dir=out_dir)
        if semantics:
            set_semantic(xf.GetPrim(), semantic_class(name))
            stats["labeled"] += 1
        if physics:
            stats["colliders"] += add_colliders(stage, stage.GetPrimAtPath(path + "/Geo"))
        stats["furniture"] += 1

    stats["robot_markers"] = add_robot_markers(stage, map_data.get("robot"))
    stage.GetRootLayer().Save()
    stats["out"] = out_path
    return stats


if __name__ == "__main__":
    cells = {}
    for i in range(3):
        for j in range(2):
            cells[(i, j)] = 1
    cells[(1, 0)] = 2  # light
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
