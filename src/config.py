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
MAPS_DIR = os.path.join(PROJECT_ROOT, "data", "maps")
SHAPES_JSON = os.path.join(PROJECT_ROOT, "data", "props_shapes.json")
CATALOG_DIR = os.path.join(PROJECT_ROOT, "data", "catalog")


def project_path(*parts):
    return os.path.join(PROJECT_ROOT, *parts)


# ===========================================================================
# World / Physics
# ===========================================================================
CELL = 3.0          # size of one grid cell (m)
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
DOOR_GAP = (0.35, 0.65)
UNKNOWN = 205
FREE = 254
OCC = 0

# ===========================================================================
# Render / Capture constants
# ===========================================================================
RESOLUTION = 1024
APERTURE_SCALE = 10.0
CHUNK_SIZE = 40
GROUND_SIZE = 12.0
CAM_HEIGHT = 6.0
SETTLE_FRAMES = 16
SHOW_FRAMES = 6
VERTICAL_FLIP = True

# ===========================================================================
# Shape detection thresholds
# ===========================================================================
WHITE_TOL = 18
SAT_TOL = 18

# ===========================================================================
# UI Theme - "Slate + Indigo" modern dark (Tailwind / Linear inspired)
# ===========================================================================
# Neutral ramp (dark -> light): canvas bg, panel, dim text, text, bright text
C0 = (15, 23, 42)       # slate-900
C1 = (30, 41, 59)       # slate-800
C2 = (148, 163, 184)    # slate-400  (dim text)
C3 = (226, 232, 240)    # slate-200  (text)
C4 = (248, 250, 252)    # slate-50   (bright text)
MESH_MARK = (244, 63, 94)   # rose-500

BG = C0
PANEL_BG = (20, 27, 45)         # slate-850 (panel, subtly above canvas)
GRID_LINE = (36, 47, 68)        # faint grid lines
SECTION_LINE = (44, 56, 78)     # slate-700 dividers

# Buttons
BTN = (42, 54, 78)              # resting
BTN_HOVER = (60, 74, 104)       # hover
BTN_ACTIVE = (99, 102, 241)     # indigo-500 (active tool / primary)

# Text
TEXT = C3
TEXT_DIM = C2

# Floor / wall / light / door
FLOOR_COL = (37, 51, 82)        # indigo-tinted slate fill
FLOOR_HOVER = (60, 80, 124)
WALL_COL = (203, 213, 225)      # slate-300 (crisp walls)
DOOR_COL = (52, 211, 153)       # emerald-400
LIGHT_COL = (251, 191, 36)      # amber-400
HOVER_EDGE = (129, 140, 248)    # indigo-400

# Furniture / selection accent
FURNI_COL = (96, 165, 250)      # blue-400
FURNI_SEL = (251, 191, 36)      # amber-400 (selected pops)
ACCENT = (167, 139, 250)        # violet-400 (rings, headers, active field)
ACCENT_DIM = (76, 66, 140)      # dim violet

# Panel details
PANEL_ROW_ALT = (28, 37, 60)    # zebra row
FIELD_BG = C0
FIELD_ACTIVE_BG = (23, 31, 49)
DANGER = (244, 63, 94)          # rose-500
