**English** · [Tiếng Việt](ASSETS.vi.md)

# Adding furniture assets & swapping structural props

The project ships with the **Office** asset pack (`assets/office/Props/*.usd`). You can add
more furniture and change the wall/floor props as described below.

**Getting the Office pack:** `fetch_assets.bat` / `python tools/fetch_office_assets.py [--version 5.1]`
downloads `Isaac/Environments/Office/{Props,Materials}` (~700 MB) from NVIDIA's public asset server into
`assets/office/`, skipping files already present, then checks every prop listed in `src/config.py` exists.

## 0. Curated asset library (office · residential · hospital · warehouse)

`tools/asset_library.py` assembles a de-duplicated multi-environment library from NVIDIA's public
asset server (ArchVis Commercial/Residential/Industrial, DigitalTwin Warehouse, Isaac Hospital &
Simple_Warehouse props) and **Poly Haven (CC0)**:

```bash
python tools/asset_library.py select --budget-gb 20   # scan -> dedupe -> crawl deps -> data/asset_manifest.json
python tools/asset_library.py fetch                   # download every asset + textures/materials
python tools/asset_library.py check                   # every root + every reference present on disk
python tools/asset_library.py sheet --env office      # thumbnail contact sheets to spot near-duplicates
```

- **Dedupe:** variants of one model (colour / size / `_A01.._A09` / `_Var01`) collapse to one family;
  each (environment, category) bucket is capped. Tune with `data/asset_overrides.json`:
  `{"exclude": [ids], "include": [ids], "family_keep": {"family": n}, "caps": {"env/cat": n},
  "category": {"id": "cat"}}`.
- **Layout:** files are mirrored as on the server (`assets/library/nvidia/...`,
  `assets/library/polyhaven/<id>/`) so relative material/texture references keep working.
  `assets/library/` is not versioned; `data/asset_manifest.json` is.
- **Editor / builder:** library ids (`AV_*`, `DT_*`, `HOS_*`, `WH_*`, `PH_*`) appear in the palette
  under extra tabs (Medical, Containers, Carts, Safety, ...); search also matches env/category
  (`hospital`, `warehouse`, ...). Y-up assets are rotated upright automatically.
- **Shapes:** run `isaac_bev_capture.py --library` (in Isaac Sim) then `build_furniture_shapes.py`.
  Each prop is captured top-down in a frame sized to it (3 / 4.5 / 6 / 9 / 12 / 18 m, recorded in
  `renders/<asset>.json`), and yields bbox + sphere + mesh mask (`mesh_shapes/<asset>.png`) + a
  colored top-down cut-out (`mesh_shapes/color/<asset>.png`). In the editor, **V** toggles mesh props
  between the footprint mask and the colored image.
- **Licences:** NVIDIA content is used unmodified under the Omniverse licence (Isaac/Environments
  props are *Limited Use*); do not commit or redistribute it. Poly Haven models are CC0.

## 1. Add new furniture (auto-register)

The palette comes from `scene_builder.available_furniture()` = the curated list (`FURNITURE`)
**+ every `.usd` in `assets/extra/`**. So you only need to:

1. Drop a **self-contained** asset file into `assets/extra/` (see `assets/extra/README.md`).
2. (Recommended) measure the real shape so BEV/editor are accurate:
   - `%ISAACSIM%\python.bat src/isaac_bev_capture.py <Name>`  — capture a white-background BEV image.
   - `python src/build_furniture_shapes.py`  — measure W/H/R + cut the mesh footprint, write `data/props_shapes.json`.
3. Open `src/scene_editor.py` → the asset is in the palette; radius/shape come from `props_shapes.json`
   (default R=0.5 if not measured yet).

To add it to the **curated list** (with a fixed radius): add `("<Name>", <r>)` to `FURNITURE`
in `src/config.py`.

## 2. Where to get Isaac-Sim-compatible USD assets

Requirements: **USD/USDZ, Z-up, meter units, self-contained** (embedded materials or bundled textures).

- **Isaac Sim built-in assets** (installed with Isaac Sim): the `Isaac/Props/`,
  `Isaac/Environments/` libraries, and **SimReady Assets** (furniture, bins, pallets, …). Point to
  the Isaac Sim asset root (local Nucleus or install folder) and copy the `.usd` you need into `assets/extra/`.
- **NVIDIA Omniverse — SimReady Explorer / Asset Browser**: a library of SimReady, USD-standard
  furniture/objects; drag-and-drop or export `.usd`.
- **Public USDZ sources** (3D models): galleries that offer `.usdz` downloads (Apple Quick Look gallery,
  Sketchfab USDZ export, …). `.usdz` is a self-contained package, ideal for dropping into `assets/extra/`.

Notes:
- If an asset is authored in **cm**, the prop may carry `xformOp:scale = 0.01` like the Office pack — that's
  fine; just capture a BEV and confirm the footprint comes out at a sensible meter size.
- If the footprint is flipped/rotated, toggle `VERTICAL_FLIP` in `src/isaac_bev_capture.py`
  or re-orient it in `src/shape_editor.py`.

## 3. Swapping wall/floor props (structure)

In `src/scene_editor.py`, the **"STRUCTURE (3D)"** panel group has two cycle buttons:
- **Wall:** `SM_Wall_3m` (default) / `SM_Window_3m_A` / `SM_Window_3m_B` / `SM_Wall_3m_doorElevator`.
- **Floor:** `SM_Floor_3m`.

The choice is saved into the map (`structure`) and passed to `build_scene` when you export `.usd`.
Use props that are **exactly 3 m long** so they match the grid (2m/6m walls and 6m floors do not fit).
To add more options, edit `STRUCTURE_CHOICES` in `src/config.py`.

> Note: walls are **auto-centered on the grid line** (from the prop's real bbox), so swapping to a
> wall prop with a different thickness still lands exactly on the grid line.
