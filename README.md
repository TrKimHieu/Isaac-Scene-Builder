<div align="center">

**English** · [Tiếng Việt](README.vi.md)

# Isaac Scene Builder

### Draw a 2D floor plan → get a 3D USD scene for **NVIDIA Isaac Sim** + a **BEV** map for robot navigation

A simple grid editor: paint floors, drag walls, drop furniture —
the tool builds a USD scene and a top-down occupancy map (ROS-ready).
**No USD or programming knowledge required.**

<br>

![Python](https://img.shields.io/badge/Python-3.12+-6366F1?style=flat-square&logo=python&logoColor=white)
![pygame](https://img.shields.io/badge/pygame-2.5+-818CF8?style=flat-square)
![Pillow](https://img.shields.io/badge/Pillow-•-818CF8?style=flat-square)
![numpy](https://img.shields.io/badge/numpy-•-818CF8?style=flat-square)
![Tests](https://img.shields.io/badge/tests-55%20passing-34D399?style=flat-square)
![Isaac Sim](https://img.shields.io/badge/NVIDIA-Isaac%20Sim-76B900?style=flat-square&logo=nvidia&logoColor=white)

<br>

![Isaac Scene Builder UI](docs/images/editor.png)

<sub>The real editor — a room with walls (white), ceiling lights (amber) and furniture (blue); the selected item has a violet ring and a coordinate/size panel on the right.</sub>

</div>

<br>

## Workflow — three steps, from sketch to robot map

> Each grid cell = **1×1 meter** (stronger lines every 3 m, one kit module). You only work in step 1; the next two are a single keypress.

| Step | You do | Result |
|:---:|---|---|
| **01** | Design the 2D plan — paint floors, drag walls, drop furniture | A visual grid map |
| **02** | Press **`S`** | `scene.usd` — a 3D scene that opens directly in Isaac Sim, walls aligned to the grid |
| **03** | Press **`B`** | A black-and-white BEV map + `CSV/SVG/PGM/YAML` for ROS `map_server` |

<br>

## ✨ Features

| | |
|---|---|
| **3 drawing tools**<br>`Floor` paint · `Wall` drag · `Furniture` drop. Drag to fill whole areas / long segments. | 🎛️ **Precise inspector**<br>Click an item to edit its X/Y position, rotation and shape — type numbers directly or hit `−` `+`. |
| **3 shape types**<br>**BBox** (box) · **Sphere** (circle) · **Mesh** (real footprint). Pick one and new props default to it. | 🪑 **68 furniture models**<br>Desks, chairs, sofas, cabinets, plants… including official **NVIDIA** assets. Search by name & filter by category. |
| **Undo/Redo & Zoom**<br>`Ctrl+Z`/`Ctrl+Y` (50 steps) · `Ctrl`+wheel to zoom · hold the middle button to pan. | 📤 **Tidy per-scene export**<br>Each scene gets its own folder under `output/` — USD, BEV and metadata, ready to hand to a robot. |

<br>

## The BEV map — what the robot actually reads

<div align="center">

![BEV occupancy map](docs/images/bev.png)

</div>

Seen from above, each pixel carries a state — this is the *occupancy grid* ROS uses for path planning. It is metrically accurate (**1 px = 2.5 cm**) and ships with a `.yaml` you can load straight into `map_server`.

| Color | Value | Meaning |
|:---:|:---:|---|
| ⬜ White | `254` | **Walkable** (free space) |
| ⬛ Black | `0` | **Occupied** — walls + furniture |
| ◾ Gray | `205` | **Unknown** / outside the room |

<br>

## Quick start

> Needs Python 3.12+ and `pygame`, `Pillow`, `numpy` — install with `pip install -r requirements.txt`.

**1 · Open the editor**
```bash
editor.bat                 # Windows: double-click
# or
python src/scene_editor.py
```

**2 · Draw a room**
```text
1  Floor      → click / drag to paint floor
W             → auto-generate boundary walls
2  Wall       → pick wall / door / window / glass / opening in the panel, click or drag
                along a row; click a door to edit it (O open, P swing, H hinge, A auto-fit)
4  Style      → paint a room style (Office / Hospital / Warehouse / Home) on the floor
3  Furniture  → pick in the palette, click to place  (hold left + drag to move)
```

Walls are built like NVIDIA's office scene: two back-to-back panels (each face takes the
style of the room it looks into), capped at free ends and corners; doors get a real frame +
leaf (open by default). The Office kit is made of 3 m modules, so on the 1 m grid collinear
edges are merged into runs: walls are filled with 3 m panels and one 2 m / 1 m panel
shortened along its length, a window run gets SM_Window_3m per 3 m and glazing for the rest,
glass walls use the 2 m + 1 m panels, and a door takes one 1 m edge (its 1.05 m frame covers
the wall ends). Floors and ceilings are one mesh per room style with the kit tile's own
material and UVs (st = xy / 3 m), so tiles keep their real size. Examples:
`data/maps/demo_1m_grid.json` (2 m corridor, 2 x 2 m store, 2 x 3 m WC) and
`data/maps/demo_architecture.json`.

Maps saved before the 1 m grid (3 m cells, no `"cell"` key) still open everywhere: each old
cell becomes 3 x 3 cells, a door moves to the middle 1 m edge of its old side, a lamp stays
in the block centre. `python tools/migrate_maps.py` rewrites the files themselves.

**Procedural scenes** (`src/map_generator.py`, deterministic per seed)
```bash
python tools/batch_generate_scenes.py --count 20 [--theme office|hospital|warehouse|residential]
                                      [--density 0.12 0.3] [--size 8 6] [--seed 1] [--no-usd]
python tools/check_density_distribution.py [--maps "data/maps/generated/*.json"]
```
- Layouts: corridor + rooms (office / hospital), BSP rooms with an optional missing corner
  (home), hall + office strip (warehouse); doors along a spanning tree, an entrance, windows,
  glass fronts for meeting rooms; per-room style and lights.
- Furniture by room type (desk + chair, table + chairs, bed + nightstand, rack rows with
  aisles, ...) from the measured footprints; every item must keep all doors and >= 90 % of
  the free space reachable for the chosen robot (`--robot`, footprint radius + 5 cm). Spawn at
  the entrance, one waypoint per room.
- Output per map: `data/maps/generated/gen_XXXX.json` (editable), BEV + height occupancy +
  Nav2 files, `.usd` with colliders / semantics; `index.csv` + density report & histogram.

**Simulation-ready output**
- `.usd`: `PhysicsScene` + static colliders on floors, walls, doors, windows, glass and every
  furniture mesh; `UsdSemantics` class labels (`floor`, `wall`, `door`, `window`, `glass_wall`,
  `ceiling`, furniture category such as `table`, `seating`, `medical`) for Replicator
  segmentation / bounding boxes; robot spawn + waypoints as `/World/Robot` markers.
- **Doors:** a lintel (wall panels with the room's style) fills the wall above every door
  and opening up to the ceiling; openings also get a soffit. Each door has a swing side (P)
  and a hinge side (H, `"door_hinge"` in the map); the plan draws the leaf and its swing arc,
  red when the leaf would run into a wall. New and generated doors are fitted automatically
  (`architecture.best_door_setup`), A re-fits one.
- **Panel:** tool tabs, a hint card with the mouse / keys of the current tool, the tool's
  own controls (edge types with colour swatches, door inspector with a zoomed plan, room
  styles, robot route), the map size in meters, and a fixed bar for undo / save / export.
- **Furniture tool (3):** thumbnail library of the top-down captures, a placement preview
  (green = free, red = no room), grid 50 / 25 / 10 / 5 cm or free (G), wall magnet (M) that
  slides props flush against walls and other props, no overlap (K) with walls, doorways, door
  leaves and other props; Alt = free move, arrows nudge, Del / Ctrl+D delete / duplicate.
- **Robot tool (5):** pick the robot model, click = waypoint, Shift+click = spawn, wheel =
  heading, right-click = remove. The footprint is drawn to scale at the spawn.
- **Robot models** (`data/robots/<id>.json` + `.svg`, `python tools/import_robots.py`):
  TurtleBot3 Burger / Waffle Pi / TurtleBot 4 / 4 Lite from the navsim presets; JetAuto Pro and
  JetBot outlines traced from their own meshes (`JetRobots/assets/.../jetauto_pro.usd`,
  `jetbot.usd`; navsim only has a centred box for JetAuto). The model sets the generator's path
  width, the Nav2 `footprint` (convex hull) / `robot_radius` in `<stem>_nav.yaml` and the outline
  under `/World/Robot/Spawn` in the USD.
- **Height occupancy:** `python tools/slice_footprints.py [--z 0.05 0.50]` cuts every prop's real
  mesh at robot-body height; BEV export then also writes `<stem>_occ_<z0>-<z1>.pgm/.yaml`
  (a low robot drives under table tops; glass-top tables block only at their legs).
  Open door leaves are obstacles in both maps.
- **ROS 2 / Nav2:** the PGM + YAML map frame equals the USD world frame; `<stem>_nav.yaml`
  (initial pose + waypoints) and `follow_waypoints.py` (nav2_simple_commander) are exported
  with the BEV.
- OpenUSD is loaded from Isaac Sim's bundle (`C:\isaacsim` or `$ISAACSIM`) when `pxr` is not
  installed, so the editor writes `.usd` from plain Python. Translucent glass is skipped by
  Replicator segmentation unless translucency is enabled in its settings.

**3 · Export — one key**
```text
S  →  output/scenes/sceneN.usd     # 3D scene for Isaac Sim
B  →  output/bev/sceneN/           # BEV map for the robot (5 formats)
```

<br>

## ⌨️ Shortcuts

| Key | Action | Key | Action |
|:---:|---|:---:|---|
| `1`–`5` | Floor / Wall / Furniture / Style / Robot | `Ctrl+Z` `Ctrl+Y` | Undo / Redo |
| `O` | Open / close the door under the cursor | `V` | Mesh view: mask / color |
| `Tab` | Switch tool | `Ctrl`+wheel | Zoom to cursor |
| `R` | Rotate furniture 5° | Middle-drag | Pan the view |
| `W` | Auto boundary walls | `S` / `B` | Export USD / BEV |
| `C` | Clear all | `Ctrl+S` / `L` | Save / Load map |
| `+` `-` | Resize grid | `F11` | Fullscreen |
| `G` | Placement grid 50/25/10/5 cm / free | `M` / `K` | Wall magnet / No overlap |
| Arrows | Nudge selected prop (`Shift` ×5) | `Alt`+drag | Free move |
| `Del` / `Ctrl+D` | Delete / duplicate prop | `P` | Door swings into the other room |
| `H` | Door hinge on the other jamb | `A` | Auto-fit the door (leaf clear of walls) |

<br>

## Project structure

```
isaac-scene-builder/
├── src/                    # Source code
│   ├── config.py           # Single source of truth (paths, colors, catalog)
│   ├── utils.py            # Shared helpers
│   ├── scene_editor.py     # Main GUI (Pygame)
│   ├── scene_builder.py    # Core USD builder
│   ├── bev_export.py       # BEV export (CSV/SVG/PGM/YAML)
│   ├── isaac_bev_capture.py# Capture BEV images in Isaac Sim
│   ├── shape_editor.py     # Manual bounding box/sphere measurement
│   ├── shape_tools.py      # Shape logic (Pillow/numpy)
│   ├── build_furniture_shapes.py  # Auto shape extraction
│   └── generate_scene.py   # Random scene generator
├── assets/                 # 3D assets (NOT versioned — see below)
│   ├── office/             # Office asset pack
│   └── extra/              # Extra assets (drop here)
├── data/                   # maps/ · props_shapes.json · catalog/
├── output/                 # Products: scenes/ · bev/ · mesh_shapes/
├── tests/                  # Test suite (pytest) — 55 tests
└── *.bat                   # Windows launchers: editor, capture, ...
```

<br>

## Adding new assets

The palette **auto-registers**: just drop a self-contained `.usd` into `assets/extra/` and it shows up in the editor.
To get the right size & shape:

```bash
isaacsim\python.bat src/isaac_bev_capture.py <Name>   # 1. capture a BEV image
python src/build_furniture_shapes.py                  # 2. measure W/H/R + cut mesh
python src/scene_editor.py                            # 3. it's now in the palette
```

**Asset library (~260 curated models, office · residential · hospital · warehouse):**
`python tools/asset_library.py fetch` downloads it into `assets/library/` (NVIDIA ArchVis / DigitalTwin / Isaac + Poly Haven CC0).

Compatible asset sources (NVIDIA Omniverse / SimReady) and details: see [`docs/ASSETS.md`](docs/ASSETS.md).

> **Note on Git:** `assets/office/` (~710 MB) and `assets/extra/*.usd` are **not** versioned to keep the repo light.
> After cloning, run `fetch_assets.bat` (or `python tools/fetch_office_assets.py`) to download the Office pack
> from NVIDIA's public Isaac Sim asset server into `assets/office/`; put extra assets into `assets/extra/` yourself. Shape data (`data/props_shapes.json`) & maps (`data/maps/`) are included.

<br>

## Tests

```bash
pytest              # 55 passed
```

<div align="center">
<br>
<sub>2D grid → USD 3D → BEV (ROS) · 68 furniture · 5 export formats </sub>
</div>
