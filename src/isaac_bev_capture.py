r"""
isaac_bev_capture.py - Capture top-down BEV images of props in Isaac Sim.

Pipeline (batch-spawn + hide/show):
  - A temp scene: an emissive WHITE FLOOR plane + dome/key light -> white, even background.
  - Camera TRUC GIAO (orthographic) nhin thang xuong, centered on the prop origin
    (no vanishing point). USD: view width = aperture * 0.1 -> aperture = 30 for 3 m.
    The frame is chosen PER PROP from its bbox (FRAME_STEPS: 3, 4.5, 6, 9, 12, 18 m)
    so big props are not clipped; <asset>.json next to the PNG records frame_m.
  - Load props in BATCHES (CHUNK), spawn at origin (0,0,0) all HIDDEN; then SHOW one by one
    to capture, then HIDE again; clear the batch when done (free RAM).
  - Snap background to pure white (from the 4 corners) -> "anything non-white is object".
  - Save PNG (true colors, white bg) + <asset>.json to output/mesh_shapes/renders/
  => Then build_furniture_shapes.py measures bbox/sphere and cuts the mesh mask + the
     colored top-down cut-out (or shape_editor.py to do it by hand).

*** PHAI CHAY BANG PYTHON CUA ISAAC SIM ***, vi du (Windows):
    C:\IsaacProjects\isaacsim\python.bat src/isaac_bev_capture.py --all
    C:\IsaacProjects\isaacsim\python.bat src/isaac_bev_capture.py SM_Sofa   (1 prop + diagnostics)

Notes:
  - APERTURE_SCALE=10 -> aperture=30 -> 3 m frame. If the frame is off, tune this constant.
  - VERTICAL_FLIP: flip vertically to match the editor top-down orientation (y-down).
  - CHUNK: number of props spawned at once (protects RAM when capturing all 465 props).
"""
import os
import argparse

from config import (PROP_DIRS, RENDER_DIR, LEGACY_CELL as CELL, RESOLUTION, CAM_HEIGHT,
                    APERTURE_SCALE, VERTICAL_FLIP, SETTLE_FRAMES, SHOW_FRAMES,
                    CHUNK_SIZE, GROUND_SIZE, PROJECT_ROOT)
from utils import safe_name as _safe_name, load_library
import shape_tools as st


def parse_args():
    ap = argparse.ArgumentParser(description="Capture top-down BEV of props in Isaac Sim.")
    ap.add_argument("asset", nargs="?", default=None, help="Name of one prop (no .usd). Leave empty + --all to capture everything.")
    ap.add_argument("--all", action="store_true", help="Capture all props across every PROP_DIRS.")
    ap.add_argument("--extra", action="store_true", help="Only capture props in assets/extra/ (newly downloaded assets).")
    ap.add_argument("--office", action="store_true", help="Only capture the Office furniture palette (FURNITURE + EXTRA_FURNITURE).")
    ap.add_argument("--library", action="store_true", help="Only capture the curated asset library (data/asset_manifest.json).")
    ap.add_argument("--res", type=int, default=RESOLUTION)
    ap.add_argument("--chunk", type=int, default=CHUNK_SIZE,
                    help="Props loaded on the GPU per batch (lower it on small-VRAM GPUs, e.g. 1-4).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Capture at most N props this run (0 = all). Used by tools/capture_all.py.")
    ap.add_argument("--exclude-file", default=None,
                    help="Text file with prop names to skip (one per line), e.g. props that crash.")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip props that already have a render (resume an interrupted run).")
    ap.add_argument("--out", default=RENDER_DIR)
    return ap.parse_args()


def _prop_dirs():
    """List of prop directories (absolute)."""
    return PROP_DIRS


def _index_props():
    """Map name -> .usd path, scanning all PROP_DIRS (first dir wins)."""
    idx = {}
    for d in _prop_dirs():
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".usd"):
                n = os.path.splitext(f)[0]
                idx.setdefault(n, os.path.join(d, f))
    for n, e in load_library().items():      # curated asset library (nested dirs)
        idx.setdefault(n, e["abs"])
    return idx


def asset_list(args):
    """List of (name, usd_path) to capture, scanning assets/office/Props + assets/extra/."""
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
    elif args.office:
        from config import FURNITURE, EXTRA_FURNITURE
        names = list(dict.fromkeys([n for (n, _r) in FURNITURE] + list(EXTRA_FURNITURE)))
    elif args.library:
        names = sorted(load_library().keys())
    elif args.all:
        names = sorted(idx.keys())            # all props across every dir
    else:
        names = (palette[:1] or sorted(idx.keys())[:1])
    out = []
    for n in names:
        p = idx.get(n) or os.path.join(PROP_DIRS[0], n + ".usd")
        if os.path.isfile(p):
            out.append((n, p))
        else:
            print("[skip] not found:", n)
    return out


# ---------------------------------------------------------------------------
# Main (runs only inside Isaac Sim)
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    res = args.res
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    targets = asset_list(args)
    if args.skip_existing:
        targets = [(n, p) for (n, p) in targets
                   if not os.path.isfile(os.path.join(out_dir, n + ".png"))]
    if args.exclude_file and os.path.isfile(args.exclude_file):
        with open(args.exclude_file, encoding="utf-8") as fh:
            excl = {ln.strip() for ln in fh if ln.strip()}
        targets = [(n, p) for (n, p) in targets if n not in excl]
    if args.limit > 0:
        targets = targets[:args.limit]
    if not targets:
        print("No props to capture.")
        return

    # 1) Start Isaac Sim (headless) BEFORE importing the remaining modules.
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

    # 2) Flat white background (emissive pure-white plane -> no shadows)
    _make_white_ground(stage, UsdGeom, UsdShade, Gf, Sdf, size=GROUND_SIZE)

    # 3) Even lighting (white dome) so the object is well lit
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.CreateIntensityAttr(400.0)
    dome.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    key = UsdLux.DistantLight.Define(stage, "/World/KeyLight")
    key.CreateIntensityAttr(500.0)
    key.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    UsdGeom.Xformable(key).AddRotateXYZOp().Set(Gf.Vec3f(-90, 0, 0))  # chieu thang xuong

    # 4) Orthographic camera looking straight down (plain USD prim, not the sensor)
    cam_xf = UsdGeom.Camera.Define(stage, "/World/TopCam")
    UsdGeom.Xformable(cam_xf).AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, CAM_HEIGHT))
    cam_prim = stage.GetPrimAtPath("/World/TopCam")
    _c = UsdGeom.Camera(cam_prim)
    _c.GetProjectionAttr().Set("orthographic")
    def set_frame(frame_m):
        ap = frame_m * APERTURE_SCALE
        _c.GetHorizontalApertureAttr().Set(ap)
        _c.GetVerticalApertureAttr().Set(ap)
    set_frame(CELL)
    _c.CreateClippingRangeAttr().Set(Gf.Vec2f(0.01, 100000.0))

    # 4b) Render via Replicator (reliable for headless): render_product + rgb annotator
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
    debug = (total == 1)                  # single prop -> print diagnostics + save raw image
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                   [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])

    # 5) Capture per BATCH: spawn the whole batch (all hidden) -> show/capture/hide each -> clear batch
    chunk_size = max(1, args.chunk)
    for base in range(0, total, chunk_size):
        chunk = targets[base:base + chunk_size]
        spawned = []
        for name, usd_path in chunk:
            print("[start] %s" % name, flush=True)
            ppath = props_root + "/" + _safe_name(name)
            # Isaac auto-normalizes units (metersPerUnit) on reference -> no manual scale
            add_reference_to_stage(usd_path=usd_path.replace("\\", "/"), prim_path=ppath)
            UsdGeom.Imageable(stage.GetPrimAtPath(ppath)).MakeInvisible()
            spawned.append((name, ppath))
        # nap xong ca lo (chi 1 lan)
        render(SETTLE_FRAMES)

        for name, ppath in spawned:
            prim = stage.GetPrimAtPath(ppath)
            UsdGeom.Imageable(prim).MakeVisible()
            bbox_cache.Clear()
            bmin, bmax = (-CELL / 2, -CELL / 2, 0), (CELL / 2, CELL / 2, 0)
            try:
                rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
                if not rng.IsEmpty():
                    bmin, bmax = rng.GetMin(), rng.GetMax()
            except Exception as e:
                print("[warn] bbox %s: %s" % (name, e), flush=True)
            frame_m = st.pick_frame(bmin, bmax)
            set_frame(frame_m)
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
                print("[skip] no image yet:", name, flush=True)
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
            png = os.path.join(out_dir, name + ".png")
            img.save(png)
            st.write_render_meta(png, frame_m, res=res,
                                 bbox_min=[round(float(v), 4) for v in bmin],
                                 bbox_max=[round(float(v), 4) for v in bmax])
            UsdGeom.Imageable(prim).MakeInvisible()
            n_done += 1
            print("[ok] %d/%d %s.png (frame %.1f m)" % (n_done, total, name, frame_m), flush=True)

        # clear the batch to free RAM before the next one
        for _, ppath in spawned:
            _clear_prim(stage, ppath)
        render(1)

    print("DONE: %d / %d images -> %s" % (n_done, total, out_dir), flush=True)
    sim_app.close()


def _debug_prop(name, prim, stage, cam, cam_prim, bbox_cache, out_dir,
                np, Image, Usd, UsdGeom):
    """Diagnostics for a single-prop run: print Gprim count + world bbox of the prop."""
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
    """metersPerUnit of the prop file (cached). cm props -> 0.01."""
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
    """Large quad at z=0 with an emissive pure-white UsdPreviewSurface material."""
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
    # emissive > 1 to saturate -> white background after tonemap
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(6, 6, 6))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(mesh).Bind(mat)


def _clear_prim(stage, path):
    if stage.GetPrimAtPath(path):
        stage.RemovePrim(path)


def _snap_background_white(img, np, Image, delta=14):
    """Snap pixels near the BACKGROUND color (from the 4 corners) to pure white 255.

    The background is an evenly-lit plane -> uniform color; the object differs from it.
    So even if tonemap makes the bg gray (e.g. 233), we still get a clean white bg for
    shape_editor to segment shapes ("anything non-white is object").
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
    """Cast -> RGB, composite over white (in case there is alpha)."""
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
