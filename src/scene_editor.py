"""
scene_editor.py - Grid GUI (pygame) to design a map -> generate sceneX.usd + BEV.

Usage:
    python src/scene_editor.py

Grid: 1 m cells (stronger lines every 3 m = one Office kit module); legacy 3 m maps are
converted on load (map_format.py).

Tools:
  FLOOR (1) - Click near a CELL CENTER: empty -> floor -> floor+light -> empty.
              DRAG to fill a rectangular floor area. Right-click removes a cell.
  WALL  (2) - Click / DRAG along a row or column paints the EDGE TYPE chosen in the panel
              (wall / door / window / glass / opening); clicking an edge of that type again
              clears it, clicking a door selects it. Right-click clears an edge.
              Doors: the plan shows the leaf + swing arc (red = it runs into a wall); new
              doors are fitted automatically. On a door (or the selected one): O open /
              closed, P swing side (which room), H hinge side (which jamb), A auto-fit.
              The DOOR panel shows a zoomed plan of the selected door with these controls.
  STYLE (4) - Paint a room style (office / hospital / warehouse / home) on floor cells:
              click or DRAG a rectangle; pick the style in the panel. Walls take the style
              of the room each face looks into.
  ROBOT (5) - Pick the robot model in the panel (JetAuto Pro, JetBot, TurtleBot 3/4 -
              data/robots); its footprint is drawn to scale at the spawn.
              Click = add a waypoint, Shift+click = robot spawn, wheel = spawn heading,
              right-click = remove the nearest waypoint / spawn. Exported with the BEV as
              <stem>_nav.yaml + follow_waypoints.py (ROS 2 Nav2) and as USD markers.
  FURNITURE (3) - Pick a prop in the LIBRARY (thumbnail cards of the top-down captures);
              a preview under the cursor shows where it lands (green = free, red = no room).
              Click empty space to place (auto-selected).
              Click a placed prop to SELECT it; HOLD left + drag to MOVE it.
              PLACEMENT: grid 50 / 25 / 10 / 5 cm or free (G), Wall magnet (M) slides props
              flush against walls / other props within 25 cm, No overlap (K) keeps props off
              walls, doorways, door leaves and each other (overlaps are outlined in red).
              Alt while moving = free position, arrows nudge one grid step (Shift x5),
              Del deletes, Ctrl+D duplicates.
              TRANSFORM panel: edit X/Y/Yaw and pick a SHAPE (BBox / Sphere / Mesh) -
              the chosen shape becomes the default for new props. Right-click opens a
              menu (Select / Duplicate / Rotate 90 / Delete). Wheel = rotate 5 deg/notch.
View:
  Ctrl + wheel = ZOOM (around cursor) | HOLD middle button + drag = PAN
  Home / 0 = reset view to 100%%
Shortcuts:
  1 floor | 2 wall | 3/F furniture | Tab switch tool | W auto-walls | C clear
  S save USD (sceneX.usd) | Ctrl+S save map JSON | L load latest map
  B  export BEV (CSV + SVG + PNG/PGM) into output/bev/
  V  mesh view: footprint mask <-> colored top-down capture
  + / -  resize grid | R rotate furniture 5 deg (selected or about-to-place)
  F11  toggle fullscreen | drag window edge to resize
  Esc  exit fullscreen -> close menu -> deselect -> back to floor
"""
import os
import json
import glob
import math

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

import scene_builder as sb
import bev_export as bev

from config import (PROJECT_ROOT, MAPS_DIR, CELL, KIT_M, DOOR_GAP, SNAP as _SNAP,
                    FURNITURE_CATEGORIES,
                    EDGE_NAMES, EDGE_CYCLE, EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS,
                    EDGE_OPENING, STYLES, DEFAULT_STYLE, STYLE_COLORS, DOOR_DEFAULT,
                    WINDOW_COL, GLASS_COL, ROBOT_COL, SPAWN_COL, PLAN_BG, BORDER, ON_ACTIVE)
import ui_kit as ui
import architecture as arch
import robots
import placement as pl
import map_format
from config import (C0, C1, C2, C3, C4, MESH_MARK, BG, GRID_LINE, FLOOR_COL,
                    FLOOR_HOVER, LIGHT_COL, WALL_COL, DOOR_COL, HOVER_EDGE,
                    PANEL_BG, BTN, BTN_HOVER, BTN_ACTIVE, TEXT, TEXT_DIM,
                    FURNI_COL, FURNI_SEL, ACCENT, ACCENT_DIM, PANEL_ROW_ALT,
                    FIELD_BG, FIELD_ACTIVE_BG, DANGER, SECTION_LINE)
from utils import bbox_corners, load_prop_shapes

SNAP = _SNAP

WIN_W, WIN_H = 1240, 820
MIN_W, MIN_H = 900, 680
PANEL_W = 360
# panel buttons laid out two per row
HALF_KEYS = ("gx-", "gx+", "gy-", "gy+", "undo", "redo", "walls", "clear", "usd", "export",
             "savemap", "load", "magnet", "overlap")
SNAP_LABELS = {0.5: "50 cm", 0.25: "25", 0.1: "10", 0.05: "5", 0.0: "Free"}
LIB_COLS = 3             # furniture library: cards per row
THUMB = 64               # thumbnail size in a library card (px)
PAD = 34
STATUS_H = 52
FOOTER_H = 100           # fixed command bar at the bottom of the panel
TOOLS = [("floor", "Floor", "1"), ("wall", "Wall", "2"), ("furniture", "Props", "3"),
         ("style", "Style", "4"), ("robot", "Robot", "5")]
TOOL_HINTS = {
    "floor": ["Click a cell: floor \u2192 floor + light \u2192 empty",
              "Drag: fill a rectangle   \u00b7   Right-click: remove"],
    "wall": ["Click / drag along a grid line: paint the type below",
             "Click a door: select it   \u00b7   Right-click: erase",
             "On a door: O open \u00b7 P swing \u00b7 H hinge \u00b7 A fit"],
    "furniture": ["Click empty floor: place   \u00b7   Drag a prop: move",
                  "Wheel / R: rotate   \u00b7   Right-click: menu",
                  "V: colour view   \u00b7   Del: delete   \u00b7   Ctrl+D: duplicate"],
    "style": ["Click / drag over floor cells: paint the room style",
              "Each wall face takes the style of the room it faces"],
    "robot": ["Click: waypoint   \u00b7   Shift+click: spawn",
              "Wheel: spawn heading   \u00b7   Right-click: remove a point"],
}
EDGE_SWATCH = {EDGE_WALL: WALL_COL, EDGE_DOOR: DOOR_COL, EDGE_WINDOW: WINDOW_COL,
               EDGE_GLASS: GLASS_COL, EDGE_OPENING: None}
OK_COL = (63, 130, 98)
EDGE_HIT = 0.24          # edge-snap threshold (cell fraction)
MAJOR_LINE = (212, 204, 188)   # grid line every kit module (3 m)


class Editor:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Isaac Scene Builder")
        self.win_w, self.win_h = WIN_W, WIN_H
        self.windowed_size = (WIN_W, WIN_H)
        self.fullscreen = False
        self.screen = pygame.display.set_mode((self.win_w, self.win_h), pygame.RESIZABLE)
        self.f = ui.fonts()
        self.font = self.f["body"]
        self.font_s = self.f["small"]
        self.font_b = self.f["title"]
        self.clock = pygame.time.Clock()

        self.nx, self.ny = 30, 24    # 1 m cells
        self.cells = {}        # (i,j) -> 1|2
        self.vedges = {}       # (i,j) -> 1|2
        self.hedges = {}       # (i,j) -> 1|2
        self.furniture = []    # {asset,x,y,yaw,shape,w,h,r}

        self.tool = "floor"    # "floor" | "wall" | "furniture"
        self.palette = sb.available_furniture()
        self.pal_sel = 0
        self.structure = {}    # legacy prop overrides: {"wall":..,"floor":..}
        self.styles = {}       # (i,j) -> room style (unset = DEFAULT_STYLE)
        self.door_state = {}   # "v:i,j" -> "open" | "closed" (unset = door_default)
        self.door_default = DOOR_DEFAULT
        self.door_flip = {}    # "v:i,j" -> True: door swings into the other room
        self.door_hinge = {}   # "v:i,j" -> True: hinge on the other jamb
        self.sel_door = None   # ("vedge"|"hedge", i, j) shown in the door inspector
        self._door_key = None  # cache of door_issues()
        self._door_bad = set()
        self.edge_type = EDGE_WALL          # what a wall-tool drag paints
        self.paint_style = "hospital"       # what the style tool paints
        self.robot = {"model": robots.DEFAULT_ROBOT}   # + "spawn": {x,y,yaw}, "waypoints"
        self.place_shape = "bbox"   # default shape when placing a new prop
        self.snap_step = 0.1        # placement grid (m); 0 = free (Alt also frees a move)
        self.wall_magnet = True     # M: slide props flush against walls / props nearby
        self.no_overlap = True      # K: props may not overlap walls, doorways or each other
        self._walls_key = None      # cache of placement.wall_obstacles()
        self._walls = []
        self._clash_key = None      # cache of the indices of overlapping props
        self._clash = set()
        self._ghost_key = None      # cache of the placement preview under the cursor
        self._ghost = None
        self._thumb_cache = {}      # (asset, size) -> Surface | None
        self._drag_was_clear = True
        self.cur_yaw = 0.0
        self.msg = "Ready. FLOOR tool: click / drag to paint floor."
        self.buttons = []       # (rect, key, label)

        self.panel_scroll = 0        # cuon toan bo panel ben phai
        self._panel_max_scroll = 0
        self._pal_rects = []         # [(idx, Rect)] cho hit-test palette
        self._scroll_to_transform = False
        self._pal_filter = ""        # search filter cho furniture palette
        self._pal_cat = "All"     # category filter
        self._pal_search_active = False  # entering search text
        self._pal_cat_rects = []     # [(cat_name, Rect)] cho hit-test category tabs
        self._pal_search_rect = None # Rect of the search field

        self.selected = None        # index into self.furniture, or None
        self.ctx_menu = None         # {"pos","target","items"}
        self.active_field = None     # "x" | "y" | "yaw" | "w" | "h" | "r" | None
        self.field_buffer = ""
        self.field_rects = {}        # ten field -> Rect (cho hit-test click)

        self.drag_start = None       # ("cell",i,j) | ("edge",kind,i,j)
        self.drag_cur = None         # current (mx,my) while dragging
        self._mesh_cache = {}        # (asset, color) -> (surface, w_m, h_m) | None
        self.color_view = False      # V: draw mesh props with their colored top-down image

        # zoom / pan (view)
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.base_cs = 20
        self.panning = False         # panning the view with the middle button
        self.pan_last = None
        self.move_drag = None        # index of furniture being drag-moved

        # undo / redo
        self._undo_stack = []
        self._redo_stack = []
        self._max_undo = 50

        # named save
        self.current_map_name = None  # current file name (None = unsaved)

        self._recalc_layout()

    # ---- undo / redo ----
    def _snapshot(self):
        """Save current state to the undo stack."""
        self._undo_stack.append(self.map_data())
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            self.msg = "Nothing to undo."
            return
        self._redo_stack.append(self.map_data())
        self.load_map_data(self._undo_stack.pop())
        self.msg = "Undone."

    def redo(self):
        if not self._redo_stack:
            self.msg = "Nothing to redo."
            return
        self._undo_stack.append(self.map_data())
        self.load_map_data(self._redo_stack.pop())
        self.msg = "Redone."

    # ---- furniture palette filter ----
    def palette_categories(self):
        """Category tabs (curated + asset library), computed once."""
        if getattr(self, "_categories", None) is None:
            try:
                self._categories = sb.palette_categories()
            except Exception:
                self._categories = dict(FURNITURE_CATEGORIES)
        return self._categories

    def filtered_palette(self):
        """Return the palette filtered by category + search text."""
        cats = self.palette_categories()
        if self._pal_cat != "All" and self._pal_cat in cats:
            allowed = set(cats[self._pal_cat])
            items = [(n, r) for (n, r) in self.palette if n in allowed]
        else:
            items = list(self.palette)
        if self._pal_filter:
            q = self._pal_filter.lower()
            lib = sb.load_library()
            items = [(n, r) for (n, r) in items if q in n.lower()
                     or q in lib.get(n, {}).get("env", "")
                     or q in lib.get(n, {}).get("category", "")]
        return items

    # ---- layout / view ----
    def _recalc_layout(self):
        area_w = self.win_w - PANEL_W - 2 * PAD
        area_h = self.win_h - 2 * PAD - STATUS_H
        self.base_cs = max(6, int(min(area_w / self.nx, area_h / self.ny)))
        self._apply_view()

    def _apply_view(self):
        """Update effective cs/ox/oy from base_cs + zoom + pan."""
        self.cs = max(4.0, self.base_cs * self.zoom)
        self.ox = PAD + self.pan_x
        self.oy = PAD + self.pan_y

    def zoom_at(self, mx, my, factor):
        """Zoom around (mx,my): keep the world point under the cursor fixed."""
        fx = (mx - self.ox) / self.cs
        fy = (my - self.oy) / self.cs
        self.zoom = max(0.25, min(8.0, self.zoom * factor))
        new_cs = max(4.0, self.base_cs * self.zoom)
        self.pan_x = (mx - fx * new_cs) - PAD
        self.pan_y = (my - fy * new_cs) - PAD
        self._apply_view()

    def reset_view(self):
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._apply_view()
        self.msg = "View reset (zoom 100%%)."

    def on_resize(self, w, h):
        """User resized the window -> update size & layout."""
        self.win_w = max(MIN_W, w)
        self.win_h = max(MIN_H, h)
        if not self.fullscreen:
            self.windowed_size = (self.win_w, self.win_h)
        self.screen = pygame.display.set_mode((self.win_w, self.win_h), pygame.RESIZABLE)
        self._recalc_layout()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            info = pygame.display.Info()
            self.win_w, self.win_h = info.current_w, info.current_h
            self.screen = pygame.display.set_mode((self.win_w, self.win_h), pygame.FULLSCREEN)
        else:
            self.win_w, self.win_h = self.windowed_size
            self.screen = pygame.display.set_mode((self.win_w, self.win_h), pygame.RESIZABLE)
        self._recalc_layout()

    # ---- coord helpers ----
    def cell_rect(self, i, j):
        return pygame.Rect(self.ox + i * self.cs, self.oy + j * self.cs, self.cs, self.cs)

    def screen_to_cellfrac(self, mx, my):
        fx = (mx - self.ox) / self.cs
        fy = (my - self.oy) / self.cs
        return fx, fy

    def screen_to_usd(self, mx, my):
        x = (mx - self.ox) / self.cs * sb.CELL
        y = (my - self.oy) / self.cs * sb.CELL
        return x, y

    def usd_to_screen(self, x, y):
        return self.ox + x / sb.CELL * self.cs, self.oy + y / sb.CELL * self.cs

    def in_grid(self, mx, my):
        return (self.ox <= mx < self.ox + self.nx * self.cs and
                self.oy <= my < self.oy + self.ny * self.cs)

    def hit(self, mx, my):
        """Tra ve ('cell', i, j) hoac ('vedge'|'hedge', i, j) tuy vi tri click."""
        fx, fy = self.screen_to_cellfrac(mx, my)
        i, j = int(fx), int(fy)
        rx, ry = fx - i, fy - j
        # distance to the 4 edges
        dl, dr, dt, db = rx, 1 - rx, ry, 1 - ry
        m = min(dl, dr, dt, db)
        if m < EDGE_HIT:
            if m == dl:
                return ("vedge", i, j)
            if m == dr:
                return ("vedge", i + 1, j)
            if m == dt:
                return ("hedge", i, j)
            return ("hedge", i, j + 1)
        return ("cell", i, j)

    def hit_cell(self, mx, my):
        """Always return ('cell', i, j) for the FLOOR tool."""
        fx, fy = self.screen_to_cellfrac(mx, my)
        return ("cell", int(fx), int(fy))

    def nearest_edge(self, mx, my):
        """Always return the nearest edge ('vedge'|'hedge', i, j) for the WALL tool."""
        fx, fy = self.screen_to_cellfrac(mx, my)
        i, j = int(fx), int(fy)
        rx, ry = fx - i, fy - j
        dl, dr, dt, db = rx, 1 - rx, ry, 1 - ry
        m = min(dl, dr, dt, db)
        if m == dl:
            return ("vedge", i, j)
        if m == dr:
            return ("vedge", i + 1, j)
        if m == dt:
            return ("hedge", i, j)
        return ("hedge", i, j + 1)

    # ---- edit ops ----
    def cycle_cell(self, i, j):
        if not (0 <= i < self.nx and 0 <= j < self.ny):
            return
        self._snapshot()
        s = self.cells.get((i, j), 0)
        s = (s + 1) % 3
        if s == 0:
            self.cells.pop((i, j), None)
        else:
            self.cells[(i, j)] = s

    def erase_cell(self, i, j):
        if (i, j) in self.cells:
            self._snapshot()
        self.cells.pop((i, j), None)

    def erase_edge(self, kind, i, j):
        d = self.vedges if kind == "vedge" else self.hedges
        if (i, j) in d:
            self._snapshot()
        d.pop((i, j), None)

    def fill_floor_rect(self, i0, j0, i1, j1):
        """Fill floor (state 1) over all cells in the box; do not downgrade lights (state 2)."""
        self._snapshot()
        lo_i, hi_i = sorted((i0, i1))
        lo_j, hi_j = sorted((j0, j1))
        n = 0
        for i in range(max(0, lo_i), min(self.nx, hi_i + 1)):
            for j in range(max(0, lo_j), min(self.ny, hi_j + 1)):
                if self.cells.get((i, j), 0) == 0:
                    self.cells[(i, j)] = 1
                    n += 1
        self.msg = "Floor: added %d cells." % n

    def draw_wall_run(self, start_edge, mx, my):
        """Paint self.edge_type on a run of edges from the start edge to the cursor."""
        self._snapshot()
        kind, i0, j0 = start_edge
        end = self.nearest_edge(mx, my)
        d = self.vedges if kind == "vedge" else self.hedges
        n = 0
        i1 = j1 = None
        if kind == "vedge":
            # fixed column i0, run along j
            j1 = end[2] if end[0] == "vedge" else j0
            for j in range(min(j0, j1), max(j0, j1) + 1):
                if 0 <= i0 <= self.nx and 0 <= j <= self.ny - 1 \
                        and d.get((i0, j)) != self.edge_type:
                    d[(i0, j)] = self.edge_type
                    n += 1
        else:
            # fixed row j0, run along i
            i1 = end[1] if end[0] == "hedge" else i0
            for i in range(min(i0, i1), max(i0, i1) + 1):
                if 0 <= i <= self.nx - 1 and 0 <= j0 <= self.ny \
                        and d.get((i, j0)) != self.edge_type:
                    d[(i, j0)] = self.edge_type
                    n += 1
        self.msg = "%s: %d segments." % (EDGE_NAMES[self.edge_type], n)
        if self.edge_type == EDGE_DOOR and n:
            run = ([("vedge", i0, j) for j in range(min(j0, j1), max(j0, j1) + 1)]
                   if kind == "vedge" else
                   [("hedge", i, j0) for i in range(min(i0, i1), max(i0, i1) + 1)])
            for door in run:
                self.fit_door(door)
            self.sel_door = run[-1]

    def paint_style_rect(self, i0, j0, i1, j1):
        """Paint self.paint_style on every floor cell in the box."""
        self._snapshot()
        lo_i, hi_i = sorted((i0, i1))
        lo_j, hi_j = sorted((j0, j1))
        n = 0
        for i in range(max(0, lo_i), min(self.nx, hi_i + 1)):
            for j in range(max(0, lo_j), min(self.ny, hi_j + 1)):
                if self.cells.get((i, j), 0) >= 1:
                    if self.paint_style == DEFAULT_STYLE:
                        self.styles.pop((i, j), None)
                    else:
                        self.styles[(i, j)] = self.paint_style
                    n += 1
        self.msg = "Style %s: %d cells." % (STYLES[self.paint_style]["label"], n)

    def remove_robot_point(self, x, y, radius=1.0):
        """Remove the waypoint (or spawn) nearest to (x, y) within radius m."""
        best, best_d = None, radius
        for k, (wx, wy) in enumerate(self.robot.get("waypoints") or []):
            dd = math.hypot(wx - x, wy - y)
            if dd < best_d:
                best, best_d = k, dd
        sp = self.robot.get("spawn")
        if sp and math.hypot(sp["x"] - x, sp["y"] - y) < best_d:
            self._snapshot()
            self.robot["spawn"] = None
            self.msg = "Spawn removed."
        elif best is not None:
            self._snapshot()
            self.robot["waypoints"].pop(best)
            self.msg = "Waypoint %d removed." % (best + 1)

    def draw_robot(self):
        """Robot footprint at the spawn (to scale) + heading arrow, numbered waypoints
        joined by the route polyline."""
        sp = self.robot.get("spawn")
        pts = [self.usd_to_screen(x, y) for x, y in self.robot.get("waypoints") or []]
        route = ([self.usd_to_screen(sp["x"], sp["y"])] if sp else []) + pts
        if len(route) >= 2:
            pygame.draw.lines(self.screen, ROBOT_COL, False, route, 2)
        rad = max(5, int(self.cs) // 7)
        for k, (px, py) in enumerate(pts):
            pygame.draw.circle(self.screen, ROBOT_COL, (int(px), int(py)), rad)
            s = self.f["caption"].render(str(k + 1), True, C4)
            self.screen.blit(s, (int(px - s.get_width() / 2), int(py - s.get_height() / 2)))
        spec = robots.get(self.robot.get("model"))
        if sp and spec:
            body = [self.usd_to_screen(x, y) for x, y in
                    robots.place(spec, sp["x"], sp["y"], sp.get("yaw", 0.0))]
            ring = self.usd_to_screen(sp["x"], sp["y"])
            pygame.draw.circle(self.screen, SPAWN_COL, (int(ring[0]), int(ring[1])),
                               max(3, int(spec["r_circ"] / sb.CELL * self.cs)), 1)
            if len(body) >= 3:
                pygame.draw.polygon(self.screen, SPAWN_COL, body)
                pygame.draw.polygon(self.screen, C0, body, 1)
        if sp:
            cx, cy = self.usd_to_screen(sp["x"], sp["y"])
            a = math.radians(sp.get("yaw", 0.0))
            L = rad * 2.4
            if spec:                     # arrow from the footprint centre past its front
                L = max(L, spec["r_circ"] / sb.CELL * self.cs * 1.6)
            tip = (cx + math.cos(a) * L, cy + math.sin(a) * L)
            pygame.draw.circle(self.screen, SPAWN_COL, (int(cx), int(cy)), 4 if spec else rad + 2)
            pygame.draw.line(self.screen, C0, (cx, cy), tip, 3)
            pygame.draw.circle(self.screen, SPAWN_COL, (int(tip[0]), int(tip[1])), 3)

    def draw_robot_card(self, bx, y, w):
        """Footprint preview + size of the chosen robot model."""
        spec = robots.get(self.robot.get("model"))
        if not spec:
            ui.text(self.screen, "No robots - run tools/import_robots.py", (bx, y), self.font_s, TEXT_DIM)
            return y + 34
        card = pygame.Rect(bx, y, w, 116)
        ui.card(self.screen, card, with_shadow=False)
        box = pygame.Rect(card.x + 10, card.y + 10, 96, 96)
        pygame.draw.rect(self.screen, PLAN_BG, box, border_radius=6)
        k = (box.w / 2 - 6) / spec["r_circ"]
        cx, cy = box.center
        pts = [(cx + px * k, cy - py * k) for px, py in spec["footprint"]["points"]]
        pygame.draw.circle(self.screen, BORDER, (cx, cy), int(spec["r_circ"] * k), 1)
        pygame.draw.polygon(self.screen, SPAWN_COL, pts)
        pygame.draw.polygon(self.screen, C0, pts, 1)
        pygame.draw.line(self.screen, C0, (cx, cy), (cx + spec["r_insc"] * k * 0.85, cy), 2)
        xs = [p[0] for p in spec["footprint"]["points"]]
        ys = [p[1] for p in spec["footprint"]["points"]]
        tx = box.right + 12
        ui.text(self.screen, robots.label(spec["id"]), (tx, card.y + 10), self.f["body"], C0)
        rows = ["%.2f x %.2f m" % (max(xs) - min(xs), max(ys) - min(ys)),
                "height %.2f m" % spec["height"], "radius %.2f m" % spec["r_circ"],
                spec.get("drive", "")]
        for n, s in enumerate(rows):
            ui.text(self.screen, s, (tx, card.y + 34 + n * 18), self.font_s, TEXT_DIM)
        return y + card.h + 16

    # ---- doors: swing side, hinge side, open / closed, auto-fit ----
    def _door_target(self, mx=None, my=None):
        """The door under the cursor (wall tool), else the selected door; None if neither."""
        if mx is not None and self.in_grid(mx, my):
            kind, i, j = self.nearest_edge(mx, my)
            d = self.vedges if kind == "vedge" else self.hedges
            if d.get((i, j)) == EDGE_DOOR:
                return (kind, i, j)
        if self.sel_door:
            kind, i, j = self.sel_door
            d = self.vedges if kind == "vedge" else self.hedges
            if d.get((i, j)) == EDGE_DOOR:
                return self.sel_door
        return None

    def _door_op(self, op, mx=None, my=None):
        door = self._door_target(mx, my)
        if door is None:
            self.msg = "No door here - point at a door or select one."
            return
        kind, i, j = door
        key = arch.edge_key(kind, i, j)
        self._snapshot()
        if op == "open":
            is_open = arch.door_is_open(self.map_data_light(), kind[0], i, j)
            self.door_state[key] = "closed" if is_open else "open"
            self.msg = "Door %s." % self.door_state[key]
        elif op == "swing":
            if self.door_flip.pop(key, None) is None:
                self.door_flip[key] = True
            self.msg = "Door now swings into the other room."
        elif op == "hinge":
            if self.door_hinge.pop(key, None) is None:
                self.door_hinge[key] = True
            self.msg = "Hinge moved to the other jamb."
        elif op == "fit":
            if not self.fit_door(door, keep_room=False):
                self._undo_stack.pop()
                return
        self.sel_door = door
        if op != "fit" and door in self.door_issues():
            self.msg += "  The leaf hits a wall - try A (auto-fit)."

    def fit_door(self, door, keep_room=True):
        """Pick swing side + hinge so the open leaf clears the walls (keeps the current
        room first). True if the door is clear afterwards."""
        kind, i, j = door
        key = arch.edge_key(kind, i, j)
        best = arch.best_door_setup(self.edge_map(), kind[0], i, j)
        if best is None:
            self.msg = "Every way this door opens hits a wall - close it or move it."
            return False
        flip, mir = best
        before = (bool(self.door_flip.get(key)), bool(self.door_hinge.get(key)))
        self.door_flip.pop(key, None)
        self.door_hinge.pop(key, None)
        if flip:
            self.door_flip[key] = True
        if mir:
            self.door_hinge[key] = True
        what = (["hinge moved to the other jamb"] if mir != before[1] else []) + \
            (["now swings into the other room"] if flip != before[0] else [])
        self.msg = ("Door fitted: %s." % ", ".join(what)) if what else "Door swing is clear."
        return True

    def door_issues(self):
        """Doors whose open leaf runs into a wall (drawn red), cached."""
        key = (self._walls_key, tuple(sorted(self.door_flip.items())),
               tuple(sorted(self.door_hinge.items())), tuple(sorted(self.door_state.items())),
               self.door_default)
        if key != self._door_key:
            md = self.edge_map()
            walls = pl.wall_obstacles(dict(md, door_state={}, door_default="closed"))
            bad = set()
            for kind, d in (("vedge", self.vedges), ("hedge", self.hedges)):
                for (i, j), t in d.items():
                    if t == EDGE_DOOR and arch.door_is_open(md, kind[0], i, j) and \
                            arch.door_swing_blocked(md, kind[0], i, j, walls):
                        bad.add((kind, i, j))
            self._door_key, self._door_bad = key, bad
        return self._door_bad

    def click_edge(self, kind, i, j):
        """Wall tool click: paint the chosen type; clicking a door selects it, clicking an
        edge of the chosen type again clears it."""
        d = self.vedges if kind == "vedge" else self.hedges
        maxi = self.nx if kind == "vedge" else self.nx - 1
        maxj = self.ny - 1 if kind == "vedge" else self.ny
        if not (0 <= i <= maxi and 0 <= j <= maxj):
            return
        cur = d.get((i, j), 0)
        if cur == EDGE_DOOR and self.edge_type == EDGE_DOOR:
            self.sel_door = (kind, i, j)
            self.msg = "Door selected - O open / P swing / H hinge / A auto-fit."
            return
        self._snapshot()
        if cur == self.edge_type:
            d.pop((i, j), None)
            self.msg = "%s removed." % EDGE_NAMES[cur]
            return
        d[(i, j)] = self.edge_type
        self.msg = "%s." % EDGE_NAMES[self.edge_type]
        if self.edge_type == EDGE_DOOR:
            self.sel_door = (kind, i, j)
            self.fit_door(self.sel_door)

    def auto_walls(self):
        ve, he = sb.boundary_edges(self.cells)
        added = 0
        for e in ve:
            if self.vedges.get(e, 0) == 0:
                self.vedges[e] = 1
                added += 1
        for e in he:
            if self.hedges.get(e, 0) == 0:
                self.hedges[e] = 1
                added += 1
        self.msg = "Auto-walls: added %d boundary segments." % added

    # ---- placement (grid snap, wall magnet, no overlap: placement.py) ----
    def walls(self):
        """Wall / doorway / door-leaf rectangles, rebuilt when the edges change."""
        key = (tuple(sorted(self.vedges.items())), tuple(sorted(self.hedges.items())),
               self.door_default, tuple(sorted(self.door_state.items())),
               tuple(sorted(self.door_flip.items())), tuple(sorted(self.door_hinge.items())))
        if key != self._walls_key:
            self._walls_key, self._walls = key, pl.wall_obstacles(self.edge_map())
        return self._walls

    def edge_map(self):
        """The edges + door settings as map data (what architecture's door / wall
        functions read)."""
        return {"cell": CELL, "grid": [self.nx, self.ny], "cells": {}, "furniture": [],
                "vedges": {"%d,%d" % k: v for k, v in self.vedges.items()},
                "hedges": {"%d,%d" % k: v for k, v in self.hedges.items()},
                "door_default": self.door_default, "door_state": self.door_state,
                "door_flip": self.door_flip, "door_hinge": self.door_hinge}

    def other_polys(self, skip=None):
        return [pl.footprint(f) for k, f in enumerate(self.furniture) if k != skip]

    def settle(self, f, x, y, skip=None):
        """(x, y, ok, what) for prop `f` dropped at (x, y); Alt = free position (no grid,
        no magnet). The floor limit applies once the plan has floor cells."""
        free = bool(pygame.key.get_mods() & pygame.KMOD_ALT)
        return pl.settle(f, x, y, self.walls(), self.other_polys(skip),
                         step=0.0 if free else self.snap_step,
                         use_magnet=self.wall_magnet and not free, no_overlap=self.no_overlap,
                         floor=self.cells if (self.no_overlap and self.cells) else None)

    def clashes(self):
        """Indices of props overlapping a wall, a doorway or another prop (drawn in red)."""
        key = (self._walls_key, repr(self.furniture))
        if key != self._clash_key:
            walls = self.walls()
            polys = self.other_polys()
            bad = set()
            for k, poly in enumerate(polys):
                if pl.collides(poly, walls, polys[k + 1:]):
                    bad.add(k)
                    for m, o in enumerate(polys[k + 1:], k + 1):
                        if pl.collides(poly, [], [o]):
                            bad.add(m)
            self._clash_key, self._clash = key, bad
        return self._clash

    def _gap_text(self, f):
        g = pl.wall_gap(f, self.walls())
        return "" if g is None or g > 1.5 else "   ·   wall gap %.2f m" % g

    def new_prop(self):
        name = self.palette[self.pal_sel][0]
        sh = bev.default_shape(name)   # measured w/h/r; shape from current placement mode
        return {"asset": name, "x": 0.0, "y": 0.0, "yaw": self.cur_yaw, "shape": self.place_shape,
                "w": sh["w"], "h": sh["h"], "r": sh["r"]}

    def place_furniture(self, mx, my):
        """Place the palette prop at the cursor; False if there is no free spot there."""
        if not self.palette:
            self.msg = "No furniture prop available."
            return False
        f = self.new_prop()
        x, y, ok, what = self.settle(f, *self.screen_to_usd(mx, my))
        if not ok:
            self.msg = "No room for %s here (walls / doorway / props). K allows overlap." % f["asset"]
            return False
        self._snapshot()
        f["x"], f["y"] = round(x, 4), round(y, 4)
        self.furniture.append(f)
        self.msg = "Placed %s @ (%.2f, %.2f)%s%s" % (
            f["asset"], x, y, "  ·  flush to " + what if what else "", self._gap_text(f))
        return True

    def remove_nearest_furniture(self, mx, my):
        if not self.furniture:
            return
        x, y = self.screen_to_usd(mx, my)
        best, bd = None, 1e9
        for f in self.furniture:
            d = (f["x"] - x) ** 2 + (f["y"] - y) ** 2
            if d < bd:
                bd, best = d, f
        if best is not None and bd < (1.5 ** 2):
            self.furniture.remove(best)
            self.msg = "Deleted %s" % best["asset"]

    def find_furniture_at(self, mx, my):
        """Return the furniture index nearest (mx,my) within its footprint radius, or None."""
        if not self.furniture:
            return None
        x, y = self.screen_to_usd(mx, my)
        pad = 4.0 / self.cs * sb.CELL            # a few pixels of slack around small props
        best_idx, best_a = None, 1e9
        for idx, f in enumerate(self.furniture):
            if pl.contains(pl.footprint(f), x, y, pad):
                x0, y0, x1, y1 = pl.aabb(pl.footprint(f))
                if (x1 - x0) * (y1 - y0) < best_a:     # the smallest prop under the cursor
                    best_a, best_idx = (x1 - x0) * (y1 - y0), idx
        return best_idx

    def select_furniture(self, idx):
        self.selected = idx
        self.active_field = None
        if idx is not None:
            self._scroll_to_transform = True   # auto-scroll panel to the TRANSFORM block
            self.msg = "Selected %s" % self.furniture[idx]["asset"]

    def switch_tool(self, t):
        self.tool = t
        self.panel_scroll = 0          # back to top so the tool buttons show

    def deselect(self):
        self.panel_scroll = 0
        self.selected = None
        self.active_field = None

    def open_ctx_menu(self, mx, my):
        idx = self.find_furniture_at(mx, my)
        if idx is not None:
            items = [("select", "Select"), ("duplicate", "Duplicate"),
                     ("rot90", "Rotate 90"), ("delete", "Delete")]
        else:
            items = [("close", "Close")]
        self.ctx_menu = {"pos": (mx, my), "target": idx, "items": items}

    def duplicate_furniture(self, idx):
        self._snapshot()
        src = self.furniture[idx]
        clone = dict(src)
        x, y, ok, _ = self.settle(clone, src["x"] + 0.5, src["y"])
        clone["x"], clone["y"] = round(x, 4), round(y, 4)
        self.furniture.append(clone)
        self.select_furniture(len(self.furniture) - 1)
        self.msg = "Duplicated %s" % clone["asset"]

    def rotate_furniture(self, idx, delta):
        self._snapshot()
        f = self.furniture[idx]
        old = dict(f)
        f["yaw"] = (f["yaw"] + delta) % 360
        if self.wall_magnet or (self.no_overlap and pl.collides(pl.footprint(f), self.walls(),
                                                                self.other_polys(idx))):
            x, y, ok, _ = self.settle(f, f["x"], f["y"], skip=idx)   # stays flush when turned
            if not ok:                       # no free spot nearby: keep the old pose
                f.update(old)
                self._undo_stack.pop()
                self.msg = "No room to turn %s here." % f["asset"]
                return
            f["x"], f["y"] = round(x, 4), round(y, 4)
        self.msg = "Rotated %s -> %d deg%s" % (f["asset"], int(f["yaw"]), self._gap_text(f))

    def nudge_selected(self, dx, dy):
        """Arrow keys: move the selected prop by one grid step (Shift x5), blocked by walls."""
        f = self.furniture[self.selected]
        step = self.snap_step or 0.01
        if pygame.key.get_mods() & pygame.KMOD_SHIFT:
            step *= 5
        g = dict(f, x=round(f["x"] + dx * step, 4), y=round(f["y"] + dy * step, 4))
        if self.no_overlap and pl.collides(pl.footprint(g), self.walls(),
                                           self.other_polys(self.selected),
                                           self.cells or None):
            self.msg = "Blocked - %s would overlap.%s" % (f["asset"], self._gap_text(f))
            return
        self._snapshot()
        f["x"], f["y"] = g["x"], g["y"]
        self.msg = "%s @ (%.2f, %.2f)%s" % (f["asset"], f["x"], f["y"], self._gap_text(f))

    def delete_furniture(self, idx):
        self._snapshot()
        f = self.furniture.pop(idx)
        if self.selected == idx:
            self.deselect()
        elif self.selected is not None and self.selected > idx:
            self.selected -= 1
        self.msg = "Deleted %s" % f["asset"]

    def do_ctx_action(self, key):
        target = self.ctx_menu["target"] if self.ctx_menu else None
        if key == "select" and target is not None:
            self.select_furniture(target)
        elif key == "duplicate" and target is not None:
            self.duplicate_furniture(target)
        elif key == "rot90" and target is not None:
            self.rotate_furniture(target, 90)
        elif key == "delete" and target is not None:
            self.delete_furniture(target)
        self.ctx_menu = None

    # ---- transform field editing ----
    def _clamp_field(self, name, v):
        if name == "yaw":
            return v % 360
        if name in ("w", "h", "r"):
            return max(0.05, v)   # minimum positive size
        return v

    def start_edit_field(self, name):
        if self.selected is None:
            return
        val = self.furniture[self.selected].get(name, 0.0)
        self.active_field = name
        self.field_buffer = str(int(round(val))) if name == "yaw" else ("%.2f" % val)

    def commit_active_field(self):
        if self.active_field is None:
            return
        name = self.active_field
        if self.selected is not None:
            try:
                v = float(self.field_buffer)
            except ValueError:
                v = None
            if v is not None:
                old_val = self.furniture[self.selected].get(name, 0.0)
                new_val = self._clamp_field(name, v)
                if old_val != new_val:
                    self._snapshot()
                self.furniture[self.selected][name] = new_val
        self.active_field = None
        self.field_buffer = ""

    def cancel_active_field(self):
        self.active_field = None
        self.field_buffer = ""

    def step_field(self, name, sign):
        if self.selected is None:
            return
        self._snapshot()
        step = 15.0 if name == "yaw" else (self.snap_step or 0.01)
        f = self.furniture[self.selected]
        v = f.get(name, 0.0) + (step if sign > 0 else -step)
        f[name] = self._clamp_field(name, v)

    def set_shape(self, shape):
        # set as default for new props
        self.place_shape = shape
        # if a prop is selected, also change its shape
        if self.selected is not None:
            self.furniture[self.selected]["shape"] = shape
            self.active_field = None
        self.msg = "Placing: %s" % shape

    # ---- data model io ----
    def map_data(self):
        return {
            "cell": CELL,
            "grid": [self.nx, self.ny],
            "cells": {"%d,%d" % k: v for k, v in self.cells.items()},
            "vedges": {"%d,%d" % k: v for k, v in self.vedges.items()},
            "hedges": {"%d,%d" % k: v for k, v in self.hedges.items()},
            "furniture": [dict(f) for f in self.furniture],
            "structure": dict(self.structure),
            "styles": {"%d,%d" % k: v for k, v in self.styles.items()},
            "door_default": self.door_default,
            "door_state": dict(self.door_state),
            "door_flip": dict(self.door_flip),
            "door_hinge": dict(self.door_hinge),
            "robot": {"model": self.robot.get("model") or robots.DEFAULT_ROBOT,
                      "spawn": dict(self.robot["spawn"]) if self.robot.get("spawn") else None,
                      "waypoints": [list(w) for w in self.robot.get("waypoints", [])]},
        }

    def load_map_data(self, m):
        m = map_format.ensure(m)              # legacy 3 m maps open on the 1 m grid
        self.nx, self.ny = m["grid"]
        self.cells = sb._ikey(m.get("cells"))
        self.vedges = sb._ikey(m.get("vedges"))
        self.hedges = sb._ikey(m.get("hedges"))
        self.furniture = list(m.get("furniture", []))
        self.structure = dict(m.get("structure") or {})
        self.styles = sb._ikey(m.get("styles"))
        self.door_state = dict(m.get("door_state") or {})
        self.door_default = m.get("door_default") or DOOR_DEFAULT
        self.door_flip = dict(m.get("door_flip") or {})
        self.door_hinge = dict(m.get("door_hinge") or {})
        self.sel_door = None
        r = m.get("robot") or {}
        self.robot = {"model": r.get("model") or robots.DEFAULT_ROBOT,
                      "spawn": dict(r["spawn"]) if r.get("spawn") else None,
                      "waypoints": [list(w) for w in r.get("waypoints") or []]}
        self.deselect()
        self.ctx_menu = None
        self._recalc_layout()

    def cycle_structure(self, key):
        """Cycle the structural prop choice (wall/floor)."""
        choices = sb.STRUCTURE_CHOICES.get(key, [])
        if not choices:
            return
        cur = self.structure.get(key, choices[0])
        nxt = choices[(choices.index(cur) + 1) % len(choices)] if cur in choices else choices[0]
        self.structure[key] = nxt
        self.msg = "Structure %s -> %s" % (key, nxt)

    def save_map(self, name=None):
        """Save map. name=None + unnamed -> auto-increment; name given -> named/overwrite."""
        if not os.path.isdir(MAPS_DIR):
            os.makedirs(MAPS_DIR)
        if name:
            filename = name if name.endswith(".json") else name + ".json"
        elif self.current_map_name:
            filename = self.current_map_name
        else:
            n = 1
            while os.path.exists(os.path.join(MAPS_DIR, "map%d.json" % n)):
                n += 1
            filename = "map%d.json" % n
        p = os.path.join(MAPS_DIR, filename)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(self.map_data(), fh, indent=2)
        self.current_map_name = filename
        self.msg = "Map saved: %s" % filename

    def list_maps(self):
        """Return saved maps sorted most-recent first."""
        if not os.path.isdir(MAPS_DIR):
            return []
        files = sorted(glob.glob(os.path.join(MAPS_DIR, "*.json")), key=os.path.getmtime)
        return [os.path.basename(f) for f in files]

    def load_map_by_name(self, filename):
        """Load a map by name."""
        path = os.path.join(MAPS_DIR, filename)
        if not os.path.isfile(path):
            self.msg = "Map not found: %s" % filename
            return
        with open(path, encoding="utf-8") as fh:
            self.load_map_data(json.load(fh))
        self.current_map_name = filename
        self.msg = "Da mo: %s" % filename

    def load_latest_map(self):
        files = sorted(glob.glob(os.path.join(MAPS_DIR, "*.json")), key=os.path.getmtime)
        if not files:
            self.msg = "No saved map."
            return
        with open(files[-1], encoding="utf-8") as fh:
            self.load_map_data(json.load(fh))
        self.current_map_name = os.path.basename(files[-1])
        self.msg = "Da mo: %s" % self.current_map_name

    def validate_map(self):
        """Validate the map and return a list of warnings (list of str)."""
        warnings = []
        if not self.cells:
            warnings.append("No floor cells.")
        if not self.hedges and not self.vedges:
            warnings.append("No walls.")
        for fi, f in enumerate(self.furniture):
            name = f.get("asset", "?")
            x, y = f.get("x", 0), f.get("y", 0)
            if not (-2.0 <= x <= (self.nx + 2) * CELL and -2.0 <= y <= (self.ny + 2) * CELL):
                warnings.append("Furniture #%d (%s) is outside the grid." % (fi + 1, name))
        # check for overlaps
        pos_map = {}
        for fi, f in enumerate(self.furniture):
            key = (round(f.get("x", 0), 2), round(f.get("y", 0), 2))
            if key in pos_map:
                name = f.get("asset", "?")
                warnings.append("Furniture #%d (%s) overlaps #%d." % (fi + 1, name, pos_map[key] + 1))
            pos_map[key] = fi
        return warnings

    def save_usd(self):
        warnings = self.validate_map()
        if not self.cells:
            self.msg = "No floor cells to export."
            return
        if warnings:
            self.msg = "Warning: " + " | ".join(warnings) + " — exporting..."
        out = sb.next_scene_path()
        try:
            st = sb.build_scene(self.map_data(), out)
        except Exception as e:
            self.msg = "Build error: %s" % e
            return
        self.msg = "Exported %s | floor %d, light %d, wall %d, door %d, furniture %d" % (
            os.path.basename(out), st["floor"], st["light"], st["wall"], st["door"], st["furniture"])

    def export_bev(self):
        if not self.cells and not self.furniture:
            self.msg = "Nothing to export to BEV."
            return
        warnings = self.validate_map()
        if warnings:
            self.msg = "Warning: " + " | ".join(warnings) + " — exporting BEV..."
        stem = os.path.splitext(os.path.basename(sb.next_scene_path()))[0]
        try:
            st = bev.export_scene(self.map_data(), stem=stem)
        except Exception as e:
            self.msg = "BEV export error: %s" % e
            return
        self.msg = "BEV -> output/bev/%s/ (csv,svg,png,pgm,yaml%s%s) | floor %d, wall %d, props %d" % (
            stem, ",occ" if st.get("occ") else "", ",nav2" if st.get("nav") else "",
            st["floor"], st["wall"], st["prop"])

    def clear(self):
        self.cells.clear(); self.vedges.clear(); self.hedges.clear(); self.furniture.clear()
        self.deselect()
        self.ctx_menu = None
        self.msg = "Cleared the whole map."

    def resize_grid(self, dnx, dny):
        step = max(1, int(round(KIT_M / CELL)))      # grow / shrink by one 3 m module
        self.nx = max(2, min(120, self.nx + dnx * step))
        self.ny = max(2, min(120, self.ny + dny * step))
        # drop elements outside the grid
        self.cells = {k: v for k, v in self.cells.items() if 0 <= k[0] < self.nx and 0 <= k[1] < self.ny}
        self.vedges = {k: v for k, v in self.vedges.items() if 0 <= k[0] <= self.nx and 0 <= k[1] < self.ny}
        self.hedges = {k: v for k, v in self.hedges.items() if 0 <= k[0] < self.nx and 0 <= k[1] <= self.ny}
        self._recalc_layout()

    # ---- input ----
    def on_mouse_down(self, mx, my, button):
        # middle button (2) -> pan the view anywhere
        if button == 2:
            self.panning = True
            self.pan_last = (mx, my)
            return
        # a context menu is open -> handle it first, swallow the click
        if self.ctx_menu is not None:
            for i, (key, _label) in enumerate(self.ctx_menu["items"]):
                rect = self._ctx_item_rect(i)
                if rect.collidepoint(mx, my):
                    self.do_ctx_action(key)
                    return
            self.ctx_menu = None
            return
        # panel?
        if mx >= self.win_w - PANEL_W:
            self.panel_click(mx, my, button)
            return
        # clicked outside the panel -> commit the field being edited (if any)
        self.commit_active_field()
        if not self.in_grid(mx, my):
            return
        if self.tool == "furniture":
            if button == 1:
                idx = self.find_furniture_at(mx, my)
                if idx is not None:
                    self.select_furniture(idx)
                    self._snapshot()                    # snapshot before dragging
                    self.move_drag = idx          # hold left + drag -> move
                    self._drag_was_clear = idx not in self.clashes()
                elif self.place_furniture(mx, my):
                    self.select_furniture(len(self.furniture) - 1)
                    self.move_drag = self.selected
                    self._drag_was_clear = True
            elif button == 3:
                self.open_ctx_menu(mx, my)
            return
        # FLOOR / WALL: left starts a drag; right clears a single cell/edge
        if self.tool == "robot":
            x, y = self.screen_to_usd(mx, my)
            x, y = pl.snap(x, self.snap_step or 0.01), pl.snap(y, self.snap_step or 0.01)
            if button == 1:
                self._snapshot()
                if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    yaw = (self.robot.get("spawn") or {}).get("yaw", 0.0)
                    self.robot["spawn"] = {"x": x, "y": y, "yaw": yaw}
                    self.msg = "Robot spawn @ (%.1f, %.1f)" % (x, y)
                else:
                    self.robot.setdefault("waypoints", []).append([x, y])
                    self.msg = "Waypoint %d @ (%.1f, %.1f)" % (len(self.robot["waypoints"]), x, y)
            elif button == 3:
                self.remove_robot_point(x, y)
            return
        if self.tool in ("floor", "style"):
            if button == 1:
                self.drag_start = self.hit_cell(mx, my)
                self.drag_cur = (mx, my)
            elif button == 3:
                _, i, j = self.hit_cell(mx, my)
                self.erase_cell(i, j)
        elif self.tool == "wall":
            if button == 1:
                self.drag_start = ("edge",) + self.nearest_edge(mx, my)
                self.drag_cur = (mx, my)
            elif button == 3:
                kind, i, j = self.nearest_edge(mx, my)
                self.erase_edge(kind, i, j)

    def on_mouse_motion(self, mx, my):
        if self.panning and self.pan_last is not None:
            self.pan_x += mx - self.pan_last[0]
            self.pan_y += my - self.pan_last[1]
            self.pan_last = (mx, my)
            self._apply_view()
            return
        if self.move_drag is not None and 0 <= self.move_drag < len(self.furniture):
            f = self.furniture[self.move_drag]
            x, y, ok, what = self.settle(f, *self.screen_to_usd(mx, my), skip=self.move_drag)
            if ok or not self._drag_was_clear:      # an overlapping prop may be dragged out
                f["x"], f["y"] = round(x, 4), round(y, 4)
                self._drag_was_clear = self._drag_was_clear or ok
            self.msg = "Moving %s @ (%.2f, %.2f)%s%s" % (
                f["asset"], f["x"], f["y"], "  ·  flush to " + what if (ok and what) else "",
                self._gap_text(f))
            return
        if self.drag_start is not None:
            self.drag_cur = (mx, my)

    def on_mouse_up(self, mx, my, button):
        if button == 2:
            self.panning = False
            self.pan_last = None
            return
        if self.move_drag is not None:
            self.move_drag = None
            return
        if button != 1 or self.drag_start is None:
            self.drag_start = None
            self.drag_cur = None
            return
        start = self.drag_start
        self.drag_start = None
        self.drag_cur = None
        if start[0] == "cell":
            _, i0, j0 = start
            _, i1, j1 = self.hit_cell(mx, my)
            if self.tool == "style":
                self.paint_style_rect(i0, j0, i1, j1)
            elif (i0, j0) == (i1, j1):
                self.cycle_cell(i0, j0)     # click don -> giu chu ky 3 trang thai
            else:
                self.fill_floor_rect(i0, j0, i1, j1)
        elif start[0] == "edge":
            _, kind, i0, j0 = start
            end = self.nearest_edge(mx, my)
            if end == (kind, i0, j0):
                self.click_edge(kind, i0, j0)
            else:
                self.draw_wall_run((kind, i0, j0), mx, my)

    def panel_click(self, mx, my, button):
        for rect, key, _ in getattr(self, "footer_buttons", []):
            if rect.collidepoint(mx, my):
                self.commit_active_field()
                self.do_action(key)
                return
        if my >= getattr(self, "_panel_view_h", self.win_h):
            return                                # the bar between the content and status
        # field in the Transform panel
        if self.selected is not None and self.tool == "furniture":
            for name, rect in self.field_rects.items():
                if rect.collidepoint(mx, my):
                    if button == 1:
                        self.start_edit_field(name)
                    return
        self.commit_active_field()
        for rect, key, _ in self.buttons:
            if rect.collidepoint(mx, my):
                self.do_action(key)
                return
        # palette list
        for idx, rect in self._pal_rects:
            if rect.collidepoint(mx, my):
                self.pal_sel = idx
                self.tool = "furniture"
                self.msg = "Picked: %s" % self.palette[idx][0]
                return
        # category tabs
        if hasattr(self, '_pal_cat_rects'):
            for cat_name, rect in self._pal_cat_rects:
                if rect.collidepoint(mx, my):
                    self._pal_cat = cat_name
                    self._pal_filter = ""
                    return
        # search field click
        if self._pal_search_rect is not None and self._pal_search_rect.collidepoint(mx, my):
            self._pal_search_active = True
            return
        else:
            if getattr(self, '_pal_search_active', False):
                self._pal_search_active = False

    def toggle_magnet(self):
        self.wall_magnet = not self.wall_magnet
        self.msg = "Wall magnet %s" % ("on: props snap flush to walls / props" if self.wall_magnet else "off")

    def toggle_overlap(self):
        self.no_overlap = not self.no_overlap
        self.msg = "No overlap %s" % ("on: walls, doorways and props block" if self.no_overlap
                                       else "off: props may overlap (shown in red)")

    def cycle_snap(self):
        steps = list(pl.SNAP_STEPS)
        k = steps.index(self.snap_step) if self.snap_step in steps else 0
        self.do_action("snap_%g" % steps[(k + 1) % len(steps)])

    def do_action(self, key):
        if key == "floor": self.switch_tool("floor")
        elif key == "wall": self.switch_tool("wall")
        elif key == "furni": self.switch_tool("furniture")
        elif key == "style": self.switch_tool("style")
        elif key == "robot": self.switch_tool("robot")
        elif key.startswith("et_"):
            self.edge_type = int(key[3:])
            self.msg = "Wall drag paints: %s" % EDGE_NAMES[self.edge_type]
        elif key.startswith("snap_"):
            self.snap_step = float(key[5:])
            self.msg = "Placement grid: %s" % ("free" if not self.snap_step else "%g cm" % (self.snap_step * 100))
        elif key == "magnet":
            self.toggle_magnet()
        elif key == "overlap":
            self.toggle_overlap()
        elif key.startswith("rb_"):
            self._snapshot()
            self.robot["model"] = key[3:]
            spec = robots.get(key[3:])
            self.msg = "Robot: %s  (r %.2f m, h %.2f m)" % (spec["name"], spec["r_circ"], spec["height"])
        elif key.startswith("st_"):
            self.paint_style = key[3:]
            self.msg = "Style brush: %s" % STYLES[self.paint_style]["label"]
        elif key in ("door_open", "door_swing", "door_hinge", "door_fit"):
            self._door_op({"door_open": "open", "door_swing": "swing", "door_hinge": "hinge",
                           "door_fit": "fit"}[key])
        elif key == "route_clear":
            self._snapshot()
            self.robot["waypoints"] = []
            self.msg = "Route cleared."
        elif key == "door_def":
            self._snapshot()
            self.door_default = "closed" if self.door_default == "open" else "open"
            self.msg = "Doors default: %s" % self.door_default
        elif key == "undo": self.undo()
        elif key == "redo": self.redo()
        elif key == "walls": self.auto_walls()
        elif key == "clear": self.clear()
        elif key == "usd": self.save_usd()
        elif key == "savemap": self.save_map()
        elif key == "load": self.load_latest_map()
        elif key == "export": self.export_bev()
        elif key == "gx+": self.resize_grid(1, 0)
        elif key == "gx-": self.resize_grid(-1, 0)
        elif key == "gy+": self.resize_grid(0, 1)
        elif key == "gy-": self.resize_grid(0, -1)
        elif key == "cyc_wall": self.cycle_structure("wall")
        elif key == "cyc_floor": self.cycle_structure("floor")
        elif key == "tf_dup" and self.selected is not None: self.duplicate_furniture(self.selected)
        elif key == "tf_del" and self.selected is not None: self.delete_furniture(self.selected)
        elif key.startswith("shape_"): self.set_shape(key[6:])
        elif key.startswith("step") and self.selected is not None:
            field = key[4:-1]
            sign = 1 if key[-1] == "+" else -1
            self.step_field(field, sign)

    def on_key(self, ev):
        mods = pygame.key.get_mods()
        k = ev.key
        # typing a number into a Transform field
        if self.active_field is not None:
            if k == pygame.K_RETURN or k == pygame.K_KP_ENTER:
                self.commit_active_field()
            elif k == pygame.K_ESCAPE:
                self.cancel_active_field()
            elif k == pygame.K_BACKSPACE:
                self.field_buffer = self.field_buffer[:-1]
            elif k == pygame.K_MINUS or k == pygame.K_KP_MINUS:
                if "-" not in self.field_buffer:
                    self.field_buffer = "-" + self.field_buffer
            elif k in (pygame.K_PERIOD, pygame.K_KP_PERIOD):
                if "." not in self.field_buffer:
                    self.field_buffer += "."
            elif pygame.K_0 <= k <= pygame.K_9:
                self.field_buffer += chr(k)
            elif pygame.K_KP0 <= k <= pygame.K_KP9:
                self.field_buffer += chr(ord('0') + (k - pygame.K_KP0))
            return
        # entering search text filter
        if getattr(self, '_pal_search_active', False):
            if k == pygame.K_ESCAPE:
                self._pal_search_active = False
                self._pal_filter = ""
            elif k == pygame.K_RETURN or k == pygame.K_KP_ENTER:
                self._pal_search_active = False
            elif k == pygame.K_BACKSPACE:
                self._pal_filter = self._pal_filter[:-1]
            elif 32 <= k < 127:
                self._pal_filter += chr(k)
            return
        if k == pygame.K_F11: self.toggle_fullscreen()
        elif k == pygame.K_1: self.switch_tool("floor")
        elif k == pygame.K_4: self.switch_tool("style")
        elif k == pygame.K_5: self.switch_tool("robot")
        elif k == pygame.K_o and self.tool == "wall":
            self._door_op("open", *pygame.mouse.get_pos())
        elif k == pygame.K_p and self.tool == "wall":
            self._door_op("swing", *pygame.mouse.get_pos())
        elif k == pygame.K_h and self.tool == "wall":
            self._door_op("hinge", *pygame.mouse.get_pos())
        elif k == pygame.K_a and self.tool == "wall":
            self._door_op("fit", *pygame.mouse.get_pos())
        elif k == pygame.K_2: self.switch_tool("wall")
        elif k in (pygame.K_3, pygame.K_f): self.switch_tool("furniture")
        elif k == pygame.K_TAB:
            order = ["floor", "wall", "furniture"]
            self.switch_tool(order[(order.index(self.tool) + 1) % 3])
        elif k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN) and \
                self.tool == "furniture" and self.selected is not None:
            self.nudge_selected(*{pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0),
                                  pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1)}[k])
        elif k == pygame.K_g: self.cycle_snap()
        elif k == pygame.K_m: self.toggle_magnet()
        elif k == pygame.K_k: self.toggle_overlap()
        elif k == pygame.K_DELETE and self.tool == "furniture" and self.selected is not None:
            self.delete_furniture(self.selected)
        elif k == pygame.K_d and (mods & pygame.KMOD_CTRL) and self.selected is not None:
            self.duplicate_furniture(self.selected)
        elif k == pygame.K_w: self.auto_walls()
        elif k == pygame.K_c: self.clear()
        elif k == pygame.K_s and (mods & pygame.KMOD_CTRL): self.save_map()
        elif k == pygame.K_s: self.save_usd()
        elif k == pygame.K_z and (mods & pygame.KMOD_CTRL): self.undo()
        elif k == pygame.K_y and (mods & pygame.KMOD_CTRL): self.redo()
        elif k == pygame.K_l: self.load_latest_map()
        elif k == pygame.K_b: self.export_bev()
        elif k == pygame.K_v:
            self.color_view = not self.color_view
            self.msg = "Mesh view: %s" % ("colored top-down" if self.color_view else "footprint mask")
        elif k == pygame.K_r:
            if self.selected is not None:
                self.rotate_furniture(self.selected, 5)
            else:
                self.cur_yaw = (self.cur_yaw + 5) % 360
        elif k in (pygame.K_HOME, pygame.K_0): self.reset_view()
        elif k in (pygame.K_PLUS, pygame.K_EQUALS): self.resize_grid(1, 1)
        elif k == pygame.K_MINUS: self.resize_grid(-1, -1)
        elif k == pygame.K_ESCAPE:
            if self.fullscreen:
                self.toggle_fullscreen()
            elif self.ctx_menu is not None:
                self.ctx_menu = None
            elif self.selected is not None:
                self.deselect()
            else:
                self.switch_tool("floor")

    def on_wheel(self, dy, ctrl=False):
        mx, my = pygame.mouse.get_pos()
        over_panel = mx >= self.win_w - PANEL_W
        # Ctrl + wheel -> zoom around cursor
        if ctrl and not over_panel:
            self.zoom_at(mx, my, 1.15 if dy > 0 else 1.0 / 1.15)
            return
        if over_panel:
            self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll - dy * 40))
        elif self.tool == "robot" and self.robot.get("spawn"):
            sp = self.robot["spawn"]
            sp["yaw"] = (sp.get("yaw", 0.0) + dy * 15) % 360
            self.msg = "Spawn heading %d deg" % int(sp["yaw"])
        elif self.tool == "furniture":
            if self.selected is not None:
                self.rotate_furniture(self.selected, dy * 5)   # rotate 5 deg per notch
            else:
                self.cur_yaw = (self.cur_yaw + dy * 5) % 360

    # ---- draw ----
    def draw(self):
        self.screen.fill(BG)
        # the plan sits on a white sheet with a soft shadow
        sheet = pygame.Rect(self.ox, self.oy, int(self.nx * self.cs), int(self.ny * self.cs))
        ui.card(self.screen, sheet.inflate(24, 24), fill=PLAN_BG, radius=10)
        self.draw_grid()
        self.draw_panel()
        self.draw_status()
        self.draw_ctx_menu()
        pygame.display.flip()

    def draw_grid(self):
        mx, my = pygame.mouse.get_pos()
        in_grid = self.in_grid(mx, my)
        hover = None
        if in_grid and self.drag_start is None:
            if self.tool in ("floor", "style"):
                hover = self.hit_cell(mx, my)
            elif self.tool == "wall":
                hover = self.nearest_edge(mx, my)
        # cells
        for (i, j), s in self.cells.items():
            r = self.cell_rect(i, j)
            pygame.draw.rect(self.screen, STYLE_COLORS.get(self.styles.get((i, j)), FLOOR_COL), r)
            if s == 2:                          # ceiling light: small champagne dot + ring
                rad = max(2, int(0.12 / CELL * self.cs))
                pygame.draw.circle(self.screen, LIGHT_COL, r.center, rad)
                pygame.draw.circle(self.screen, LIGHT_COL, r.center, rad + 4, 1)
        # hover cell
        if hover and hover[0] == "cell" and 0 <= hover[1] < self.nx and 0 <= hover[2] < self.ny:
            if (hover[1], hover[2]) not in self.cells:
                r = self.cell_rect(hover[1], hover[2])
                pygame.draw.rect(self.screen, FLOOR_HOVER, r, 2)
        # drag preview
        self.draw_drag_preview()
        # grid lines
        major = max(1, int(round(KIT_M / CELL)))     # every 3 m (kit module) a stronger line
        fine = self.cs >= 9                           # 1 m lines only when they do not crowd
        for i in range(self.nx + 1):
            if i % major and not fine:
                continue
            x = self.ox + i * self.cs
            pygame.draw.line(self.screen, GRID_LINE if i % major else MAJOR_LINE,
                             (x, self.oy), (x, self.oy + self.ny * self.cs))
        for j in range(self.ny + 1):
            if j % major and not fine:
                continue
            y = self.oy + j * self.cs
            pygame.draw.line(self.screen, GRID_LINE if j % major else MAJOR_LINE,
                             (self.ox, y), (self.ox + self.nx * self.cs, y))
        # edges
        for (i, j), s in self.vedges.items():
            self.draw_edge("vedge", i, j, s)
        for (i, j), s in self.hedges.items():
            self.draw_edge("hedge", i, j, s)
        # hover edge
        if hover and hover[0] in ("vedge", "hedge"):
            self.draw_edge(hover[0], hover[1], hover[2], -1)
        # furniture (overlapping ones get a red outline)
        clash = self.clashes() if self.furniture else set()
        for idx, f in enumerate(self.furniture):
            self.draw_furni(f, selected=(idx == self.selected))
            if idx in clash:
                pts = [self.usd_to_screen(x, y) for x, y in pl.footprint(f)]
                pygame.draw.polygon(self.screen, DANGER, pts, 2)
        self.draw_ghost(mx, my, in_grid)
        self.draw_robot()

    def draw_ghost(self, mx, my, in_grid):
        """Where the palette prop would land under the cursor: its footprint (green = free,
        red = no room) plus its colored top-down image."""
        if (self.tool != "furniture" or not in_grid or self.move_drag is not None
                or self.ctx_menu is not None or not self.palette
                or self.find_furniture_at(mx, my) is not None):
            return
        alt = bool(pygame.key.get_mods() & pygame.KMOD_ALT)
        key = (mx, my, self.pal_sel, self.cur_yaw, self.place_shape, self.snap_step,
               self.wall_magnet, self.no_overlap, alt, self._walls_key, len(self.furniture),
               self.zoom, self.pan_x, self.pan_y)
        if key != self._ghost_key:
            f = self.new_prop()
            x, y, ok, what = self.settle(f, *self.screen_to_usd(mx, my))
            f["x"], f["y"] = x, y
            self._ghost_key, self._ghost = key, (f, ok, what)
        f, ok, what = self._ghost
        col = SPAWN_COL if ok else DANGER
        pts = [self.usd_to_screen(x, y) for x, y in pl.footprint(f)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = pygame.Rect(min(xs) - 2, min(ys) - 2, max(xs) - min(xs) + 4, max(ys) - min(ys) + 4)
        layer = pygame.Surface(box.size, pygame.SRCALPHA)
        local = [(x - box.x, y - box.y) for x, y in pts]
        pygame.draw.polygon(layer, col + (46,), local)
        mesh = self._get_mesh_surface(f["asset"], color=True)
        if mesh is not None and f.get("shape") != "sphere":
            surf, w_m, h_m = mesh
            img = pygame.transform.smoothscale(surf, (max(2, int(w_m / sb.CELL * self.cs)),
                                                      max(2, int(h_m / sb.CELL * self.cs))))
            img = pygame.transform.rotate(img, -f.get("yaw", 0.0))
            img.set_alpha(150)
            sx, sy = self.usd_to_screen(f["x"], f["y"])
            layer.blit(img, img.get_rect(center=(sx - box.x, sy - box.y)))
        self.screen.blit(layer, box.topleft)
        pygame.draw.polygon(self.screen, col, pts, 2)
        if what and ok:                               # flush: mark the touching side
            ui.text(self.screen, "flush to " + what, (box.right + 6, box.y - 2), self.f["caption"], col)

    def draw_drag_preview(self):
        if self.drag_start is None or self.drag_cur is None:
            return
        mx, my = self.drag_cur
        if self.drag_start[0] == "cell":
            _, i0, j0 = self.drag_start
            _, i1, j1 = self.hit_cell(mx, my)
            lo_i, hi_i = sorted((max(0, min(i0, self.nx - 1)), max(0, min(i1, self.nx - 1))))
            lo_j, hi_j = sorted((max(0, min(j0, self.ny - 1)), max(0, min(j1, self.ny - 1))))
            r = pygame.Rect(self.ox + lo_i * self.cs, self.oy + lo_j * self.cs,
                            (hi_i - lo_i + 1) * self.cs, (hi_j - lo_j + 1) * self.cs)
            pygame.draw.rect(self.screen, FLOOR_HOVER, r, 3)
        elif self.drag_start[0] == "edge":
            _, kind, i0, j0 = self.drag_start
            end = self.nearest_edge(mx, my)
            if kind == "vedge":
                j1 = end[2] if end[0] == "vedge" else j0
                for j in range(min(j0, j1), max(j0, j1) + 1):
                    self.draw_edge("vedge", i0, j, -1)
            else:
                i1 = end[1] if end[0] == "hedge" else i0
                for i in range(min(i0, i1), max(i0, i1) + 1):
                    self.draw_edge("hedge", i, j0, -1)

    def draw_edge(self, kind, i, j, s):
        w = max(3, int(round(0.224 / CELL * self.cs)))       # the real 22 cm wall
        if kind == "vedge":
            x = self.ox + i * self.cs
            p0 = (x, self.oy + j * self.cs)
            p1 = (x, self.oy + (j + 1) * self.cs)
        else:
            y = self.oy + j * self.cs
            p0 = (self.ox + i * self.cs, y)
            p1 = (self.ox + (i + 1) * self.cs, y)
        if s == -1:  # hover
            pygame.draw.line(self.screen, HOVER_EDGE, p0, p1, w)
            return
        f0, f1 = DOOR_GAP
        a = (p0[0] + (p1[0] - p0[0]) * f0, p0[1] + (p1[1] - p0[1]) * f0)
        b = (p0[0] + (p1[0] - p0[0]) * f1, p0[1] + (p1[1] - p0[1]) * f1)
        if s in (EDGE_DOOR, EDGE_OPENING):
            # door / opening: gap in the middle (0.94 m clear)
            pygame.draw.line(self.screen, WALL_COL, p0, a, w)
            pygame.draw.line(self.screen, WALL_COL, b, p1, w)
            if s == EDGE_DOOR:
                self.draw_door_symbol(kind, i, j, w, a, b)
        elif s == EDGE_WINDOW:
            pygame.draw.line(self.screen, WALL_COL, p0, p1, w)
            pygame.draw.line(self.screen, WINDOW_COL, p0, p1, max(2, w // 2))
        elif s == EDGE_GLASS:
            pygame.draw.line(self.screen, GLASS_COL, p0, p1, max(2, w // 3))
        else:
            pygame.draw.line(self.screen, WALL_COL, p0, p1, w)

    def draw_door_symbol(self, kind, i, j, w, a, b):
        """Plan symbol: open leaf from its hinge + the swing arc (red when it hits a wall),
        or a line across the gap when closed; the selected door gets a gold ring."""
        md = self.map_data_light()
        bad = (kind, i, j) in self.door_issues()
        col = DANGER if bad else DOOR_COL
        if arch.door_is_open(md, kind[0], i, j):
            hinge, tip = arch.leaf_segment(md, kind[0], i, j)
            arc = [self.usd_to_screen(*arch.leaf_segment(md, kind[0], i, j, angle=ang)[1])
                   for ang in range(0, int(arch.DOOR_OPEN_DEG) + 1, 10)]
            if len(arc) > 1:
                pygame.draw.lines(self.screen, col, False, arc, 1)
            pygame.draw.line(self.screen, col, self.usd_to_screen(*hinge),
                             self.usd_to_screen(*tip), max(2, w // 2))
            hx, hy = self.usd_to_screen(*hinge)
            pygame.draw.circle(self.screen, col, (int(hx), int(hy)), max(2, w // 2))
        else:
            pygame.draw.line(self.screen, col, a, b, max(2, w // 2))
        if self.sel_door == (kind, i, j) and self.tool == "wall":
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            pygame.draw.circle(self.screen, ACCENT, (int(m[0]), int(m[1])),
                               max(8, int(0.62 / CELL * self.cs)), 2)

    def map_data_light(self):
        """Just what architecture.door_is_open() needs (cheap, called per drawn door)."""
        return {"door_default": self.door_default, "door_state": self.door_state,
                "door_flip": self.door_flip, "door_hinge": self.door_hinge}

    def _get_mesh_surface(self, asset, color=False):
        """Footprint surface from mesh_shapes/<asset>.png (cached).

        color=False: white object / transparent background mask (tinted at draw time).
        color=True : the colored top-down capture mesh_shapes/color/<asset>.png.
        Returns (surface, w_m, h_m) cropped tight to the object, or None if missing.
        Scale comes from props_shapes.json 'mesh_mpp' (legacy masks span one CELL).
        """
        key = (asset, bool(color))
        if key in self._mesh_cache:
            return self._mesh_cache[key]
        result = None
        path = os.path.join(bev.MESH_DIR, asset + ".png")
        cpath = os.path.join(bev.MESH_DIR, "color", asset + ".png")
        if os.path.isfile(path) and (not color or os.path.isfile(cpath)):
            try:
                from PIL import Image
                import numpy as np
                import shape_tools as st
                im = Image.open(path).convert("L")
                a = np.asarray(im)
                ys, xs = np.where(a < 128)          # object = pixel toi
                if len(xs) > 0:
                    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
                    if color:
                        rgba = np.ascontiguousarray(
                            np.asarray(Image.open(cpath).convert("RGBA"))[y0:y1, x0:x1])
                    else:
                        obj = a[y0:y1, x0:x1] < 128
                        rgba = np.zeros(obj.shape + (4,), dtype=np.uint8)
                        rgba[obj] = (255, 255, 255, 255)   # white, tinted at draw time
                    ch, cw = rgba.shape[:2]
                    surf = pygame.image.frombuffer(rgba.tobytes(), (cw, ch), "RGBA").convert_alpha()
                    scl = min(1.0, (320.0 if color else 160.0) / max(ch, cw))
                    if scl < 1.0:
                        surf = pygame.transform.smoothscale(surf, (max(1, int(cw * scl)), max(1, int(ch * scl))))
                    mpp = st.mesh_mpp(load_prop_shapes().get(asset), im.width)
                    result = (surf, (x1 - x0) * mpp, (y1 - y0) * mpp)
            except Exception:
                result = None
        self._mesh_cache[key] = result
        return result

    def _rot_rect_pts(self, cx, cy, wpx, hpx, yaw_deg):
        """4 corners of a rectangle (center cx,cy) rotated by yaw_deg in screen space (y-down)."""
        return bbox_corners(cx, cy, wpx, hpx, yaw_deg)

    def draw_furni(self, f, selected=False):
        sx, sy = self.usd_to_screen(f["x"], f["y"])
        shape = f.get("shape", "bbox")
        fill = FURNI_SEL if selected else FURNI_COL
        yaw = f.get("yaw", 0.0)

        if shape == "mesh":
            mesh = None
            if self.color_view:
                mesh = self._get_mesh_surface(f["asset"], color=True)
            colored = mesh is not None
            if mesh is None:
                mesh = self._get_mesh_surface(f["asset"])
            if mesh is None:
                # no mesh data -> mark with a red "?"
                if selected:
                    rpx = max(8, int(0.45 / sb.CELL * self.cs))
                    pygame.draw.circle(self.screen, ACCENT, (int(sx), int(sy)), rpx + 4, 2)
                surf = self.font_b.render("?", True, MESH_MARK)
                self.screen.blit(surf, (int(sx - surf.get_width() / 2), int(sy - surf.get_height() / 2)))
                return
            mask, w_m, h_m = mesh
            tw = max(2, int(w_m / sb.CELL * self.cs))
            th = max(2, int(h_m / sb.CELL * self.cs))
            surf = pygame.transform.smoothscale(mask, (tw, th))
            surf = surf.copy()
            if not colored:
                surf.fill(fill + (255,), special_flags=pygame.BLEND_RGBA_MULT)  # tint by state
            surf = pygame.transform.rotate(surf, -yaw)                       # yaw: y-xuong -> quay am
            rect = surf.get_rect(center=(int(sx), int(sy)))
            if selected:
                pygame.draw.circle(self.screen, ACCENT, (int(sx), int(sy)),
                                   int(max(tw, th) / 2) + 4, 2)
            self.screen.blit(surf, rect)
            return

        if shape == "sphere":
            rad = f.get("r", dict(self.palette).get(f["asset"], 0.4))
            rpx = max(4, int(rad / sb.CELL * self.cs))
            if selected:
                pygame.draw.circle(self.screen, ACCENT, (int(sx), int(sy)), rpx + 4, 2)
            pygame.draw.circle(self.screen, fill, (int(sx), int(sy)), rpx)
            pygame.draw.circle(self.screen, PLAN_BG, (int(sx), int(sy)), rpx, 1)
            ex, ey = sx + math.cos(math.radians(yaw)) * rpx, sy + math.sin(math.radians(yaw)) * rpx
            pygame.draw.line(self.screen, ACCENT if selected else PLAN_BG, (sx, sy), (ex, ey), 2)
            return

        # bbox (default): w x h rectangle rotated by yaw
        wpx = max(4, int(f.get("w", 0.8) / sb.CELL * self.cs))
        hpx = max(4, int(f.get("h", 0.8) / sb.CELL * self.cs))
        if selected:
            ring = self._rot_rect_pts(sx, sy, wpx + 8, hpx + 8, yaw)
            pygame.draw.polygon(self.screen, ACCENT, ring, 2)
        pts = self._rot_rect_pts(sx, sy, wpx, hpx, yaw)
        pygame.draw.polygon(self.screen, fill, pts)
        pygame.draw.polygon(self.screen, PLAN_BG, pts, 1)
        ex, ey = sx + math.cos(math.radians(yaw)) * wpx / 2, sy + math.sin(math.radians(yaw)) * hpx / 2
        pygame.draw.line(self.screen, ACCENT if selected else PLAN_BG, (sx, sy), (ex, ey), 2)

    def _section(self, title, bx, y, right=None):
        ui.tracked(self.screen, title, (bx, y), self.f["caption"])
        if right:
            w = self.f["caption"].size(right)[0]
            ui.text(self.screen, right, (bx + PANEL_W - 40 - w, y), self.f["caption"], TEXT_DIM)
        return y + 22

    def _half_buttons(self, defs, bx, y, bw_full, mx, my, h=32):
        """Buttons two per row: defs = [(key, label), ...]."""
        bw = (bw_full - 8) // 2
        for k, (key, label) in enumerate(defs):
            rect = pygame.Rect(bx + (k % 2) * (bw + 8), y + (k // 2) * (h + 8), bw, h)
            self._draw_button(rect, key, label, mx, my)
        return y + ((len(defs) + 1) // 2) * (h + 8)

    def draw_panel(self):
        """Header -> tool tabs -> what the tool does -> the tool's own controls -> map size;
        undo / save / export sit in a fixed bar at the bottom."""
        px = self.win_w - PANEL_W
        pygame.draw.rect(self.screen, PANEL_BG, (px, 0, PANEL_W, self.win_h))
        pygame.draw.line(self.screen, BORDER, (px, 0), (px, self.win_h))
        mx, my = pygame.mouse.get_pos()
        bx = px + 20
        bw_full = PANEL_W - 40
        self.buttons = []
        self._pal_rects = []
        self._pal_cat_rects = []
        self._pal_search_rect = None

        avail_h = self.win_h - STATUS_H - FOOTER_H
        self._panel_view_h = avail_h
        # clamp before drawing (use previous frame limit) to avoid jitter on resize
        self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll))
        # clip the panel area (above the command bar) so scrolled content stays inside
        self.screen.set_clip(pygame.Rect(px + 1, 0, PANEL_W - 1, avail_h))
        y = 20 - self.panel_scroll

        ui.text(self.screen, "Scene Editor", (bx, y), self.f["title"], C0)
        y += 26
        name = self.current_map_name or "Untitled map"
        ui.text(self.screen, "%s   \u00b7   %g \u00d7 %g m" % (name, self.nx * CELL, self.ny * CELL),
                (bx, y), self.f["subtitle"], TEXT_DIM)
        y += 28

        y = self.draw_tool_tabs(bx, y, bw_full, mx, my)
        y = self.draw_hint(bx, y, bw_full)

        if self.tool == "furniture":
            # transform inspector (only when a furniture is selected)
            if self.selected is not None and 0 <= self.selected < len(self.furniture):
                if self._scroll_to_transform:
                    # bring the TRANSFORM block near the top of view (applied next frame)
                    tf_top_abs = y + self.panel_scroll
                    self.panel_scroll = max(0, tf_top_abs - 56)
                    self._scroll_to_transform = False
                y = self.draw_transform_panel(px, y)
            else:
                self.field_rects = {}
                self._scroll_to_transform = False
            y = self.draw_placement(bx, y, bw_full, mx, my)
            y = self.draw_library(px, bx, y, bw_full, mx, my, avail_h)
        else:
            self.field_rects = {}
            self._scroll_to_transform = False
            if self.tool == "wall":
                y = self.draw_wall_section(bx, y, bw_full, mx, my)
            elif self.tool == "style":
                y = self.draw_style_section(bx, y, bw_full, mx, my)
            elif self.tool == "robot":
                y = self.draw_robot_section(bx, y, bw_full, mx, my)
            else:
                y = self.draw_floor_section(bx, y, bw_full, mx, my)
        y = self.draw_map_section(bx, y, bw_full, mx, my)

        # scroll limits + reset clip
        content_h = y + self.panel_scroll
        self._panel_max_scroll = max(0, content_h - avail_h + 8)
        self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll))
        self.screen.set_clip(None)

        # slim scrollbar (only when content overflows)
        if self._panel_max_scroll > 0:
            bar_h = max(30, int(avail_h * avail_h / float(content_h)))
            bar_y = int((avail_h - bar_h) * self.panel_scroll / self._panel_max_scroll)
            pygame.draw.rect(self.screen, BORDER, (self.win_w - 6, bar_y + 4, 3, bar_h - 8),
                             border_radius=2)
        self.draw_footer(px, bx, bw_full, mx, my)

    def draw_tool_tabs(self, bx, y, bw_full, mx, my):
        """Segmented control of the five tools (label + shortcut)."""
        gap = 4
        n = len(TOOLS)
        w = (bw_full - gap * (n - 1)) // n
        frame = pygame.Rect(bx - 4, y - 4, bw_full + 8, 56)
        pygame.draw.rect(self.screen, BTN_HOVER, frame, border_radius=12)
        for k, (tool, label, keyn) in enumerate(TOOLS):
            rect = pygame.Rect(bx + k * (w + gap), y, w, 48)
            on = self.tool == tool
            hov = rect.collidepoint(mx, my)
            if on:
                ui.shadow(self.screen, rect, 9, spread=4)
                pygame.draw.rect(self.screen, BTN_ACTIVE, rect, border_radius=9)
            elif hov:
                pygame.draw.rect(self.screen, PANEL_BG, rect, border_radius=9)
            ui.text(self.screen, label, (rect.centerx, rect.y + 17), self.f["button"],
                    ON_ACTIVE if on else TEXT, center=True)
            ui.text(self.screen, keyn, (rect.centerx, rect.y + 35), self.f["caption"],
                    ui.HINT_ON_ACTIVE if on else ui.HINT, center=True)
            self.buttons.append((rect, {"furniture": "furni"}.get(tool, tool), label))
        return y + 66

    def draw_hint(self, bx, y, bw_full):
        """What the mouse / keys do with the current tool."""
        lines = TOOL_HINTS.get(self.tool, [])
        if not lines:
            return y
        card = pygame.Rect(bx, y, bw_full, 14 + 19 * len(lines))
        pygame.draw.rect(self.screen, ACCENT_DIM, card, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT, pygame.Rect(card.x, card.y + 6, 3, card.h - 12),
                         border_radius=2)
        for k, s in enumerate(lines):
            ui.text(self.screen, self._fit_text(s, self.font_s, bw_full - 22),
                    (card.x + 14, card.y + 7 + 19 * k), self.font_s, TEXT)
        return card.bottom + 20

    def _swatch_button(self, rect, key, label, col, mx, my, gap=False):
        self._draw_button(rect, key, label, mx, my)
        sx = rect.right - 34
        sy = rect.centery
        on = key == "et_%d" % self.edge_type or key == "st_" + self.paint_style
        if gap:                                              # opening: wall | gap | wall
            c = ON_ACTIVE if on else WALL_COL
            pygame.draw.line(self.screen, c, (sx, sy), (sx + 8, sy), 4)
            pygame.draw.line(self.screen, c, (sx + 16, sy), (sx + 24, sy), 4)
        elif len(col) == 3 and key.startswith("et_"):
            pygame.draw.line(self.screen, col, (sx, sy), (sx + 24, sy), 5)
        else:
            sw = pygame.Rect(sx, sy - 8, 22, 16)
            pygame.draw.rect(self.screen, col, sw, border_radius=4)
            pygame.draw.rect(self.screen, BORDER, sw, 1, border_radius=4)

    def draw_wall_section(self, bx, y, bw_full, mx, my):
        y = self._section("Paint", bx, y)
        bw = (bw_full - 8) // 2
        types = [e for e in EDGE_CYCLE if e]
        for k, e in enumerate(types):
            rect = pygame.Rect(bx + (k % 2) * (bw + 8), y + (k // 2) * 40, bw, 32)
            self._swatch_button(rect, "et_%d" % e, EDGE_NAMES[e], EDGE_SWATCH[e] or WALL_COL,
                                mx, my, gap=e == EDGE_OPENING)
        y += ((len(types) + 1) // 2) * 40
        rect = pygame.Rect(bx, y, bw_full, 32)
        self._draw_button(rect, "door_def", "New doors: %s" % self.door_default + "\tclick to switch",
                          mx, my)
        y += 52
        door = self._door_target()
        if door is not None:
            y = self.draw_door_card(door, bx, y, bw_full, mx, my)
        else:
            ui.text(self.screen, "Click a door on the plan to edit its hinge and swing.",
                    (bx, y), self.font_s, TEXT_DIM)
            y += 36
        return y

    def draw_door_card(self, door, bx, y, bw_full, mx, my):
        """Door inspector: a zoomed plan of the door with its swing, and its controls."""
        kind, i, j = door
        md = self.edge_map()
        y = self._section("Door", bx, y, "%s %d,%d" % ("vertical" if kind == "vedge" else
                                                        "horizontal", i, j))
        box = pygame.Rect(bx, y, bw_full, 150)
        ui.card(self.screen, box, fill=PLAN_BG, with_shadow=False)
        mid, _dyaw, _h, _l = arch.door_pose(md, kind[0], i, j)
        k = (box.h - 16) / 3.2                                  # px per m: 3.2 m around the door
        cx, cy = box.center

        def scr(x, y_):
            return cx + (x - mid[0]) * k, cy + (y_ - mid[1]) * k
        clip = self.screen.get_clip()
        self.screen.set_clip(box.inflate(-2, -2).clip(clip) if clip else box.inflate(-2, -2))
        for (ci, cj) in self.cells:                              # floor around the door
            if abs((ci + 0.5) * CELL - mid[0]) < 2.6 and abs((cj + 0.5) * CELL - mid[1]) < 2.6:
                x0, y0 = scr(ci * CELL, cj * CELL)
                pygame.draw.rect(self.screen, STYLE_COLORS.get(self.styles.get((ci, cj)), FLOOR_COL),
                                 pygame.Rect(x0, y0, CELL * k + 1, CELL * k + 1))
        walls = pl.wall_obstacles(dict(md, door_state={}, door_default="closed"))
        for x0, y0, x1, y1 in walls:
            if abs((x0 + x1) / 2 - mid[0]) < 3 and abs((y0 + y1) / 2 - mid[1]) < 3:
                a0, b0 = scr(x0, y0)
                a1, b1 = scr(x1, y1)
                pygame.draw.rect(self.screen, WALL_COL,
                                 pygame.Rect(a0, b0, max(1, a1 - a0) + 1, max(1, b1 - b0) + 1))
        bad = door in self.door_issues()
        col = DANGER if bad else DOOR_COL
        opened = arch.door_is_open(md, kind[0], i, j)
        arc = [scr(*arch.leaf_segment(md, kind[0], i, j, angle=a)[1])
               for a in range(0, int(arch.DOOR_OPEN_DEG) + 1, 5)]
        hinge, tip = arch.leaf_segment(md, kind[0], i, j, opened=True)
        pygame.draw.lines(self.screen, col, False, arc, 1)
        pygame.draw.line(self.screen, col, scr(*hinge), scr(*(tip if opened else arc[0])), 4)
        hx, hy = scr(*hinge)
        pygame.draw.circle(self.screen, ACCENT, (int(hx), int(hy)), 5)
        self.screen.set_clip(clip)
        y = box.bottom + 8
        ok = not bad or not opened
        pygame.draw.circle(self.screen, OK_COL if ok else DANGER, (bx + 5, y + 9), 5)
        ui.text(self.screen, ("Swing is clear   \u00b7   gold dot = hinge" if not bad else
                              "The leaf hits a wall - try Auto-fit") if opened else
                "Closed   \u00b7   gold dot = hinge", (bx + 16, y), self.font_s,
                OK_COL if ok else DANGER)
        y += 26
        y = self._half_buttons([("door_open", ("Close" if opened else "Open") + "\tO"),
                                ("door_swing", "Swing side\tP"),
                                ("door_hinge", "Hinge side\tH"),
                                ("door_fit", "Auto-fit\tA")], bx, y, bw_full, mx, my)
        return y + 14

    def draw_style_section(self, bx, y, bw_full, mx, my):
        y = self._section("Room style", bx, y)
        bw = (bw_full - 8) // 2
        for k, (key, v) in enumerate(STYLES.items()):
            rect = pygame.Rect(bx + (k % 2) * (bw + 8), y + (k // 2) * 40, bw, 32)
            self._swatch_button(rect, "st_" + key, v["label"], STYLE_COLORS.get(key, FLOOR_COL), mx, my)
        y += ((len(STYLES) + 1) // 2) * 40 + 8
        counts = {}
        for ij in self.cells:
            s = self.styles.get(ij, DEFAULT_STYLE)
            counts[s] = counts.get(s, 0) + 1
        info = "   \u00b7   ".join("%s %g m\u00b2" % (STYLES[s]["label"], n * CELL * CELL)
                                   for s, n in sorted(counts.items()) if s in STYLES)
        if info:
            ui.text(self.screen, self._fit_text(info, self.font_s, bw_full), (bx, y), self.font_s, TEXT_DIM)
            y += 30
        return y

    def draw_robot_section(self, bx, y, bw_full, mx, my):
        if robots.load_robots():
            y = self._section("Robot model", bx, y)
            y = self._half_buttons([("rb_" + k, robots.label(k)) for k in robots.load_robots()],
                                   bx, y, bw_full, mx, my)
            y = self.draw_robot_card(bx, y + 4, bw_full)
        y = self._section("Route", bx, y)
        sp = self.robot.get("spawn")
        n = len(self.robot.get("waypoints") or [])
        ui.text(self.screen, "Spawn %s   \u00b7   %d waypoint%s" % (
            "(%.1f, %.1f)" % (sp["x"], sp["y"]) if sp else "not set", n, "" if n == 1 else "s"),
            (bx, y), self.font_s, TEXT if sp else TEXT_DIM)
        y += 26
        self._draw_button(pygame.Rect(bx, y, bw_full, 32), "route_clear", "Clear waypoints", mx, my,
                          danger=True)
        return y + 52

    def draw_floor_section(self, bx, y, bw_full, mx, my):
        y = self._section("Floor", bx, y)
        lights = sum(1 for v in self.cells.values() if v == 2)
        ui.text(self.screen, "%g m\u00b2 of floor   \u00b7   %d ceiling light%s" % (
            len(self.cells) * CELL * CELL, lights, "" if lights == 1 else "s"), (bx, y),
            self.font_s, TEXT_DIM)
        y += 28
        self._draw_button(pygame.Rect(bx, y, bw_full, 32), "walls", "Wall the floor outline\tW",
                          mx, my)
        return y + 52

    def draw_map_section(self, bx, y, bw_full, mx, my):
        """Map size steppers (3 m steps) + whole-map actions."""
        y = self._section("Map", bx, y, "%d \u00d7 %d cells" % (self.nx, self.ny))
        for label, val, minus, plus in (("Width", self.nx * CELL, "gx-", "gx+"),
                                        ("Depth", self.ny * CELL, "gy-", "gy+")):
            ui.text(self.screen, label, (bx, y + 7), self.font_s, TEXT_DIM)
            box = pygame.Rect(bx + 70, y, bw_full - 70 - 2 * 38, 30)
            ui.field(self.screen, box, "%g m" % val, self.f["mono"])
            self._draw_button(pygame.Rect(box.right + 6, y, 32, 30), minus, "\u2212", mx, my, center=True)
            self._draw_button(pygame.Rect(box.right + 44, y, 32, 30), plus, "+", mx, my, center=True)
            y += 38
        y += 4
        y = self._half_buttons([("walls", "Auto-walls\tW"), ("clear", "Clear all\tC")],
                               bx, y, bw_full, mx, my)
        return y + 10

    def draw_footer(self, px, bx, bw_full, mx, my):
        """Fixed command bar: undo / redo / load, save map / USD / BEV."""
        top = self.win_h - STATUS_H - FOOTER_H
        pygame.draw.rect(self.screen, PANEL_BG, (px + 1, top, PANEL_W - 1, FOOTER_H))
        pygame.draw.line(self.screen, BORDER, (px, top), (self.win_w, top))
        defs = [("undo", "Undo\t^Z"), ("redo", "Redo\t^Y"), ("load", "Load\tL"),
                ("savemap", "Save\t^S"), ("usd", "USD\tS"), ("export", "BEV\tB")]
        gap = 8
        w = (bw_full - 2 * gap) // 3
        self.footer_buttons = []
        for k, (key, label) in enumerate(defs):
            rect = pygame.Rect(bx + (k % 3) * (w + gap), top + 14 + (k // 3) * 40, w, 32)
            n = len(self.buttons)
            self._draw_button(rect, key, label, mx, my)
            self.footer_buttons.append(self.buttons.pop(n))

    def draw_placement(self, bx, y, bw_full, mx, my):
        """Grid step pills + wall magnet / no overlap toggles."""
        ui.tracked(self.screen, "Placement", (bx, y), self.f["caption"])
        ui.text(self.screen, "G", (bx + bw_full - 8, y), self.f["caption"], TEXT_DIM)
        y += 22
        steps = list(pl.SNAP_STEPS)
        gap = 6
        w = (bw_full - gap * (len(steps) - 1)) // len(steps)
        for k, s in enumerate(steps):
            rect = pygame.Rect(bx + k * (w + gap), y, w, 28)
            ui.pill(self.screen, rect, SNAP_LABELS[s], self.f["caption"],
                    active=(s == self.snap_step), hover=rect.collidepoint(mx, my))
            self.buttons.append((rect, "snap_%g" % s, SNAP_LABELS[s]))
        y += 38
        bw = (bw_full - 8) // 2
        self._draw_button(pygame.Rect(bx, y, bw, 32), "magnet", "Wall magnet\tM", mx, my)
        self._draw_button(pygame.Rect(bx + bw + 8, y, bw, 32), "overlap", "No overlap\tK", mx, my)
        y += 40
        ui.text(self.screen, "Alt = free move   ·   arrows nudge   ·   R / wheel rotate",
                (bx, y), self.f["caption"], TEXT_DIM)
        return y + 30

    @staticmethod
    def pretty(name):
        """Readable asset label: SM_ArmChair_01 -> ArmChair 01."""
        for pre in ("SM_", "S_", "SKM_"):
            if name.startswith(pre):
                name = name[len(pre):]
        return name.replace("_", " ")

    def _fit_text(self, s, font, w):
        if font.size(s)[0] <= w:
            return s
        while s and font.size(s + "\u2026")[0] > w:
            s = s[:-1]
        return s + "\u2026"

    def thumb(self, asset, size):
        """Colored top-down image of a prop (tinted footprint mask as fallback), fit in a
        size x size box; None if the prop has never been captured."""
        key = (asset, size)
        if key not in self._thumb_cache:
            surf = None
            mesh = self._get_mesh_surface(asset, color=True)
            colored = mesh is not None
            if mesh is None:
                mesh = self._get_mesh_surface(asset)
            if mesh is not None:
                src = mesh[0]
                k = size / float(max(src.get_width(), src.get_height()))
                surf = pygame.transform.smoothscale(src, (max(1, int(src.get_width() * k)),
                                                          max(1, int(src.get_height() * k))))
                if not colored:
                    surf = surf.copy()
                    surf.fill(FURNI_COL + (255,), special_flags=pygame.BLEND_RGBA_MULT)
            self._thumb_cache[key] = surf
        return self._thumb_cache[key]

    def _draw_thumb(self, asset, box):
        img = self.thumb(asset, min(box.w, box.h) - 8)
        if img is None:
            ui.text(self.screen, self.pretty(asset)[:1], box.center, self.f["title"], TEXT_DIM,
                    center=True)
        else:
            self.screen.blit(img, img.get_rect(center=box.center))

    def draw_library(self, px, bx, y, bw_full, mx, my, avail_h):
        """Selected prop preview, category pills, search and a grid of thumbnail cards."""
        fp = self.filtered_palette()
        ui.tracked(self.screen, "Library", (bx, y), self.f["caption"])
        n = "%d items" % len(fp)
        ui.text(self.screen, n, (bx + bw_full - self.f["caption"].size(n)[0], y),
                self.f["caption"], TEXT_DIM)
        y += 22

        # preview of the prop about to be placed
        if self.palette:
            name = self.palette[self.pal_sel][0]
            card = pygame.Rect(bx, y, bw_full, 112)
            ui.card(self.screen, card, with_shadow=False)
            box = pygame.Rect(card.x + 8, card.y + 8, 96, 96)
            pygame.draw.rect(self.screen, PLAN_BG, box, border_radius=6)
            self._draw_thumb(name, box)
            tx, tw = box.right + 12, card.right - box.right - 20
            ui.text(self.screen, self._fit_text(self.pretty(name), self.f["body"], tw),
                    (tx, card.y + 10), self.f["body"], C0)
            sh = bev.default_shape(name)
            info = sb.load_library().get(name, {})
            rows = ["%.2f x %.2f m" % (sh["w"], sh["h"]),
                    " · ".join(v for v in (info.get("category"), info.get("env")) if v) or "office pack",
                    "yaw %d deg  ·  %s" % (int(self.cur_yaw), self.place_shape)]
            for k, s in enumerate(rows):
                ui.text(self.screen, self._fit_text(s, self.font_s, tw), (tx, card.y + 36 + k * 20),
                        self.font_s, TEXT_DIM)
            y += card.h + 12

        # category tabs (pills)
        categories = ["All"] + list(self.palette_categories().keys())
        tab_x = bx
        for cat_name in categories:
            active = (cat_name == self._pal_cat)
            tab_w = ui.pill_width(cat_name, self.f["caption"], pad=10)
            if tab_x + tab_w > px + PANEL_W - 20:
                tab_x = bx
                y += 30
            tab_rect = pygame.Rect(tab_x, y, tab_w, 24)
            ui.pill(self.screen, tab_rect, cat_name, self.f["caption"], active=active,
                    hover=tab_rect.collidepoint(mx, my))
            self._pal_cat_rects.append((cat_name, tab_rect))
            tab_x += tab_w + 6
        y += 34

        # search field
        searching = getattr(self, '_pal_search_active', False)
        self._pal_search_rect = pygame.Rect(bx, y, bw_full, 32)
        if self._pal_filter or searching:
            caret = "|" if searching and (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            ui.field(self.screen, self._pal_search_rect, self._pal_filter + caret, self.font_s,
                     active=searching)
        else:
            ui.field(self.screen, self._pal_search_rect, "Search furniture, room, category",
                     self.font_s, placeholder=True)
        y += 42

        # thumbnail cards (only the visible ones are drawn / loaded)
        gap = 8
        cw = (bw_full - gap * (LIB_COLS - 1)) // LIB_COLS
        ch = THUMB + 34
        index = {item: k for k, item in enumerate(self.palette)}
        for k, item in enumerate(fp):
            name = item[0]
            real_idx = index[item]
            rect = pygame.Rect(bx + (k % LIB_COLS) * (cw + gap), y + (k // LIB_COLS) * (ch + gap), cw, ch)
            self._pal_rects.append((real_idx, rect))
            if rect.bottom < 0 or rect.top > avail_h:
                continue
            sel = real_idx == self.pal_sel
            hov = rect.collidepoint(mx, my)
            pygame.draw.rect(self.screen, ACCENT_DIM if sel else (BTN_HOVER if hov else PANEL_BG),
                             rect, border_radius=8)
            pygame.draw.rect(self.screen, ACCENT if sel else BORDER, rect, 2 if sel else 1,
                             border_radius=8)
            self._draw_thumb(name, pygame.Rect(rect.x + 4, rect.y + 4, cw - 8, THUMB))
            label = self._fit_text(self.pretty(name), self.f["caption"], cw - 10)
            ui.text(self.screen, label, (rect.centerx, rect.bottom - 15), self.f["caption"],
                    C0 if sel else TEXT, center=True)
        rows = (len(fp) + LIB_COLS - 1) // LIB_COLS
        y += rows * (ch + gap)
        if not fp:
            ui.text(self.screen, "No match", (bx, y + 4), self.font_s, TEXT_DIM)
            y += 28
        return y + 16

    def draw_transform_panel(self, px, y):
        f = self.furniture[self.selected]
        mx, my = pygame.mouse.get_pos()
        bx = px + 20
        card = pygame.Rect(bx - 8, y - 6, PANEL_W - 24, 10)       # height fixed below
        top = y
        y += 8
        ui.tracked(self.screen, "Transform", (bx, y), self.f["caption"], ACCENT)
        y += 20
        ui.text(self.screen, f["asset"], (bx, y), self.f["body"], C0)
        y += 28

        self.field_rects = {}
        for name, label in (("x", "X  m"), ("y", "Y  m"), ("yaw", "Yaw  deg")):
            y = self._draw_field_row(px, y, name, label, f.get(name, 0.0), mx, my)
        y += 6

        # --- SHAPE ---
        shape = f.get("shape", "bbox")
        ui.tracked(self.screen, "Shape", (bx, y), self.f["caption"], ACCENT)
        y += 20
        bw = (PANEL_W - 40 - 2 * 6) // 3
        for k, (skey, slabel) in enumerate((("bbox", "BBox"), ("sphere", "Sphere"), ("mesh", "Mesh"))):
            rect = pygame.Rect(bx + k * (bw + 6), y, bw, 30)
            self._draw_shape_button(rect, skey, slabel, shape, mx, my)
        y += 40
        if shape == "bbox":
            y = self._draw_field_row(px, y, "w", "W  m", f.get("w", 0.8), mx, my)
            y = self._draw_field_row(px, y, "h", "H  m", f.get("h", 0.8), mx, my)
        elif shape == "sphere":
            y = self._draw_field_row(px, y, "r", "R  m", f.get("r", 0.4), mx, my)
        else:  # mesh
            ui.text(self.screen, "Real footprint from the top-down capture", (bx, y + 2),
                    self.font_s, TEXT_DIM)
            y += 26
        y += 6

        bw2 = (PANEL_W - 40 - 8) // 2
        dup_rect = pygame.Rect(bx, y, bw2, 32)
        del_rect = pygame.Rect(bx + bw2 + 8, y, bw2, 32)
        self._draw_button(dup_rect, "tf_dup", "Duplicate", mx, my)
        self._draw_button(del_rect, "tf_del", "Delete", mx, my, danger=True)
        y += 44
        # gold hairline frame around the inspector
        card.h = y - top - 2
        pygame.draw.rect(self.screen, ACCENT_DIM, card, 1, border_radius=10)
        return y + 12

    def _draw_shape_button(self, rect, skey, slabel, cur_shape, mx, my):
        ui.button(self.screen, rect, slabel, self.f["button"], active=(skey == cur_shape),
                  hover=rect.collidepoint(mx, my), align="center")
        self.buttons.append((rect, "shape_" + skey, slabel))

    def _draw_field_row(self, px, y, name, label, value, mx, my):
        row_h = 30
        lbl_w = 70
        step_w = 30
        gap = 6
        bx = px + 20
        ui.text(self.screen, label, (bx, y + 7), self.font_s, TEXT_DIM)
        minus_rect = pygame.Rect(bx + lbl_w, y, step_w, row_h)
        box_w = (PANEL_W - 40) - lbl_w - 2 * step_w - 2 * gap
        box_rect = pygame.Rect(minus_rect.right + gap, y, box_w, row_h)
        plus_rect = pygame.Rect(box_rect.right + gap, y, step_w, row_h)

        self._draw_button(minus_rect, "step%s-" % name, "-", mx, my, center=True)
        self._draw_button(plus_rect, "step%s+" % name, "+", mx, my, center=True)

        active = (self.active_field == name)
        if active:
            blink = (pygame.time.get_ticks() // 500) % 2 == 0
            txt = self.field_buffer + ("|" if blink else "")
        else:
            txt = ("%d" % int(round(value))) if name == "yaw" else ("%.2f" % value)
        ui.field(self.screen, box_rect, txt, self.f["mono"], active=active)
        self.field_rects[name] = box_rect
        return y + row_h + 8

    def _draw_button(self, rect, key, label, mx, my, danger=False, center=False):
        tool_of = {"floor": "floor", "wall": "wall", "furni": "furniture", "style": "style",
                   "robot": "robot"}
        active = (tool_of.get(key) == self.tool or key == "et_%d" % self.edge_type
                  or key == "st_" + self.paint_style
                  or key == "rb_" + (self.robot.get("model") or robots.DEFAULT_ROBOT)
                  or key == "snap_%g" % self.snap_step
                  or (key == "magnet" and self.wall_magnet)
                  or (key == "overlap" and self.no_overlap))
        active = active and key not in ("floor", "wall", "furni", "style", "robot")
        ui.button(self.screen, rect, label, self.f["button"], active=active and not danger,
                  hover=rect.collidepoint(mx, my), danger=danger,
                  align="center" if center else "left")
        self.buttons.append((rect, key, label))

    def draw_status(self):
        y = self.win_h - STATUS_H
        pygame.draw.rect(self.screen, PANEL_BG, (0, y, self.win_w, STATUS_H))
        pygame.draw.line(self.screen, BORDER, (0, y), (self.win_w, y))
        nxt = os.path.basename(sb.next_scene_path())
        label = self.tool.upper()
        bw = ui.pill_width(label, self.f["caption"], pad=12)
        badge = pygame.Rect(16, y + (STATUS_H - 24) // 2, bw, 24)
        ui.pill(self.screen, badge, label, self.f["caption"], active=True)
        ui.text(self.screen, self.msg, (badge.right + 14, y + 7), self.f["body"], C0)
        info = "Grid %d x %d   ·   %d floor   ·   %d lights   ·   %d props   ·   %s   ·   %d%%   ·   %s" % (
            self.nx, self.ny,
            len(self.cells), sum(1 for v in self.cells.values() if v == 2),
            len(self.furniture), self.place_shape, int(self.zoom * 100), nxt)
        ui.text(self.screen, info, (badge.right + 14, y + 27), self.f["subtitle"], TEXT_DIM)

    # ---- context menu ----
    def _ctx_menu_geometry(self):
        if not self.ctx_menu:
            return None
        mx, my = self.ctx_menu["pos"]
        item_w, item_h = 170, 32
        n = len(self.ctx_menu["items"])
        x0 = min(mx, self.win_w - item_w - 8)
        y0 = min(my, self.win_h - n * item_h - 8)
        return x0, y0, item_w, item_h

    def _ctx_item_rect(self, i):
        geo = self._ctx_menu_geometry()
        if not geo:
            return pygame.Rect(0, 0, 0, 0)
        x0, y0, w, h = geo
        return pygame.Rect(x0, y0 + i * h, w, h)

    def draw_ctx_menu(self):
        if not self.ctx_menu:
            return
        x0, y0, w, h = self._ctx_menu_geometry()
        n = len(self.ctx_menu["items"])
        ui.card(self.screen, pygame.Rect(x0 - 6, y0 - 6, w + 12, n * h + 12), radius=10)
        mx, my = pygame.mouse.get_pos()
        for i, (key, label) in enumerate(self.ctx_menu["items"]):
            rect = self._ctx_item_rect(i)
            if rect.collidepoint(mx, my):
                pygame.draw.rect(self.screen, BTN_HOVER, rect, border_radius=6)
            ui.text(self.screen, label, (rect.x + 12, rect.y + 7), self.f["button"],
                    DANGER if key == "delete" else TEXT)

    # ---- loop ----
    def run(self):
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.VIDEORESIZE:
                    self.on_resize(ev.w, ev.h)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button in (1, 2, 3):
                        self.on_mouse_down(ev.pos[0], ev.pos[1], ev.button)
                    elif ev.button == 4:
                        self.on_wheel(1, pygame.key.get_mods() & pygame.KMOD_CTRL)
                    elif ev.button == 5:
                        self.on_wheel(-1, pygame.key.get_mods() & pygame.KMOD_CTRL)
                elif ev.type == pygame.MOUSEBUTTONUP:
                    if ev.button in (1, 2, 3):
                        self.on_mouse_up(ev.pos[0], ev.pos[1], ev.button)
                elif ev.type == pygame.MOUSEMOTION:
                    self.on_mouse_motion(ev.pos[0], ev.pos[1])
                elif ev.type == pygame.MOUSEWHEEL:
                    self.on_wheel(ev.y, pygame.key.get_mods() & pygame.KMOD_CTRL)
                elif ev.type == pygame.KEYDOWN:
                    self.on_key(ev)
            self.draw()
            self.clock.tick(60)
        pygame.quit()


if __name__ == "__main__":
    Editor().run()
