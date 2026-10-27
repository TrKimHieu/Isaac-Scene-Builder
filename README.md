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

> Each grid cell = **3×3 meters**. You only work in step 1; the next two are a single keypress.

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
3  Furniture  → pick in the palette, click to place  (hold left + drag to move)
```

**3 · Export — one key**
```text
S  →  output/scenes/sceneN.usd     # 3D scene for Isaac Sim
B  →  output/bev/sceneN/           # BEV map for the robot (5 formats)
```

<br>

## ⌨️ Shortcuts

| Key | Action | Key | Action |
|:---:|---|:---:|---|
| `1` `2` `3` | Floor / Wall / Furniture | `Ctrl+Z` `Ctrl+Y` | Undo / Redo |
| `Tab` | Switch tool | `Ctrl`+wheel | Zoom to cursor |
| `R` | Rotate furniture 5° | Middle-drag | Pan the view |
| `W` | Auto boundary walls | `S` / `B` | Export USD / BEV |
| `C` | Clear all | `Ctrl+S` / `L` | Save / Load map |
| `+` `-` | Resize grid | `F11` | Fullscreen |

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
