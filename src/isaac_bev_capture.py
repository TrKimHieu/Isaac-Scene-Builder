r"""
isaac_bev_capture.py - Chup anh BEV (top-down) cua prop trong Isaac Sim.

Quy trinh (kieu spawn-lo + an/hien):
  - 1 scene tam: mieng SAN TRANG phat sang + dome/key light -> nen trang, deu.
  - Camera TRUC GIAO (orthographic) nhin thang xuong, khung khit o 3x3 m
    (khong diem tu). USD: be rong khung = aperture * 0.1 -> aperture = 30 cho 3 m.
  - Nap props theo LO (CHUNK), spawn tai goc (0,0,0) va AN het; roi HIEN lan luot
    tung prop de chup, chup xong AN lai; het lo thi xoa lo (giai phong RAM).
  - Ep nen ve trang tuyet doi (theo mau 4 goc) -> "cai gi khong trang la object".
  - Xuat PNG vao output/mesh_shapes/renders/<asset>.png
  => Sau do mo shape_editor.py de ve bounding + cat shape tu cac anh nay.

*** PHAI CHAY BANG PYTHON CUA ISAAC SIM ***, vi du (Windows):
    C:\IsaacProjects\isaacsim\python.bat src/isaac_bev_capture.py --all
    C:\IsaacProjects\isaacsim\python.bat src/isaac_bev_capture.py SM_Sofa   (1 prop + chan doan)

Ghi chu:
  - APERTURE_SCALE=10 -> aperture=30 -> khung 3 m. Neu khung lech, chinh hang so nay.
  - VERTICAL_FLIP: lat doc cho khop huong top-down cua editor (y huong xuong).
  - CHUNK: so prop spawn dong thoi (bao ve RAM khi chup ca 465 prop).
"""
import os
import argparse

from config import (PROP_DIRS, RENDER_DIR, CELL, RESOLUTION, CAM_HEIGHT,
                    APERTURE_SCALE, VERTICAL_FLIP, SETTLE_FRAMES, SHOW_FRAMES,
                    CHUNK_SIZE, GROUND_SIZE, PROJECT_ROOT)
from utils import safe_name as _safe_name


def parse_args():
    ap = argparse.ArgumentParser(description="Chup BEV top-down cac prop trong Isaac Sim.")
    ap.add_argument("asset", nargs="?", default=None, help="Ten 1 prop (khong .usd). Bo trong + --all de chup tat ca.")
    ap.add_argument("--all", action="store_true", help="Chup toan bo prop trong moi PROP_DIRS.")
    ap.add_argument("--extra", action="store_true", help="Chi chup prop trong assets/extra/ (asset moi tai ve).")
    ap.add_argument("--res", type=int, default=RESOLUTION)
    ap.add_argument("--out", default=RENDER_DIR)
    return ap.parse_args()


def _prop_dirs():
    """Danh sach thu muc chua prop (tuyet doi)."""
    return PROP_DIRS


def _index_props():
    """Map ten -> duong dan .usd, quet qua tat ca PROP_DIRS (uu tien thu muc dau)."""
    idx = {}
    for d in _prop_dirs():
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".usd"):
                n = os.path.splitext(f)[0]
                idx.setdefault(n, os.path.join(d, f))
    return idx


def asset_list(args):
    """Danh sach (ten, duong_dan_usd) can chup, quet ca assets/office/Props + assets/extra/."""
    idx = _index_props()
    try:
        import scene_builder as sb
        palette = [n for (n, _r) in sb.FURNITURE]
    except Exception:
        palette = []
    if args.asset:
        names = [args.asset]
    elif args.extra:
        extra_dir = PROP_DIRS[1] if len(PROP_DIRS) > 1 else None
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(extra_dir)
                       if f.lower().endswith(".usd")) if os.path.isdir(extra_dir) else []
    elif args.all:
        names = sorted(idx.keys())            # toan bo prop trong moi thu muc
    else:
        names = (palette[:1] or sorted(idx.keys())[:1])
    out = []
    for n in names:
        p = idx.get(n) or os.path.join(PROP_DIRS[0], n + ".usd")
        if os.path.isfile(p):
            out.append((n, p))
        else:
            print("[bo qua] khong thay:", n)
    return out


# ---------------------------------------------------------------------------
# Main (chi chay duoc trong Isaac Sim)
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    res = args.res
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    targets = asset_list(args)
    if not targets:
        print("Khong co prop de chup.")
        return

    # 1) Khoi dong Isaac Sim (headless) TRUOC khi import cac module con lai.
    os.environ.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")
    try:                                   # Isaac Sim 4.5 / 5 / 6 (namespace moi)
        from isaacsim import SimulationApp
    except ImportError:                    # Isaac Sim <= 4.2 (namespace cu)
        from omni.isaac.kit import SimulationApp
    sim_app = SimulationApp({"headless": True, "renderer": "RayTracedLighting"})

    import numpy as np
    from PIL import Image
    from pxr import Usd, UsdGeom, UsdLux, UsdShade, Gf, Sdf
    import omni.usd
    import omni.replicator.core as rep
    try:                                   # namespace moi (isaacsim.*)
        from isaacsim.core.utils.stage import add_reference_to_stage
    except ImportError:                    # namespace cu (omni.isaac.*)
        from omni.isaac.core.utils.stage import add_reference_to_stage

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(stage, "/World")

    # 2) Nen trang phang (plane phat sang trang tuyet doi -> khong bong)
    _make_white_ground(stage, UsdGeom, UsdShade, Gf, Sdf, size=GROUND_SIZE)

    # 3) Anh sang deu (dome trang) de vat sang ro
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.CreateIntensityAttr(400.0)
    dome.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    key = UsdLux.DistantLight.Define(stage, "/World/KeyLight")
    key.CreateIntensityAttr(500.0)
    key.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    UsdGeom.Xformable(key).AddRotateXYZOp().Set(Gf.Vec3f(-90, 0, 0))  # chieu thang xuong

    # 4) Camera orthographic nhin thang xuong (prim USD thuan, khong dung sensor)
    cam_xf = UsdGeom.Camera.Define(stage, "/World/TopCam")
    UsdGeom.Xformable(cam_xf).AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, CAM_HEIGHT))
    cam_prim = stage.GetPrimAtPath("/World/TopCam")
    _c = UsdGeom.Camera(cam_prim)
    _c.GetProjectionAttr().Set("orthographic")
    ap = CELL * APERTURE_SCALE
    _c.GetHorizontalApertureAttr().Set(ap)
    _c.GetVerticalApertureAttr().Set(ap)
    _c.CreateClippingRangeAttr().Set(Gf.Vec2f(0.01, 100000.0))

    # 4b) Render qua Replicator (dang tin cay cho headless): render_product + rgb annotator
    render_product = rep.create.render_product("/World/TopCam", (res, res))
    rgb_annot = rep.AnnotatorRegistry.get_annotator("rgb")
    rgb_annot.attach([render_product])

    def render(n):
        for _ in range(n):
            try:
                rep.orchestrator.step(rt_subframes=8, delta_time=0.0, pause_timeline=False)
            except TypeError:
                try:
                    rep.orchestrator.step(rt_subframes=8)
                except TypeError:
                    sim_app.update()

    def grab_rgb():
        data = rgb_annot.get_data()
        arr = np.asarray(data)
        if arr.size == 0:
            return None
        return arr[..., :3]              # bo alpha

    props_root = "/World/Props"
    UsdGeom.Scope.Define(stage, props_root)
    n_done = 0
    total = len(targets)
    debug = (total == 1)                  # chay 1 prop -> in chan doan + luu anh raw
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                   [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])

    # 5) Chup theo LO: spawn ca lo (an het) -> hien/chup/an tung cai -> xoa lo
    for base in range(0, total, CHUNK_SIZE):
        chunk = targets[base:base + CHUNK_SIZE]
        spawned = []
        for name, usd_path in chunk:
            ppath = props_root + "/" + _safe_name(name)
            # Isaac tu chuan hoa don vi (metersPerUnit) khi reference -> khong scale tay
            add_reference_to_stage(usd_path=usd_path.replace("\\", "/"), prim_path=ppath)
            UsdGeom.Imageable(stage.GetPrimAtPath(ppath)).MakeInvisible()
            spawned.append((name, ppath))
        # nap xong ca lo (chi 1 lan)
        render(SETTLE_FRAMES)

        for name, ppath in spawned:
            prim = stage.GetPrimAtPath(ppath)
            UsdGeom.Imageable(prim).MakeVisible()
            render(SHOW_FRAMES)

            if debug:
                _debug_prop(name, prim, stage, None, cam_prim, bbox_cache, out_dir,
                            np, Image, Usd, UsdGeom)
                cc = UsdGeom.Camera(cam_prim)
                m = UsdGeom.Xformable(cam_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
                print("[dbg] cam T=%s proj=%s hAp=%.2f clip=%s" % (
                    tuple(round(v, 2) for v in m.ExtractTranslation()),
                    cc.GetProjectionAttr().Get(), cc.GetHorizontalApertureAttr().Get(),
                    cc.GetClippingRangeAttr().Get()), flush=True)

            rgb = grab_rgb()
            if rgb is None:
                print("[skip] chua co anh:", name, flush=True)
                UsdGeom.Imageable(prim).MakeInvisible()
                continue
            raw = _rgba_to_white_rgb(rgb, np, Image)
            if debug:
                a = np.asarray(raw)
                print("[dbg] raw min=%d max=%d mean=%d" % (a.min(), a.max(), int(a.mean())), flush=True)
                raw.save(os.path.join(out_dir, name + "_raw.png"))
            img = _snap_background_white(raw, np, Image)
            if VERTICAL_FLIP:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            img.save(os.path.join(out_dir, name + ".png"))
            UsdGeom.Imageable(prim).MakeInvisible()
            n_done += 1
            print("[ok] %d/%d %s.png" % (n_done, total, name), flush=True)

        # xoa ca lo de giai phong RAM truoc lo sau
        for _, ppath in spawned:
            _clear_prim(stage, ppath)
        render(1)

    print("HOAN TAT: %d / %d anh -> %s" % (n_done, total, out_dir), flush=True)
    sim_app.close()


def _debug_prop(name, prim, stage, cam, cam_prim, bbox_cache, out_dir,
                np, Image, Usd, UsdGeom):
    """Chan doan cho lan chay 1 prop: in so Gprim + world bbox cua prop."""
    bbox_cache.Clear()
    gprims = sum(1 for p in Usd.PrimRange(prim) if p.IsA(UsdGeom.Gprim))
    try:
        rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        print("[dbg] %s Gprim=%d bbox min=%s max=%s" % (
            name, gprims, tuple(round(v, 3) for v in rng.GetMin()),
            tuple(round(v, 3) for v in rng.GetMax())), flush=True)
    except Exception as e:
        print("[dbg] bbox loi:", e, flush=True)


_MPU = {}


def _read_mpu(path, Usd, UsdGeom):
    """metersPerUnit cua file prop (cache). Prop cm -> 0.01."""
    if path in _MPU:
        return _MPU[path]
    v = 1.0
    try:
        st = Usd.Stage.Open(path)
        v = UsdGeom.GetStageMetersPerUnit(st) or 1.0
    except Exception:
        v = 1.0
    _MPU[path] = v
    return v


def _make_white_ground(stage, UsdGeom, UsdShade, Gf, Sdf, size):
    """Mieng quad lon o z=0, vat lieu UsdPreviewSurface emissive trang tuyet doi."""
    mesh = UsdGeom.Mesh.Define(stage, "/World/Ground")
    h = size / 2.0
    mesh.CreatePointsAttr([Gf.Vec3f(-h, -h, 0), Gf.Vec3f(h, -h, 0),
                           Gf.Vec3f(h, h, 0), Gf.Vec3f(-h, h, 0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateNormalsAttr([Gf.Vec3f(0, 0, 1)] * 4)

    mat = UsdShade.Material.Define(stage, "/World/Ground/WhiteMat")
    shader = UsdShade.Shader.Define(stage, "/World/Ground/WhiteMat/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1, 1, 1))
    # emissive > 1 de bao hoa -> nen trang khi qua tonemap
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(6, 6, 6))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(mesh).Bind(mat)


def _clear_prim(stage, path):
    if stage.GetPrimAtPath(path):
        stage.RemovePrim(path)


def _snap_background_white(img, np, Image, delta=14):
    """Ep pixel gan mau NEN (lay tu 4 goc) ve trang tuyet doi 255.

    Nen la mieng phang duoc chieu deu -> mau dong nhat; object khac mau nen.
    Nho vay du tonemap lam nen thanh xam (vd 233), ta van co nen trang sach de
    shape_editor tach shape ("chi thu khong trang la object").
    """
    a = np.asarray(img).astype(np.int16)
    h, w, _ = a.shape
    corners = np.stack([a[0, 0], a[0, w - 1], a[h - 1, 0], a[h - 1, w - 1]])
    bg = np.median(corners, axis=0)
    dist = np.abs(a - bg).max(axis=2)
    mask_bg = dist <= delta
    out = a.copy()
    out[mask_bg] = 255
    return Image.fromarray(out.astype("uint8"), mode="RGB")


def _rgba_to_white_rgb(rgba, np, Image):
    """Ep kieu -> RGB, gop nen trang (phong khi co alpha)."""
    a = np.asarray(rgba)
    if a.dtype != np.uint8:
        a = (np.clip(a, 0.0, 1.0) * 255).astype(np.uint8)
    if a.shape[-1] == 4:
        rgb = a[..., :3].astype(np.float32)
        alpha = a[..., 3:4].astype(np.float32) / 255.0
        white = np.full_like(rgb, 255.0)
        comp = (rgb * alpha + white * (1.0 - alpha)).astype(np.uint8)
    else:
        comp = a[..., :3]
    return Image.fromarray(comp, mode="RGB")


if __name__ == "__main__":
    main()
