"""
config.py - Centralized constants for Isaac Scene Builder.

Single source of truth: paths, world constants, asset names, furniture catalog,
BEV parameters, render/capture settings, and UI theme.
"""
import os

# ===========================================================================
# Paths
# ===========================================================================
_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_HERE)
SRC_DIR = _HERE
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
PROP_DIRS = [os.path.join(ASSETS_DIR, "office", "Props"),
             os.path.join(ASSETS_DIR, "extra")]
PROPS_REL = "assets/office/Props"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
SCENES_DIR = os.path.join(OUTPUT_DIR, "scenes")
BEV_DIR = os.path.join(OUTPUT_DIR, "bev")
MESH_DIR = os.path.join(OUTPUT_DIR, "mesh_shapes")
RENDER_DIR = os.path.join(MESH_DIR, "renders")
COLOR_DIR = os.path.join(MESH_DIR, "color")      # colored top-down cut-outs (RGBA)
MAPS_DIR = os.path.join(PROJECT_ROOT, "data", "maps")
SHAPES_JSON = os.path.join(PROJECT_ROOT, "data", "props_shapes.json")
CATALOG_DIR = os.path.join(PROJECT_ROOT, "data", "catalog")
# Curated multi-environment library (tools/asset_library.py)
LIBRARY_DIR = os.path.join(ASSETS_DIR, "library")
ASSET_MANIFEST = os.path.join(PROJECT_ROOT, "data", "asset_manifest.json")
ASSET_OVERRIDES = os.path.join(PROJECT_ROOT, "data", "asset_overrides.json")


def project_path(*parts):
    return os.path.join(PROJECT_ROOT, *parts)


# ===========================================================================
# World / Physics
# ===========================================================================
CELL = 1.0          # size of one grid cell (m): walls / doors / floors sit on a 1 m grid
LEGACY_CELL = 3.0   # cell of maps saved before the 1 m grid (no "cell" key; map_format.py
                    # converts them on load) and the frame of old top-down renders
KIT_M = 3.0         # module length of the Office kit pieces (SM_Wall_3m, SM_Window_3m, tiles)
SNAP = 0.5          # snap step when placing/moving furniture (m)
WALL_H = 3.0

# ===========================================================================
# Structural asset names
# ===========================================================================
FLOOR = "SM_Floor_3m"
CEILING = "SM_Ceiling_3m"
WALL = "SM_Wall_3m"
WALL_DOOR = "SM_Wall_3m_door"
LIGHT_MESH = "SM_CeilingLight"
REQUIRED = [FLOOR, CEILING, WALL, WALL_DOOR, LIGHT_MESH]

# ===========================================================================
# Structure choices (for editor cycling)
# ===========================================================================
STRUCTURE_CHOICES = {
    "wall": ["SM_Wall_3m", "SM_Window_3m_A", "SM_Window_3m_B",
             "SM_Wall_3m_doorElevator"],
    "floor": ["SM_Floor_3m"],
    "ceiling": ["SM_Ceiling_3m"],
    "wall_door": ["SM_Wall_3m_door", "SM_Wall_3m_doorElevator"],
}

# ===========================================================================
# Architecture (src/architecture.py): edge types, wall kit, room styles
# ===========================================================================
# Edge values in map "vedges"/"hedges" (0/1/2 keep their old meaning).
EDGE_NONE, EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING = range(6)
EDGE_NAMES = {EDGE_WALL: "Wall", EDGE_DOOR: "Door", EDGE_WINDOW: "Window",
              EDGE_GLASS: "Glass", EDGE_OPENING: "Opening"}
EDGE_CYCLE = [EDGE_NONE, EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING]

# Office kit modules (measured in Isaac Sim; composed like NVIDIA's office.usd):
# - walls are TWO 3 m panels back to back (x 0.100..0.112 each side) -> 22.4 cm wall,
#   one finished face per room; SM_Wall_end caps free ends / corner posts.
# - doors: SM_Wall_3m_door pair + SM_DoorB frame at mid-edge + SM_DoorB_Door leaf hinged at
#   frame-local (0.128, 0.47), closed = 0 deg, open = DOOR_OPEN_DEG; 0.94 m clear opening.
KIT = {
    "wall": "SM_Wall_3m", "wall_door": "SM_Wall_3m_door", "wall_end": "SM_Wall_end",
    "window": "SM_Window_3m_A", "glass_2m": "SM_Glass_2m", "glass_1m": "SM_Glass_1m",
    "door_frame": "SM_DoorB", "door_leaf": "SM_DoorB_Door", "door_handle": "SM_DoorB_Handle",
}
WALL_HALF = 0.112                        # half wall thickness (outer face of a panel)
DOOR_HINGE = (0.128, 0.47)               # leaf hinge, door-frame local (m)
DOOR_HANDLE = (-0.026, -0.896, 1.017)    # handle, leaf local (m)
DOOR_OPEN_DEG = 100.0
DOOR_DEFAULT = "open"                    # "open" | "closed" (per-door override in the map)

# Room styles: MDL material overrides on the Office geometry (same module sizes, so corners
# and doors always fit). Paths are relative to assets/library/nvidia/ and are downloaded by
# tools/asset_library.py. None = keep the kit's own material.
_HOSP = "Isaac/5.1/Isaac/Environments/Hospital/Materials/"
_WH = "Isaac/5.1/Isaac/Environments/Simple_Warehouse/Materials/"
STYLES = {
    "office": {"label": "Office", "wall": None, "floor": None, "ceiling": None},
    "hospital": {"label": "Hospital", "wall": _HOSP + "M_Wall_PlasterBlue.mdl",
                 "floor": _HOSP + "MI_Hospital_Floor.mdl",
                 "ceiling": _HOSP + "M_CeilingTile2x2.mdl"},
    "warehouse": {"label": "Warehouse", "wall": _WH + "MI_WallA_01.mdl",
                  "floor": _WH + "MI_Floor_01.mdl", "ceiling": _WH + "MI_CeilingA_06b.mdl"},
    "residential": {"label": "Home", "wall": _HOSP + "M_Wall_Cream.mdl",
                    "floor": _HOSP + "M_Wood_Floor.mdl", "ceiling": _HOSP + "M_Wall_Plaster.mdl"},
}
DEFAULT_STYLE = "office"
STYLE_COLORS = {"office": (235, 237, 241), "hospital": (224, 239, 236),
                "warehouse": (240, 231, 215), "residential": (243, 229, 226)}

# ===========================================================================
# Furniture catalog (single source of truth)
# ===========================================================================
FURNITURE = [
    ("SM_SecretaryDeskA", 1.1), ("SM_SecretaryDeskB", 1.1),
    ("SM_InformationDesk_A", 1.2), ("SM_InformationDesk_B", 1.2),
    ("SM_ChairOffice", 0.5), ("SM_ChairOffice_A", 0.5),
    ("SM_Armchair", 0.6), ("SM_Sofa", 1.1), ("SM_Chair", 0.5),
    ("SM_FileCabinet_01", 0.6), ("SM_FileCabinet_02", 0.6),
    ("SM_FileCabinet_03", 0.6),
    ("SM_BookcaseA", 0.7), ("SM_Rack", 0.8), ("SM_RackA", 0.8),
    ("SM_TrashCan", 0.3), ("SM_TrashCan_01", 0.3),
    ("SM_DrinksMachine", 0.7), ("SM_Printer", 0.4),
    ("SM_Plant01", 0.4), ("SM_Plant02", 0.4), ("SM_Plant03", 0.4),
]

FURNITURE_CATEGORIES = {
    "Desks": ["SM_SecretaryDeskA", "SM_SecretaryDeskB",
              "SM_InformationDesk_A", "SM_InformationDesk_B"],
    "Chairs": ["SM_ChairOffice", "SM_ChairOffice_A", "SM_Armchair",
               "SM_Chair", "SM_Sofa"],
    "Cabinets": ["SM_FileCabinet_01", "SM_FileCabinet_02", "SM_FileCabinet_03",
                 "SM_BookcaseA", "SM_Rack", "SM_RackA"],
    "Machines": ["SM_Printer", "SM_DrinksMachine"],
    "Decor": ["SM_Plant01", "SM_Plant02", "SM_Plant03",
              "SM_TrashCan", "SM_TrashCan_01"],
}

# Asset-library category (tools/asset_library.py) -> editor palette tab
LIBRARY_CATEGORY_TABS = {
    "table": "Desks", "seating": "Chairs", "sofa": "Chairs", "storage": "Cabinets",
    "shelving": "Shelving", "appliance": "Machines", "equipment": "Machines",
    "plant": "Decor", "decor": "Decor", "lighting": "Decor", "bed": "Beds",
    "medical": "Medical", "fixture": "Fixtures", "container": "Containers",
    "pallet": "Containers", "cart": "Carts", "safety": "Safety", "misc": "Other",
}

# Extra furniture for shape extraction (from Office pack)
EXTRA_FURNITURE = [
    "SM_TableA", "SM_TableB", "SM_TableC", "SM_TableD", "SM_TableD2",
    "SM_TableCoffee", "SM_TableRound_module", "SM_TableWorkSecurity",
    "SM_TableWorkingDouble", "SM_StandTableWork",
    "SM_ReceptionTableStraight", "SM_ReceptionTableCornerOutside",
    "SM_StandForPapers", "SM_Recliner", "SM_Cupboard", "SM_PaperCase_Case",
    "SM_ReceptionClosets", "SM_Rack1m", "SM_Reception", "SM_ReceptionStandA",
    "SM_ReceptionStandB", "SM_WaterCooler", "SM_Toilet", "SM_ToiletClosed",
    "SM_Urinal", "SM_Washbasin", "SM_Extinguisher", "SM_FireCabinetA",
    "SM_FireCabinetB", "SM_VaseDecorative", "SM_ColumnA", "SM_ColumnD",
    "SM_Elevator",
]

# ===========================================================================
# Light parameters
# ===========================================================================
LIGHT_RADIUS = 0.15
LIGHT_INTENSITY = 30000.0
LIGHT_COLOR = (1.0, 0.93, 0.75)
LIGHT_EXPOSURE = 0.0
LIGHT_CONE_ANGLE = 90.0
LIGHT_CONE_SOFTNESS = 0.5

# ===========================================================================
# BEV (Bird's Eye View) constants
# ===========================================================================
BEV_SCALE = 40
WALL_M = 0.2
DOOR_GAP = (0.5 - 0.47 / CELL, 0.5 + 0.47 / CELL)   # 0.94 m clear opening, edge fractions
UNKNOWN = 205
FREE = 254
OCC = 0

# ===========================================================================
# Render / Capture constants
# ===========================================================================
RESOLUTION = 1024
APERTURE_SCALE = 10.0
CHUNK_SIZE = 40
GROUND_SIZE = 40.0      # white ground plane (m); must exceed the largest capture frame
CAM_HEIGHT = 6.0
# Capture frame (m, square, centered on the prop origin): the smallest step that
# contains the prop footprint is used, so large props (conference tables, racks,
# reception counters) are not clipped. Each render gets a <asset>.json sidecar
# {"frame_m": ...}; meters/pixel = frame_m / image width.
FRAME_STEPS = (3.0, 4.5, 6.0, 9.0, 12.0, 18.0)
# Height-sliced occupancy (tools/slice_footprints.py): what a robot of this body height
# actually hits - a low robot drives under table tops, glass-top tables block at the legs.
SLICE_Z = (0.05, 0.50)  # m above the floor (default slab; others via --z)
SLICE_MPP = 0.01        # m / pixel of slice masks


def slice_dir(z=SLICE_Z):
    return os.path.join(MESH_DIR, "slice_%.2f-%.2f" % (float(z[0]), float(z[1])))
FRAME_MARGIN = 0.15     # m kept free around the footprint
SETTLE_FRAMES = 16
SHOW_FRAMES = 6
VERTICAL_FLIP = True

# ===========================================================================
# Shape detection thresholds
# ===========================================================================
WHITE_TOL = 18
SAT_TOL = 18

# ===========================================================================
# UI Theme - "Ivory & Ink": light, minimal, quietly luxurious
#   warm ivory canvas, white cards, ink text, one champagne-gold accent.
# ===========================================================================
# Neutral ramp (kept as C0..C4 for older code): ink -> white
C0 = (28, 31, 36)       # ink (strongest text / active fills)
C1 = (58, 62, 70)       # graphite
C2 = (128, 122, 112)    # warm grey (secondary text)
C3 = (40, 43, 48)       # body text
C4 = (255, 255, 255)    # white
MESH_MARK = (178, 58, 58)

BG = (243, 240, 233)            # ivory canvas around the plan
PLAN_BG = (252, 251, 248)       # the plan sheet (grid area)
PANEL_BG = (255, 255, 255)      # side panel / cards
GRID_LINE = (228, 222, 210)     # hairline grid
SECTION_LINE = (238, 233, 224)  # dividers
BORDER = (226, 220, 208)        # control outlines
SHADOW_ALPHA = 22               # soft card shadow (0-255)

# Buttons
BTN = (255, 255, 255)           # resting (outlined)
BTN_HOVER = (246, 242, 234)     # hover
BTN_ACTIVE = C0                 # active tool / selected option: ink fill
ON_ACTIVE = (250, 247, 240)     # text on ink

# Text
TEXT = C3
TEXT_DIM = C2

# Accent - champagne gold (selection, focus, highlights)
ACCENT = (166, 129, 74)
ACCENT_DIM = (244, 236, 220)    # gold tint (selected rows, active field)

# Floor / wall / light / door
FLOOR_COL = (235, 237, 241)     # default (office) floor
FLOOR_HOVER = (196, 184, 160)
WALL_COL = (44, 47, 54)         # ink walls
DOOR_COL = (63, 130, 98)        # muted green
WINDOW_COL = (96, 146, 190)     # steel blue
GLASS_COL = (112, 176, 198)
ROBOT_COL = (184, 92, 112)      # muted rose (waypoints / route)
SPAWN_COL = (63, 130, 98)       # robot spawn
LIGHT_COL = (196, 160, 98)      # champagne
HOVER_EDGE = ACCENT

# Furniture / selection
FURNI_COL = (122, 134, 152)     # slate
FURNI_SEL = ACCENT

# Panel details
PANEL_ROW_ALT = (250, 248, 244) # zebra row
FIELD_BG = (255, 255, 255)
FIELD_ACTIVE_BG = (253, 250, 243)
DANGER = (178, 58, 58)
