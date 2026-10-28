"""
map_generator.py - Procedural indoor maps (pure Python, deterministic per seed).

    generate_map(seed, theme="office"|"hospital"|"warehouse"|"residential",
                 size=(nx, ny), density=0.2) -> map_data (scene_editor / scene_builder format)

Pipeline
  1. Layout on the 3 m grid: corridor + rooms (office / hospital), BSP rooms with an
     optional missing corner (residential), hall + office strip (warehouse).
  2. Edges: walls between rooms and outside, doors along a spanning tree of the room
     graph (+ a few extra links), one entrance, windows on outer walls, glass fronts.
  3. Room styles + ceiling lights.
  4. Furniture per room type from recipes (against walls, grouped: desk + chair,
     bed + nightstand, table + chairs, rack rows with aisles), collision-checked with the
     measured footprints (props_shapes.json) and kept out of door clearances. Every item
     must keep all doors reachable for a robot (flood fill on the inflated free space).
  5. Robot spawn at the entrance + one waypoint per room (greedy tour).
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from config import (CELL, EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS, EDGE_OPENING,
                    FURNITURE, EXTRA_FURNITURE)
from utils import load_library, load_prop_shapes, bbox_corners
import architecture as arch

RES = 0.1               # m / px of the planning grid
ROBOT_R = 0.28          # robot radius kept free around obstacles (m)
WALL_CLEAR = 0.25       # gap between furniture and the wall line (m)
DOOR_CLEAR = (1.2, 1.2)  # free box at each door: along the edge, into each side (m)
MIN_REACH = 0.9         # an item may not cut off more than 10 % of the robot-free space
THEMES = ("office", "hospital", "warehouse", "residential")

# ----------------------------------------------------------------------------
# Asset roles (exact names or name prefixes; missing ones are skipped)
# ----------------------------------------------------------------------------
ROLES = {
    # office
    "desk": ["SM_SecretaryDeskA", "SM_SecretaryDeskB", "SM_TableC", "SM_TableD2",
             "SM_TableWorkSecurity"],
    "office_chair": ["SM_ChairOffice", "SM_ChairOffice_A", "AV_Elliot", "AV_Reidmeyer",
                     "AV_Soba"],
    "meeting_table": ["AV_Boat", "AV_Cline", "AV_Gilbert", "AV_Modern", "AV_OakTableLarge",
                      "SM_TableA", "AV_Steam", "SM_TableRound_module", "AV_Hexagon"],
    "meeting_chair": ["SM_Chair", "AV_Stackable", "AV_Basic", "AV_Monarch", "AV_Caprice_A"],
    "cabinet": ["SM_FileCabinet_01", "SM_FileCabinet_02", "SM_FileCabinet_03", "SM_BookcaseA",
                "AV_Contemporary_LaterialFile", "AV_Contemporary_LockedStorage",
                "AV_Contemporary_OpenStorage", "AV_Standard_SmallUnit",
                "AV_Contemporary_Hutch", "SM_Cupboard"],
    "plant": ["SM_Plant01", "SM_Plant02", "SM_Plant03", "AV_Anza_Tall", "AV_Plant_02",
              "AV_PlantPot", "AV_Anza_Medium"],
    "lounge_sofa": ["SM_Sofa", "AV_Jobba_Sofa", "AV_Petite_Loveseat"],
    "lounge_chair": ["SM_Armchair", "AV_Petite_Chair", "AV_Rave", "AV_Anora"],
    "coffee_table": ["SM_TableCoffee", "AV_Midtown", "AV_Willow", "PH_CoffeeTable_01"],
    "office_appliance": ["SM_DrinksMachine", "SM_Printer", "SM_WaterCooler"],
    "bin": ["SM_TrashCan", "SM_TrashCan_01", "DT_OfficeTrashCan", "DT_DomedWasteTrashCan"],
    "reception": ["SM_ReceptionTableStraight", "AV_Curved_Full"],
    # hospital
    "hospital_bed": ["HOS_SM_HospitalBed_01b", "HOS_SM_HospitalBed_02d"],
    "bedside": ["HOS_SM_BedSideTable_01b"],
    "visitor_chair": ["HOS_SM_Chair_01a", "HOS_SM_Chair_04a"],
    "waiting_bench": ["HOS_SM_Chair_02a"],
    "med_cabinet": ["HOS_SM_MedicalCabinet_01a", "HOS_SM_MedShelf_01d",
                    "HOS_SM_SupplyCabinet_01c", "HOS_SM_ShelfSet_01a", "HOS_SM_Shelf_06f"],
    "med_cart": ["HOS_SM_SupplyCart_01e", "HOS_SM_SupplyCart_02a", "HOS_SM_SupplyCart_03a",
                 "HOS_SM_Cart_01a"],
    "gurney": ["HOS_SM_Gurney_01a"],
    "wheelchair": ["HOS_SM_WheelChair_01a"],
    "med_equipment": ["HOS_SM_Scale_01a", "HOS_SM_DisposalStand_02", "HOS_SM_Chart_Rack_01c"],
    "hospital_appliance": ["HOS_SM_DrinksMachine", "HOS_SM_WaterDispenser_01a"],
    # warehouse
    "rack": ["AV_RackLarge_A7", "AV_RackLong_A3", "AV_RackLongEmpty_A1", "AV_RackSmall_A1",
             "DT_HeavyDutySteelShelving", "DT_IndustrialSteelShelving",
             "DT_OpenIndustrialSteelShelving", "DT_BulkStorageRack"],
    "pallet": ["AV_Pallet_A1", "DT_BlockPallet", "WH_SM_PaletteA", "DT_WoodDrumPallet"],
    "crate": ["AV_WoodenCrate_A2", "DT_HeavyDutyWoodCrate", "AV_Cardbox_C1",
              "DT_Container_D08", "DT_Tote", "WH_SM_BarelPlastic", "WH_SM_CratePlastic"],
    "cart": ["DT_MobileShelvingCart", "DT_ServingTrolley", "DT_TableTrolley",
             "DT_StandardAluminumHandTruck", "DT_ConvertibleSteelHandTruck", "WH_SM_PushcartA",
             "DT_WorkShopTrolley", "DT_TradeMasterCart"],
    "workbench": ["DT_HeavyDutyPackingTable", "DT_IndustrialPackingTable", "DT_LabWorkbench",
                  "DT_PedestalWorkbench", "DT_DeluxePackingTable", "DT_TableMetal"],
    "stool": ["DT_ShopStool", "DT_SwivelShopStool", "DT_IndustrialMetalStool"],
    "safety": ["DT_TrafficCone", "DT_HeavyDutyTrafficCone", "DT_WetFloorSign", "WH_S_TrafficCone",
               "DT_WarningSign"],
    # residential
    "sofa": ["AV_Arnold", "AV_Maplewood_Sofa", "AV_Moline", "AV_Crestwood_Loveseat",
             "AV_Appleseed_Loveseat", "PH_Sofa_01", "PH_chinese_sofa"],
    "armchair": ["AV_Armchair", "PH_ArmChair_01", "PH_GreenChair_01", "PH_Rockingchair_01"],
    "home_coffee_table": ["AV_Midtown", "AV_Ellendale", "AV_Festus01", "PH_CoffeeTable_01",
                          "PH_chinese_tea_table"],
    "media": ["AV_Huntliegh", "PH_ClassicConsole_01", "AV_Manchester"],
    "bookshelf": ["AV_Fenton", "AV_Ladue", "PH_wooden_bookshelf_worn", "PH_steel_frame_shelves_01",
                  "AV_Costello", "PH_painted_wooden_shelves"],
    "bed": ["PH_GothicBed_01", "AV_Daybed"],
    "nightstand": ["PH_ClassicNightstand_01", "AV_Ellendale", "AV_Festus01"],
    "wardrobe": ["PH_GothicCabinet_01", "PH_chinese_cabinet", "PH_drawer_cabinet",
                 "PH_painted_wooden_cabinet", "PH_vintage_cabinet_01"],
    "dining_table": ["AV_EastRural_Table", "PH_WoodenTable_01", "AV_Whittershins"],
    "dining_chair": ["AV_Jennings_Chair", "AV_DesPeres_Chair", "AV_Sedie_Chair",
                     "PH_WoodenChair_01", "AV_Chair_Wire"],
    "kitchen": ["AV_fridge", "AV_stove", "AV_dishwasher_A"],
    "home_desk": ["AV_Desk_01", "PH_SchoolDesk_01"],
    "desk_chair": ["AV_Chair_Desk", "PH_SchoolChair_01"],
    "home_plant": ["AV_Anza_Large", "AV_Anza_Medium", "AV_PlantPot", "AV_Plant_02",
                   "AV_SquareGardenPlanter_Large"],
    "lamp": ["AV_FloorLamp", "AV_VintageFloorLamp", "AV_BrassFloorLamp"],
}

# step = (role, how, (min, max), {options}); "follow" steps place relative to the anchor
R = {
    # ---- office
    "open_office": [("desk", "wall", (2, 6), {"follow": [("office_chair", "front", (1, 1))]}),
                    ("cabinet", "wall", (1, 3), {}), ("plant", "corner", (1, 2), {}),
                    ("bin", "wall", (0, 1), {})],
    "meeting": [("meeting_table", "center", (1, 1), {"follow": [("meeting_chair", "around", (4, 8))]}),
                ("plant", "corner", (0, 1), {}), ("cabinet", "wall", (0, 1), {})],
    "private_office": [("desk", "wall", (1, 1), {"follow": [("office_chair", "front", (1, 1))]}),
                       ("cabinet", "wall", (1, 2), {}), ("lounge_chair", "wall", (0, 1), {}),
                       ("plant", "corner", (0, 1), {})],
    "lounge": [("lounge_sofa", "wall", (1, 1), {"follow": [("coffee_table", "front", (1, 1))]}),
               ("lounge_chair", "wall", (1, 2), {}), ("office_appliance", "wall", (1, 2), {}),
               ("plant", "corner", (1, 2), {})],
    "office_corridor": [("plant", "corner", (0, 2), {}), ("bin", "wall", (0, 1), {}),
                        ("office_appliance", "wall", (0, 1), {})],
    # ---- hospital
    "ward": [("hospital_bed", "wall", (1, 2), {"follow": [("bedside", "beside", (1, 1)),
                                                           ("visitor_chair", "beside", (0, 1))]}),
             ("med_cart", "wall", (0, 1), {}), ("med_cabinet", "wall", (0, 1), {})],
    "exam": [("gurney", "center", (1, 1), {}), ("med_cabinet", "wall", (1, 2), {}),
             ("med_equipment", "wall", (1, 2), {}),
             ("desk", "wall", (0, 1), {"follow": [("office_chair", "front", (1, 1))]})],
    "waiting": [("waiting_bench", "wall", (1, 3), {}), ("hospital_appliance", "wall", (1, 2), {}),
                ("plant", "corner", (0, 2), {})],
    "supply": [("med_cabinet", "wall", (2, 5), {}), ("med_cart", "free", (1, 2), {})],
    "hospital_corridor": [("wheelchair", "wall", (0, 1), {}), ("med_cart", "wall", (0, 1), {}),
                          ("gurney", "wall", (0, 1), {}), ("hospital_appliance", "wall", (0, 1), {})],
    # ---- warehouse
    "hall": [("rack", "rows", (1, 1), {}), ("pallet", "free", (2, 8), {}),
             ("crate", "free", (3, 12), {}), ("cart", "free", (1, 4), {}),
             ("workbench", "wall", (0, 2), {"follow": [("stool", "front", (0, 1))]}),
             ("safety", "free", (0, 3), {})],
    "wh_office": [("workbench", "wall", (1, 1), {"follow": [("stool", "front", (1, 1))]}),
                  ("cabinet", "wall", (1, 2), {}), ("crate", "free", (0, 2), {})],
    # ---- residential
    "living": [("sofa", "wall", (1, 1), {"follow": [("home_coffee_table", "front", (1, 1))]}),
               ("armchair", "free", (0, 2), {}), ("media", "wall", (0, 1), {}),
               ("bookshelf", "wall", (0, 1), {}), ("home_plant", "corner", (1, 2), {}),
               ("lamp", "corner", (0, 1), {})],
    "bedroom": [("bed", "wall", (1, 1), {"follow": [("nightstand", "beside", (1, 2))]}),
                ("wardrobe", "wall", (1, 1), {}), ("home_plant", "corner", (0, 1), {}),
                ("lamp", "corner", (0, 1), {})],
    "kitchen": [("kitchen", "wall", (2, 3), {}),
                ("dining_table", "center", (1, 1), {"follow": [("dining_chair", "around", (2, 6))]})],
    "study": [("home_desk", "wall", (1, 1), {"follow": [("desk_chair", "front", (1, 1))]}),
              ("bookshelf", "wall", (1, 2), {}), ("armchair", "free", (0, 1), {})],
    "hallway": [("home_plant", "corner", (0, 1), {}), ("media", "wall", (0, 1), {})],
}
# extra items to reach the density target after the recipe: (role, how)
# extra groups to reach the density target after the recipe: (role, how, follow-steps)
# - meaningful clusters rather than loose chairs
_DESK = [("office_chair", "front", (1, 1))]
FILL = {
    "open_office": [("desk", "wall", _DESK), ("desk", "wall", _DESK), ("cabinet", "wall", []),
                    ("plant", "corner", []), ("office_appliance", "wall", [])],
    "meeting": [("cabinet", "wall", []), ("plant", "corner", [])],
    "private_office": [("cabinet", "wall", []), ("plant", "corner", []),
                       ("lounge_chair", "wall", [])],
    "lounge": [("lounge_sofa", "wall", [("coffee_table", "front", (1, 1))]),
               ("plant", "corner", []), ("lounge_chair", "wall", [])],
    "ward": [("hospital_bed", "wall", [("bedside", "beside", (1, 1))]),
             ("hospital_bed", "wall", [("bedside", "beside", (1, 1))]),
             ("med_cabinet", "wall", []), ("med_cart", "wall", [])],
    "exam": [("med_equipment", "wall", []), ("med_cabinet", "wall", []),
             ("med_cart", "wall", [])],
    "waiting": [("waiting_bench", "wall", []), ("plant", "corner", []),
                ("hospital_appliance", "wall", [])],
    "supply": [("med_cabinet", "wall", []), ("med_cart", "wall", [])],
    "hall": [("crate", "free", []), ("pallet", "free", []), ("cart", "free", []),
             ("workbench", "wall", [("stool", "front", (1, 1))])],
    "wh_office": [("cabinet", "wall", []), ("crate", "wall", [])],
    "living": [("armchair", "wall", []), ("home_plant", "corner", []), ("lamp", "corner", []),
               ("bookshelf", "wall", [])],
    "bedroom": [("wardrobe", "wall", []), ("home_plant", "corner", []), ("bookshelf", "wall", [])],
    "kitchen": [("kitchen", "wall", []), ("home_plant", "corner", [])],
    "study": [("bookshelf", "wall", []), ("home_plant", "corner", []), ("armchair", "wall", [])],
}
STYLE_OF = {"office": "office", "hospital": "hospital", "warehouse": "warehouse",
            "residential": "residential"}


# ----------------------------------------------------------------------------
# Assets
# ----------------------------------------------------------------------------
class Assets:
    def __init__(self):
        lib = load_library()
        shapes = load_prop_shapes()
        names = set(lib) | {n for n, _ in FURNITURE} | set(EXTRA_FURNITURE)
        import scene_builder as sb
        self.dims = {}
        for n in names:
            s = shapes.get(n)
            if s and sb.asset_exists(n) and s.get("w", 0) > 0.05 and s.get("h", 0) > 0.05:
                self.dims[n] = (float(s["w"]), float(s["h"]), bool(s.get("mesh")))
        self.roles = {}
        for role, pats in ROLES.items():
            hits = []
            for p in pats:
                hits += sorted(n for n in self.dims if n == p or n.startswith(p + "_"))
            self.roles[role] = list(dict.fromkeys(hits))

    def pick(self, rng, role):
        c = self.roles.get(role) or []
        return rng.choice(c) if c else None


# ----------------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------------
class Room:
    def __init__(self, name, rect, rtype):
        self.name, self.rect, self.type = name, rect, rtype     # rect = (i0, j0, i1, j1) incl.

    def cells(self):
        i0, j0, i1, j1 = self.rect
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def bounds(self, inset=0.0):
        i0, j0, i1, j1 = self.rect
        return (i0 * CELL + inset, j0 * CELL + inset, (i1 + 1) * CELL - inset, (j1 + 1) * CELL - inset)

    def area_cells(self):
        i0, j0, i1, j1 = self.rect
        return (i1 - i0 + 1) * (j1 - j0 + 1)


def _split(n, rng, lo=2, hi=4):
    """Split length n into parts in [lo, hi] (last part absorbs the remainder)."""
    out, left = [], n
    while left > hi:
        w = rng.randint(lo, min(hi, left - lo))
        out.append(w)
        left -= w
    out.append(left)
    return out


def layout_corridor(nx, ny, rng, types):
    """Rooms on both sides of a 1-cell corridor along X (types = room type list to cycle)."""
    cj = rng.randint(2, ny - 3)
    rooms = [Room("corridor", (0, cj, nx - 1, cj), types[0])]
    for (j0, j1) in ((0, cj - 1), (cj + 1, ny - 1)):
        i = 0
        for w in _split(nx, rng):
            rooms.append(Room("room%d" % len(rooms), (i, j0, i + w - 1, j1),
                              rng.choice(types[1:])))
            i += w
    return rooms


def layout_bsp(nx, ny, rng, types, max_cells=9):
    rects = [(0, 0, nx - 1, ny - 1)]
    out = []
    while rects:
        r = rects.pop()
        i0, j0, i1, j1 = r
        w, h = i1 - i0 + 1, j1 - j0 + 1
        if w * h <= max_cells or (w < 4 and h < 4):
            out.append(r)
            continue
        if w >= h and w >= 4:
            s = rng.randint(i0 + 2, i1 - 1)
            rects += [(i0, j0, s - 1, j1), (s, j0, i1, j1)]
        elif h >= 4:
            s = rng.randint(j0 + 2, j1 - 1)
            rects += [(i0, j0, i1, s - 1), (i0, s, i1, j1)]
        else:
            out.append(r)
    rooms = [Room("room%d" % k, r, None) for k, r in enumerate(out)]
    rooms.sort(key=lambda rm: -rm.area_cells())
    rooms[0].type = types[0]                         # biggest room = living / main
    rest = list(types[1:])
    for k, rm in enumerate(rooms[1:]):
        rm.type = rest[k % len(rest)] if k < len(rest) else rng.choice(rest)
    return rooms


def layout_hall(nx, ny, rng):
    depth = 2
    side_bottom = rng.random() < 0.5
    hj = (depth, ny - 1) if side_bottom else (0, ny - 1 - depth)
    rooms = [Room("hall", (0, hj[0], nx - 1, hj[1]), "hall")]
    oj = (0, depth - 1) if side_bottom else (ny - depth, ny - 1)
    i = 0
    for w in _split(nx, rng, 2, 3):
        rooms.append(Room("office%d" % len(rooms), (i, oj[0], i + w - 1, oj[1]), "wh_office"))
        i += w
    return rooms


def room_graph(rooms):
    """{(a, b): [shared edges as (kind, i, j)]} for rooms sharing a boundary."""
    owner = {}
    for k, rm in enumerate(rooms):
        for c in rm.cells():
            owner[c] = k
    shared = {}
    for (i, j), a in owner.items():
        for kind, nb, e in (("v", (i + 1, j), (i + 1, j)), ("h", (i, j + 1), (i, j + 1))):
            b = owner.get(nb)
            if b is not None and b != a:
                shared.setdefault(tuple(sorted((a, b))), []).append((kind,) + e)
    return owner, shared


def _mid(lst):
    return lst[len(lst) // 2]


def build_edges(rooms, theme, rng):
    owner, shared = room_graph(rooms)
    edges = {}                                       # (kind, i, j) -> type
    # all boundaries: walls (outside + between rooms)
    for (i, j), a in owner.items():
        for kind, nb, e in (("v", (i - 1, j), (i, j)), ("v", (i + 1, j), (i + 1, j)),
                            ("h", (i, j - 1), (i, j)), ("h", (i, j + 1), (i, j + 1))):
            if owner.get(nb) != a:
                edges[(kind,) + e] = EDGE_WALL
    # connections: spanning tree over the room graph (+ extras)
    pairs = list(shared)
    rng.shuffle(pairs)
    hub = [k for k, rm in enumerate(rooms) if rm.name in ("corridor", "hall")]
    if hub:                                          # every room to the corridor / hall first
        pairs.sort(key=lambda p: 0 if (p[0] in hub or p[1] in hub) else 1)
    parent = list(range(len(rooms)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    links = []
    for p in pairs:
        a, b = find(p[0]), find(p[1])
        if a != b:
            parent[a] = b
            links.append(p)
        elif rng.random() < 0.15:
            links.append(p)
    for p in links:
        e = _mid(sorted(shared[p]))
        both = {rooms[p[0]].type, rooms[p[1]].type}
        open_plan = theme == "residential" and both & {"living", "kitchen"} == {"living", "kitchen"}
        edges[e] = EDGE_OPENING if open_plan and rng.random() < 0.6 else EDGE_DOOR
    # glass fronts: meeting rooms / lounges facing the corridor
    for p, es in shared.items():
        types = {rooms[p[0]].type, rooms[p[1]].type}
        if "office_corridor" in types and types & {"meeting", "lounge"} and rng.random() < 0.6:
            for e in es:
                if edges.get(e) == EDGE_WALL:
                    edges[e] = EDGE_GLASS
    # entrance: an outer edge of the hub / main room
    main = hub[0] if hub else 0
    outer = [e for e, t in edges.items() if t == EDGE_WALL and _is_outer(e, owner)
             and main in _sides(e, owner)]
    entrance = rng.choice(sorted(outer)) if outer else None
    if entrance:
        edges[entrance] = EDGE_DOOR
    # windows on outer walls of rooms (not corridors / storage)
    p_win = {"office": 0.45, "hospital": 0.35, "residential": 0.4, "warehouse": 0.08}[theme]
    for e, t in sorted(edges.items()):
        if t != EDGE_WALL or not _is_outer(e, owner) or e == entrance:
            continue
        rm = rooms[_sides(e, owner)[0]]
        if rm.type in ("office_corridor", "hospital_corridor", "supply") and theme != "warehouse":
            continue
        if rng.random() < p_win:
            edges[e] = EDGE_WINDOW
    return edges, entrance, owner


def _sides(e, owner):
    kind, i, j = e
    cells = [(i - 1, j), (i, j)] if kind == "v" else [(i, j - 1), (i, j)]
    return [owner[c] for c in cells if c in owner]


def _is_outer(e, owner):
    return len(_sides(e, owner)) == 1


# ----------------------------------------------------------------------------
# Planning grid (walls, furniture, reachability)
# ----------------------------------------------------------------------------
class Grid:
    def __init__(self, map_data, nx, ny):
        self.W, self.H = int(round(nx * CELL / RES)), int(round(ny * CELL / RES))
        floor = Image.new("L", (self.W, self.H), 0)
        d = ImageDraw.Draw(floor)
        for key, s in map_data["cells"].items():
            i, j = map(int, key.split(","))
            d.rectangle([i * CELL / RES, j * CELL / RES, (i + 1) * CELL / RES - 1,
                         (j + 1) * CELL / RES - 1], fill=255)
        self.free = np.asarray(floor) > 0                         # floor
        walls = Image.new("L", (self.W, self.H), 0)
        d = ImageDraw.Draw(walls)
        import bev_export as bev
        _, _, rows = bev.scene_rows(map_data)
        for r in rows:
            if r["kind"] in bev.EDGE_KINDS + ("door_leaf",):
                for (ax, ay), (bx, by) in bev._edge_segments(r):
                    d.line([ax / RES, ay / RES, bx / RES, by / RES], fill=255,
                           width=max(1, int(round(0.25 / RES))))
        self.walls = np.asarray(walls) > 0
        self.furn = np.zeros_like(self.free)
        self.block = np.zeros_like(self.free)                     # door clearances etc.
        self.keypoints = []

    def px(self, x, y):
        return int(x / RES), int(y / RES)

    def poly_mask(self, pts, grow=0.0):
        """Boolean mask of a polygon (meters), optionally grown by `grow` m."""
        img = Image.new("L", (self.W, self.H), 0)
        ImageDraw.Draw(img).polygon([(x / RES, y / RES) for x, y in pts], fill=255)
        if grow > 0:
            k = 2 * int(math.ceil(grow / RES)) + 1
            img = img.filter(ImageFilter.MaxFilter(k))
        return np.asarray(img) > 0

    def fits(self, mask, inside):
        return mask.any() and not (mask & (self.walls | self.furn | self.block | ~inside)).any()

    def reachable(self, extra=None):
        """Flood fill from the first keypoint over the robot-inflated free space;
        True if every keypoint is reached."""
        if not self.keypoints:
            return True
        furn = self.furn if extra is None else (self.furn | extra)
        # furniture grows one extra pixel: rounding coordinates in the saved map must not
        # be able to close a passage the planner just accepted (walls/doors are exact)
        furn = np.asarray(Image.fromarray(np.where(furn, 255, 0).astype("uint8"))
                          .filter(ImageFilter.MaxFilter(3))) > 0
        occ = ~self.free | self.walls | furn
        img = Image.fromarray(np.where(occ, 255, 0).astype("uint8"))
        k = 2 * int(math.ceil(ROBOT_R / RES)) + 1
        img = img.filter(ImageFilter.MaxFilter(k))
        free = Image.fromarray(np.where(np.asarray(img) > 0, 0, 255).astype("uint8")).copy()
        sx, sy = self.px(*self.keypoints[0])
        if free.getpixel((sx, sy)) != 255:
            return False
        ImageDraw.floodfill(free, (sx, sy), 128)
        if not all(free.getpixel(self.px(x, y)) == 128 for x, y in self.keypoints[1:]):
            return False
        a = np.asarray(free)
        return (a == 128).sum() >= MIN_REACH * max(1, int((a > 0).sum()))

    def reach_mask(self):
        occ = ~self.free | self.walls | self.furn
        img = Image.fromarray(np.where(occ, 255, 0).astype("uint8"))
        img = img.filter(ImageFilter.MaxFilter(2 * int(math.ceil(ROBOT_R / RES)) + 1))
        free = Image.fromarray(np.where(np.asarray(img) > 0, 0, 255).astype("uint8")).copy()
        if self.keypoints:
            ImageDraw.floodfill(free, self.px(*self.keypoints[0]), 128)
        return np.asarray(free) == 128, np.asarray(free) > 0


def door_frames(edges):
    """[(edge, midpoint, normal)] for doors / openings (normal points to +X / +Y side)."""
    out = []
    for e, t in edges.items():
        if t not in (EDGE_DOOR, EDGE_OPENING):
            continue
        kind, i, j = e
        if kind == "v":
            out.append((e, (i * CELL, (j + 0.5) * CELL), (1.0, 0.0)))
        else:
            out.append((e, ((i + 0.5) * CELL, j * CELL), (0.0, 1.0)))
    return out


# ----------------------------------------------------------------------------
# Furniture placement
# ----------------------------------------------------------------------------
def _extent(w, h, yaw):
    return (w, h) if int(round(yaw)) % 180 == 0 else (h, w)


class Furnisher:
    def __init__(self, grid, assets, rng):
        self.g, self.a, self.rng = grid, assets, rng
        self.items = []

    def _try(self, name, x, y, yaw, inside, pad=0.0):
        w, h, has_mesh = self.a.dims[name]
        pts = bbox_corners(x, y, w, h, yaw)
        m = self.g.poly_mask(pts, grow=pad)
        if not self.g.fits(m, inside):
            return None
        if not self.g.reachable(extra=m):
            return None
        self.g.furn |= m
        it = {"asset": name, "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw % 360, 1),
              "shape": "mesh" if has_mesh else "bbox", "w": w, "h": h,
              "r": round(0.5 * math.hypot(w, h), 3)}
        self.items.append(it)
        return it

    def wall(self, room, name, inside, tries=24):
        w, h, _ = self.a.dims[name]
        x0, y0, x1, y1 = room.bounds(WALL_CLEAR)
        sides = ["S", "N", "W", "E"]
        for _ in range(tries):
            side = self.rng.choice(sides)
            long_x = side in ("S", "N")
            yaw = (0 if (w >= h) == long_x else 90) + self.rng.choice((0, 180))
            ex, ey = _extent(w, h, yaw)
            if ex > x1 - x0 or ey > y1 - y0:
                continue
            if long_x:
                x = self.rng.uniform(x0 + ex / 2, x1 - ex / 2)
                y = y0 + ey / 2 if side == "S" else y1 - ey / 2
                f = (0.0, 1.0) if side == "S" else (0.0, -1.0)
            else:
                y = self.rng.uniform(y0 + ey / 2, y1 - ey / 2)
                x = x0 + ex / 2 if side == "W" else x1 - ex / 2
                f = (1.0, 0.0) if side == "W" else (-1.0, 0.0)
            it = self._try(name, x, y, yaw, inside)
            if it:
                it["_face"], it["_ext"] = f, (ex, ey)
                return it
        return None

    def corner(self, room, name, inside):
        w, h, _ = self.a.dims[name]
        x0, y0, x1, y1 = room.bounds(WALL_CLEAR)
        cs = [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]
        self.rng.shuffle(cs)
        for cx, cy, sx, sy in cs:
            yaw = self.rng.choice((0, 90, 180, 270))
            ex, ey = _extent(w, h, yaw)
            it = self._try(name, cx + sx * ex / 2, cy + sy * ey / 2, yaw, inside)
            if it:
                return it
        return None

    def center(self, room, name, inside, tries=12):
        w, h, _ = self.a.dims[name]
        x0, y0, x1, y1 = room.bounds(WALL_CLEAR)
        long_x = (x1 - x0) >= (y1 - y0)
        for _ in range(tries):
            yaw = (0 if (w >= h) == long_x else 90) + self.rng.choice((0, 180))
            jx, jy = self.rng.uniform(-0.6, 0.6), self.rng.uniform(-0.6, 0.6)
            it = self._try(name, (x0 + x1) / 2 + jx, (y0 + y1) / 2 + jy, yaw, inside)
            if it:
                ex, ey = _extent(w, h, yaw)
                it["_face"], it["_ext"] = ((0.0, 1.0) if long_x else (1.0, 0.0)), (ex, ey)
                return it
        return None

    def free(self, room, name, inside, tries=20, jitter=15.0):
        w, h, _ = self.a.dims[name]
        x0, y0, x1, y1 = room.bounds(WALL_CLEAR)
        for _ in range(tries):
            yaw = self.rng.choice((0, 90, 180, 270)) + self.rng.uniform(-jitter, jitter)
            r = 0.5 * max(w, h)
            if x1 - x0 < 2 * r or y1 - y0 < 2 * r:
                return None
            it = self._try(name, self.rng.uniform(x0 + r, x1 - r), self.rng.uniform(y0 + r, y1 - r),
                           yaw, inside)
            if it:
                return it
        return None

    def front(self, anchor, name, inside, gap=0.15):
        """In front of a wall/center anchor, along its facing direction."""
        f, (ax, ay) = anchor["_face"], anchor["_ext"]
        w, h, _ = self.a.dims[name]
        depth_a = ay if f[0] == 0 else ax
        for yaw in (anchor["yaw"], anchor["yaw"] + 180, anchor["yaw"] + 90):
            ex, ey = _extent(w, h, yaw)
            depth_o = ey if f[0] == 0 else ex
            d = depth_a / 2 + gap + depth_o / 2
            it = self._try(name, anchor["x"] + f[0] * d, anchor["y"] + f[1] * d, yaw, inside)
            if it:
                return it
        return None

    def beside(self, anchor, name, inside, gap=0.1):
        """Next to a wall anchor along the wall, back aligned with the anchor's back."""
        f, (ax, ay) = anchor["_face"], anchor["_ext"]
        w, h, _ = self.a.dims[name]
        t = (f[1], -f[0]) if f[0] == 0 else (-f[1], f[0])
        len_a = ax if f[0] == 0 else ay
        depth_a = ay if f[0] == 0 else ax
        for sgn in self.rng.sample((1, -1), 2):
            yaw = anchor["yaw"]
            ex, ey = _extent(w, h, yaw)
            len_o, depth_o = (ex, ey) if f[0] == 0 else (ey, ex)
            off = len_a / 2 + gap + len_o / 2
            back = -(depth_a / 2) + depth_o / 2
            x = anchor["x"] + t[0] * off * sgn + f[0] * back
            y = anchor["y"] + t[1] * off * sgn + f[1] * back
            it = self._try(name, x, y, yaw, inside)
            if it:
                return it
        return None

    def around(self, anchor, name, inside, n, gap=0.12):
        """Chairs along the long sides of a table anchor."""
        (ax, ay) = anchor["_ext"]
        w, h, _ = self.a.dims[name]
        long_x = ax >= ay
        L, D = (ax, ay) if long_x else (ay, ax)
        per_side = max(1, (n + 1) // 2)
        spots = []
        for s in (1, -1):
            for k in range(per_side):
                u = (k + 0.5) / per_side - 0.5
                off = D / 2 + gap + max(w, h) / 2
                if long_x:
                    spots.append((anchor["x"] + u * L * 0.9, anchor["y"] + s * off, 90 - 90 * s))
                else:
                    spots.append((anchor["x"] + s * off, anchor["y"] + u * L * 0.9, -90 * s))
        placed = []
        for x, y, yaw in spots[:n]:
            it = self._try(name, x, y, yaw + self.rng.uniform(-8, 8), inside)
            if it:
                placed.append(it)
        return placed

    def rows(self, room, name_pool, inside, aisle=2.4):
        """Parallel rack rows along the room's long axis, with aisles between them."""
        x0, y0, x1, y1 = room.bounds(0.9)
        long_x = (x1 - x0) >= (y1 - y0)
        if not name_pool:
            return []
        name = self.rng.choice(name_pool)
        w, h, _ = self.a.dims[name]
        yaw = 0 if (w >= h) == long_x else 90
        ex, ey = _extent(w, h, yaw)
        L, D = (ex, ey) if long_x else (ey, ex)
        span_l = (x0, x1) if long_x else (y0, y1)
        span_d = (y0, y1) if long_x else (x0, x1)
        placed = []
        d = span_d[0] + D / 2
        while d + D / 2 <= span_d[1]:
            u = span_l[0] + L / 2
            gap_at = self.rng.uniform(span_l[0] + 2.5, span_l[1] - 2.5)   # cross aisle
            crossed = False
            while u + L / 2 <= span_l[1]:
                if not crossed and u + L / 2 > gap_at - 1.2:      # leave a cross aisle
                    u = gap_at + 1.2 + L / 2
                    crossed = True
                    continue
                x, y = (u, d) if long_x else (d, u)
                it = self._try(name, x, y, yaw, inside)
                if it:
                    placed.append(it)
                u += L + 0.05
            d += D + aisle
        return placed


# ----------------------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------------------
def generate_map(seed, theme=None, size=None, density=None, assets=None):
    rng = random.Random(seed)
    theme = theme or rng.choice(THEMES)
    if size:
        nx, ny = size
    else:
        nx, ny = {"office": (rng.randint(6, 10), rng.randint(5, 8)),
                  "hospital": (rng.randint(6, 10), rng.randint(5, 8)),
                  "warehouse": (rng.randint(6, 10), rng.randint(5, 8)),
                  "residential": (rng.randint(4, 7), rng.randint(4, 6))}[theme]
    density = rng.uniform(0.12, 0.3) if density is None else float(density)
    assets = assets or Assets()

    if theme == "office":
        rooms = layout_corridor(nx, ny, rng, ["office_corridor", "open_office", "meeting",
                                              "private_office", "lounge", "open_office"])
    elif theme == "hospital":
        rooms = layout_corridor(nx, ny, rng, ["hospital_corridor", "ward", "ward", "exam",
                                              "waiting", "supply"])
    elif theme == "warehouse":
        rooms = layout_hall(nx, ny, rng)
    else:
        rooms = layout_bsp(nx, ny, rng, ["living", "kitchen", "bedroom", "bedroom", "study",
                                         "hallway"])
        if len(rooms) >= 4 and rng.random() < 0.35:          # L-shaped house
            corner = [k for k, rm in enumerate(rooms[1:], 1)
                      if rm.rect[0] == 0 and rm.rect[1] == 0 or rm.rect[2] == nx - 1 and rm.rect[3] == ny - 1]
            if corner:
                rest = rooms[:corner[0]] + rooms[corner[0] + 1:]
                _, shared = room_graph(rest)
                if _connected(len(rest), shared):
                    rooms = rest
    edges, entrance, owner = build_edges(rooms, theme, rng)

    style = STYLE_OF[theme]
    md = {"grid": [nx, ny], "cells": {}, "vedges": {}, "hedges": {}, "furniture": [],
          "styles": {}, "door_default": "open", "door_state": {},
          "rooms": [{"name": rm.name, "type": rm.type, "rect": list(rm.rect)} for rm in rooms],
          "generator": {"seed": seed, "theme": theme, "density_target": round(density, 3)}}
    for k, rm in enumerate(rooms):
        st = "office" if (theme == "warehouse" and rm.type == "wh_office") else style
        for (i, j) in rm.cells():
            md["cells"]["%d,%d" % (i, j)] = 2 if ((i + j) % 2 == 0 or rm.type == "hall") else 1
            md["styles"]["%d,%d" % (i, j)] = st
    for (kind, i, j), t in edges.items():
        md["vedges" if kind == "v" else "hedges"]["%d,%d" % (i, j)] = t
    if entrance:                                 # the entrance door swings inwards
        _p0, _d, right, _left = arch.edge_frame(*entrance)
        if right not in owner:
            md["door_flip"] = {arch.edge_key(*entrance): True}

    # planning grid + door clearances + keypoints (spawn first)
    g = Grid(md, nx, ny)
    for e, (mx, my), n in door_frames(edges):
        tx, ty = (-n[1], n[0])
        a, b = DOOR_CLEAR[0] / 2, DOOR_CLEAR[1]
        pts = [(mx + tx * a + n[0] * b, my + ty * a + n[1] * b),
               (mx - tx * a + n[0] * b, my - ty * a + n[1] * b),
               (mx - tx * a - n[0] * b, my - ty * a - n[1] * b),
               (mx + tx * a - n[0] * b, my + ty * a - n[1] * b)]
        g.block |= g.poly_mask(pts)
    keyp = []
    for e, (mx, my), n in door_frames(edges):
        for s in (1, -1):
            px, py = mx + n[0] * 0.7 * s, my + n[1] * 0.7 * s
            c, r = g.px(px, py)
            if 0 <= c < g.W and 0 <= r < g.H and g.free[r, c]:
                keyp.append((e, px, py))
    if entrance:
        _, (mx, my), n = [f for f in door_frames(edges) if f[0] == entrance][0]
        inside = [(px, py) for e, px, py in keyp if e == entrance]
        spawn = inside[0] if inside else (mx, my)
        sx, sy = spawn
        spawn = (mx + (sx - mx) * 1.4, my + (sy - my) * 1.4)
    else:
        spawn = ((nx * CELL) / 2, (ny * CELL) / 2)
    g.keypoints = [spawn] + [(px, py) for e, px, py in keyp]
    reach0, _ = g.reach_mask()                     # keep only keypoints reachable when empty
    g.keypoints = [spawn] + [(px, py) for px, py in g.keypoints[1:]
                             if reach0[min(g.H - 1, int(py / RES)), min(g.W - 1, int(px / RES))]]
    g.block |= g.poly_mask([(spawn[0] - 0.5, spawn[1] - 0.5), (spawn[0] + 0.5, spawn[1] - 0.5),
                            (spawn[0] + 0.5, spawn[1] + 0.5), (spawn[0] - 0.5, spawn[1] + 0.5)])

    fur = Furnisher(g, assets, rng)
    for rm in rooms:
        inside = g.poly_mask([(x, y) for x, y in _rect_pts(rm.bounds(0.13))])
        recipe = R.get(rm.type, [])
        area = rm.area_cells() * CELL * CELL
        target = density * area * (0.35 if "corridor" in rm.type else 1.0)
        scale = min(1.0, density / 0.25)            # sparser rooms at low density
        for role, how, (lo, hi), opt in recipe:
            n = rng.randint(lo, max(lo, int(round(lo + (hi - lo) * scale))))
            if how == "rows":
                fur.rows(rm, assets.roles.get(role) or [], inside)
                continue
            for _ in range(n):
                if lo == 0 and _room_fill(fur.items, rm) >= target:
                    break
                _place_group(fur, assets, rng, rm, inside, role, how, opt.get("follow", []))
        fills = FILL.get(rm.type, [])
        misses = 0
        while fills and misses < 12 and _room_fill(fur.items, rm) < target:
            role, how, follow = rng.choice(fills)
            if not _place_group(fur, assets, rng, rm, inside, role, how, follow):
                misses += 1
    md["furniture"] = [{k: v for k, v in it.items() if not k.startswith("_")} for it in fur.items]

    # robot: spawn at the entrance, one waypoint per room (greedy tour)
    reach, _ = g.reach_mask()
    wps = []
    for rm in rooms:
        x0, y0, x1, y1 = rm.bounds(0.0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        p = _nearest_true(reach, cx, cy, rm)
        if p:
            wps.append(p)
    tour, cur = [], spawn
    while wps:
        k = min(range(len(wps)), key=lambda q: math.hypot(wps[q][0] - cur[0], wps[q][1] - cur[1]))
        cur = wps.pop(k)
        tour.append([round(cur[0], 2), round(cur[1], 2)])
    yaw = 0.0
    if entrance:
        _, (mx, my), _n = [f for f in door_frames(edges) if f[0] == entrance][0]
        yaw = math.degrees(math.atan2(spawn[1] - my, spawn[0] - mx))
    md["robot"] = {"spawn": {"x": round(spawn[0], 2), "y": round(spawn[1], 2),
                             "yaw": round(yaw, 1)}, "waypoints": tour}
    return md


def _place_group(fur, assets, rng, room, inside, role, how, follow):
    """Place one item of `role` with strategy `how` (+ its follow-up items). -> item | None"""
    name = assets.pick(rng, role)
    if not name:
        return None
    it = getattr(fur, how)(room, name, inside)
    if not it:
        return None
    for frole, fhow, (flo, fhi) in follow:
        fn = rng.randint(flo, fhi)
        fname = assets.pick(rng, frole)
        if not fname or fn == 0:
            continue
        if fhow == "around":
            fur.around(it, fname, inside, fn)
        else:
            for _k in range(fn):
                getattr(fur, fhow)(it, fname, inside)
    return it


def _rect_pts(b):
    x0, y0, x1, y1 = b
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _room_fill(items, room):
    x0, y0, x1, y1 = room.bounds()
    return sum(it["w"] * it["h"] for it in items if x0 <= it["x"] <= x1 and y0 <= it["y"] <= y1)


def _nearest_true(mask, x, y, room):
    x0, y0, x1, y1 = room.bounds(0.3)
    sub = mask[int(y0 / RES):int(y1 / RES), int(x0 / RES):int(x1 / RES)]
    ys, xs = np.nonzero(sub)
    if not len(xs):
        return None
    px = (xs + int(x0 / RES) + 0.5) * RES
    py = (ys + int(y0 / RES) + 0.5) * RES
    k = int(np.argmin((px - x) ** 2 + (py - y) ** 2))
    return (float(px[k]), float(py[k]))


def _connected(n, shared):
    adj = {k: set() for k in range(n)}
    for a, b in shared:
        adj[a].add(b)
        adj[b].add(a)
    seen, stack = {0}, [0]
    while stack:
        for b in adj[stack.pop()]:
            if b not in seen:
                seen.add(b)
                stack.append(b)
    return len(seen) == n


# ----------------------------------------------------------------------------
# Metrics (check_density_distribution.py)
# ----------------------------------------------------------------------------
def map_metrics(md):
    """Density / reachability numbers of one map."""
    nx, ny = md["grid"]
    floor_cells = sum(1 for v in md["cells"].values() if v >= 1)
    floor_m2 = floor_cells * CELL * CELL
    furn = md.get("furniture", [])
    foot = sum(float(f.get("w", 0.6)) * float(f.get("h", 0.6)) for f in furn)
    g = Grid(md, nx, ny)
    for f in furn:
        w, h = float(f.get("w", 0.6)), float(f.get("h", 0.6))
        g.furn |= g.poly_mask(bbox_corners(float(f["x"]), float(f["y"]), w, h,
                                           float(f.get("yaw", 0))))
    rob = md.get("robot") or {}
    sp = rob.get("spawn")
    if sp:
        g.keypoints = [(sp["x"], sp["y"])]
    reach, free = g.reach_mask()
    n_free = int(free.sum())
    edges = arch.edges(md)
    return {
        "theme": (md.get("generator") or {}).get("theme", ""),
        "grid": "%dx%d" % (nx, ny), "rooms": len(md.get("rooms") or []),
        "floor_m2": round(floor_m2, 1), "items": len(furn),
        "footprint_m2": round(foot, 2), "density": round(foot / floor_m2, 4) if floor_m2 else 0.0,
        "items_per_10m2": round(10.0 * len(furn) / floor_m2, 3) if floor_m2 else 0.0,
        "robot_free_ratio": round(n_free / max(1, int(g.free.sum())), 4),
        "reachable_ratio": round(float(reach.sum()) / max(1, n_free), 4) if sp else None,
        "doors": sum(1 for e in edges if e[3] == EDGE_DOOR),
        "windows": sum(1 for e in edges if e[3] == EDGE_WINDOW),
        "waypoints": len(rob.get("waypoints") or []),
    }
