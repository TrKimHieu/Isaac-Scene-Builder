"""
scene_editor.py - Grid GUI (pygame) to design a map -> generate sceneX.usd + BEV.

Usage:
    python src/scene_editor.py

3 tools:
  FLOOR (1) - Click near a CELL CENTER: empty -> floor -> floor+light -> empty.
              DRAG to fill a rectangular floor area. Right-click removes a cell.
  WALL  (2) - Click near a CELL EDGE: cycles none -> wall -> door -> window -> glass ->
              opening. DRAG along a row/column paints the EDGE TYPE chosen in the panel.
              O over a door toggles it open/closed, P flips its swing side.
              Right-click clears an edge.
  STYLE (4) - Paint a room style (office / hospital / warehouse / home) on floor cells:
              click or DRAG a rectangle; pick the style in the panel. Walls take the style
              of the room each face looks into.
  ROBOT (5) - Pick the robot model in the panel (JetAuto Pro, JetBot, TurtleBot 3/4 -
              data/robots); its footprint is drawn to scale at the spawn.
              Click = add a waypoint, Shift+click = robot spawn, wheel = spawn heading,
              right-click = remove the nearest waypoint / spawn. Exported with the BEV as
              <stem>_nav.yaml + follow_waypoints.py (ROS 2 Nav2) and as USD markers.
  FURNITURE (3) - Pick a prop in the palette, click empty space to place (auto-selected).
              Click a placed prop to SELECT it; HOLD left + drag to MOVE it.
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

from config import (PROJECT_ROOT, MAPS_DIR, CELL, SNAP as _SNAP, FURNITURE_CATEGORIES,
                    EDGE_NAMES, EDGE_CYCLE, EDGE_WALL, EDGE_DOOR, EDGE_WINDOW, EDGE_GLASS,
                    EDGE_OPENING, STYLES, DEFAULT_STYLE, STYLE_COLORS, DOOR_DEFAULT,
                    WINDOW_COL, GLASS_COL, ROBOT_COL, SPAWN_COL, PLAN_BG, BORDER, ON_ACTIVE)
import ui_kit as ui
import architecture as arch
import robots
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
             "savemap", "load")
PAD = 34
STATUS_H = 52
EDGE_HIT = 0.24          # edge-snap threshold (cell fraction)


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

        self.nx, self.ny = 10, 8
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
        self.edge_type = EDGE_WALL          # what a wall-tool drag paints
        self.paint_style = "hospital"       # what the style tool paints
        self.robot = {"model": robots.DEFAULT_ROBOT}   # + "spawn": {x,y,yaw}, "waypoints"
        self.place_shape = "bbox"   # default shape when placing a new prop
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
        self.base_cs = max(14, int(min(area_w / self.nx, area_h / self.ny)))
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

    def cycle_edge(self, kind, i, j):
        d = self.vedges if kind == "vedge" else self.hedges
        maxi = self.nx if kind == "vedge" else self.nx - 1
        maxj = self.ny - 1 if kind == "vedge" else self.ny
        if not (0 <= i <= maxi and 0 <= j <= maxj):
            return
        self._snapshot()
        cur = d.get((i, j), 0)
        s = EDGE_CYCLE[(EDGE_CYCLE.index(cur) + 1) % len(EDGE_CYCLE)] if cur in EDGE_CYCLE else 0
        if s == 0:
            d.pop((i, j), None)
        else:
            d[(i, j)] = s
        self.msg = "Edge: %s" % EDGE_NAMES.get(s, "none")

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

    def flip_door(self, mx, my):
        """Turn the door under the cursor 180 deg (it then swings into the other room)."""
        kind, i, j = self.nearest_edge(mx, my)
        d = self.vedges if kind == "vedge" else self.hedges
        if d.get((i, j)) != EDGE_DOOR:
            self.msg = "No door here."
            return
        self._snapshot()
        key = arch.edge_key(kind, i, j)
        if self.door_flip.pop(key, None) is None:
            self.door_flip[key] = True
        self.msg = "Door swing flipped."

    def toggle_door(self, mx, my):
        """Open <-> closed for the door edge under the cursor."""
        kind, i, j = self.nearest_edge(mx, my)
        d = self.vedges if kind == "vedge" else self.hedges
        if d.get((i, j)) != EDGE_DOOR:
            self.msg = "No door here."
            return
        self._snapshot()
        key = arch.edge_key(kind, i, j)
        is_open = arch.door_is_open(self.map_data_light(), kind[0], i, j)
        self.door_state[key] = "closed" if is_open else "open"
        self.msg = "Door %s" % self.door_state[key]

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

    def place_furniture(self, mx, my):
        if not self.palette:
            self.msg = "No furniture prop available."
            return
        self._snapshot()
        x, y = self.screen_to_usd(mx, my)
        x = round(x / SNAP) * SNAP
        y = round(y / SNAP) * SNAP
        name = self.palette[self.pal_sel][0]
        sh = bev.default_shape(name)   # measured w/h/r; shape from current placement mode
        self.furniture.append({"asset": name, "x": x, "y": y, "yaw": self.cur_yaw,
                               "shape": self.place_shape,
                               "w": sh["w"], "h": sh["h"], "r": sh["r"]})
        self.msg = "Placed %s (%s) @ (%.1f, %.1f)" % (name, self.place_shape, x, y)

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
        rad_map = dict(self.palette)
        best_idx, best_d = None, 1e9
        for idx, f in enumerate(self.furniture):
            d2 = (f["x"] - x) ** 2 + (f["y"] - y) ** 2
            rad = rad_map.get(f["asset"], 0.4) * 1.3
            if d2 <= rad * rad and d2 < best_d:
                best_d, best_idx = d2, idx
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
        clone["x"] = src["x"] + SNAP
        self.furniture.append(clone)
        self.select_furniture(len(self.furniture) - 1)
        self.msg = "Duplicated %s" % clone["asset"]

    def rotate_furniture(self, idx, delta):
        self._snapshot()
        f = self.furniture[idx]
        f["yaw"] = (f["yaw"] + delta) % 360
        self.msg = "Xoay %s -> %d deg" % (f["asset"], int(f["yaw"]))

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
        step = 15.0 if name == "yaw" else SNAP
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
            "robot": {"model": self.robot.get("model") or robots.DEFAULT_ROBOT,
                      "spawn": dict(self.robot["spawn"]) if self.robot.get("spawn") else None,
                      "waypoints": [list(w) for w in self.robot.get("waypoints", [])]},
        }

    def load_map_data(self, m):
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
        self.nx = max(2, min(40, self.nx + dnx))
        self.ny = max(2, min(40, self.ny + dny))
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
                else:
                    self.place_furniture(mx, my)
                    self.select_furniture(len(self.furniture) - 1)
                    self.move_drag = self.selected
            elif button == 3:
                self.open_ctx_menu(mx, my)
            return
        # FLOOR / WALL: left starts a drag; right clears a single cell/edge
        if self.tool == "robot":
            x, y = self.screen_to_usd(mx, my)
            x, y = round(x / SNAP) * SNAP, round(y / SNAP) * SNAP
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
            x, y = self.screen_to_usd(mx, my)
            f = self.furniture[self.move_drag]
            f["x"] = round(x / SNAP) * SNAP
            f["y"] = round(y / SNAP) * SNAP
            self.msg = "Moving %s @ (%.1f, %.1f)" % (f["asset"], f["x"], f["y"])
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
                self.cycle_edge(kind, i0, j0)
            else:
                self.draw_wall_run((kind, i0, j0), mx, my)

    def panel_click(self, mx, my, button):
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
        if hasattr(self, '_pal_search_rect') and self._pal_search_rect.collidepoint(mx, my):
            self._pal_search_active = True
            return
        else:
            if getattr(self, '_pal_search_active', False):
                self._pal_search_active = False

    def do_action(self, key):
        if key == "floor": self.switch_tool("floor")
        elif key == "wall": self.switch_tool("wall")
        elif key == "furni": self.switch_tool("furniture")
        elif key == "style": self.switch_tool("style")
        elif key == "robot": self.switch_tool("robot")
        elif key.startswith("et_"):
            self.edge_type = int(key[3:])
            self.msg = "Wall drag paints: %s" % EDGE_NAMES[self.edge_type]
        elif key.startswith("rb_"):
            self._snapshot()
            self.robot["model"] = key[3:]
            spec = robots.get(key[3:])
            self.msg = "Robot: %s  (r %.2f m, h %.2f m)" % (spec["name"], spec["r_circ"], spec["height"])
        elif key.startswith("st_"):
            self.paint_style = key[3:]
            self.msg = "Style brush: %s" % STYLES[self.paint_style]["label"]
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
            self.toggle_door(*pygame.mouse.get_pos())
        elif k == pygame.K_p and self.tool == "wall":
            self.flip_door(*pygame.mouse.get_pos())
        elif k == pygame.K_2: self.switch_tool("wall")
        elif k in (pygame.K_3, pygame.K_f): self.switch_tool("furniture")
        elif k == pygame.K_TAB:
            order = ["floor", "wall", "furniture"]
            self.switch_tool(order[(order.index(self.tool) + 1) % 3])
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
                rad = max(3, int(self.cs) // 11)
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
        for i in range(self.nx + 1):
            x = self.ox + i * self.cs
            pygame.draw.line(self.screen, GRID_LINE, (x, self.oy), (x, self.oy + self.ny * self.cs))
        for j in range(self.ny + 1):
            y = self.oy + j * self.cs
            pygame.draw.line(self.screen, GRID_LINE, (self.ox, y), (self.ox + self.nx * self.cs, y))
        # edges
        for (i, j), s in self.vedges.items():
            self.draw_edge("vedge", i, j, s)
        for (i, j), s in self.hedges.items():
            self.draw_edge("hedge", i, j, s)
        # hover edge
        if hover and hover[0] in ("vedge", "hedge"):
            self.draw_edge(hover[0], hover[1], hover[2], -1)
        # furniture
        for idx, f in enumerate(self.furniture):
            self.draw_furni(f, selected=(idx == self.selected))
        self.draw_robot()

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
        w = max(3, int(self.cs) // 11)
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
        a = (p0[0] * 0.65 + p1[0] * 0.35, p0[1] * 0.65 + p1[1] * 0.35)
        b = (p0[0] * 0.35 + p1[0] * 0.65, p0[1] * 0.35 + p1[1] * 0.65)
        if s in (EDGE_DOOR, EDGE_OPENING):
            # door / opening: gap in the middle (0.94 m clear)
            pygame.draw.line(self.screen, WALL_COL, p0, a, w)
            pygame.draw.line(self.screen, WALL_COL, b, p1, w)
            if s == EDGE_DOOR:
                if arch.door_is_open(self.map_data_light(), kind[0], i, j):
                    # leaf swung open from the hinge into the +X (vedge) / -Y (hedge) room
                    n = (1, 0) if kind == "vedge" else (0, -1)
                    if arch.door_flipped(self.map_data_light(), kind[0], i, j):
                        n, b = (-n[0], -n[1]), a      # turned 180: other room, other jamb
                    L = 0.94 / sb.CELL * self.cs
                    pygame.draw.line(self.screen, DOOR_COL, b,
                                     (b[0] + n[0] * L, b[1] + n[1] * L), max(2, w // 2))
                else:
                    pygame.draw.line(self.screen, DOOR_COL, a, b, max(2, w // 2))
        elif s == EDGE_WINDOW:
            pygame.draw.line(self.screen, WALL_COL, p0, p1, w)
            pygame.draw.line(self.screen, WINDOW_COL, p0, p1, max(2, w // 2))
        elif s == EDGE_GLASS:
            pygame.draw.line(self.screen, GLASS_COL, p0, p1, max(2, w // 3))
        else:
            pygame.draw.line(self.screen, WALL_COL, p0, p1, w)

    def map_data_light(self):
        """Just what architecture.door_is_open() needs (cheap, called per drawn door)."""
        return {"door_default": self.door_default, "door_state": self.door_state,
                "door_flip": self.door_flip}

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

    def _btn_groups(self):
        groups = [
            ("Tools", [("floor", "Floor	1"), ("wall", "Wall	2"), ("furni", "Furniture	3"),
                       ("style", "Style	4"), ("robot", "Robot	5")]),
            ("Edit", [("undo", "Undo	Ctrl+Z"), ("redo", "Redo	Ctrl+Y")]),
            ("Grid", [("walls", "Auto-walls	W"), ("clear", "Clear	C"),
                      ("gx-", "Width  −"), ("gx+", "Width  +"),
                      ("gy-", "Depth  −"), ("gy+", "Depth  +")]),
            ("File", [("usd", "Save USD	S"), ("export", "Export BEV	B"),
                     ("savemap", "Save map	Ctrl+S"), ("load", "Load map	L")]),
        ]
        if self.tool == "wall":
            groups.insert(1, ("Edge type", [("et_%d" % e, EDGE_NAMES[e])
                                                   for e in EDGE_CYCLE if e] +
                              [("door_def", "Doors " + self.door_default + "	O / P")]))
        elif self.tool == "style":
            groups.insert(1, ("Room style", [("st_" + k, v["label"]) for k, v in STYLES.items()]))
        elif self.tool == "robot" and robots.load_robots():
            groups.insert(1, ("Robot model", [("rb_" + k, robots.label(k))
                                              for k in robots.load_robots()]))
        return groups

    def draw_panel(self):
        px = self.win_w - PANEL_W
        pygame.draw.rect(self.screen, PANEL_BG, (px, 0, PANEL_W, self.win_h))
        pygame.draw.line(self.screen, BORDER, (px, 0), (px, self.win_h))
        mx, my = pygame.mouse.get_pos()
        bx = px + 20
        bw_full = PANEL_W - 40
        self.buttons = []
        self._pal_rects = []

        avail_h = self.win_h - STATUS_H
        # clamp before drawing (use previous frame limit) to avoid jitter on resize
        self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll))
        # clip the panel area (excluding status bar) so scrolled content stays inside
        self.screen.set_clip(pygame.Rect(px + 1, 0, PANEL_W - 1, avail_h))
        y = 22 - self.panel_scroll

        ui.text(self.screen, "Scene Editor", (bx, y), self.f["title"], C0)
        y += 26
        ui.text(self.screen, "Isaac Scene Builder", (bx, y), self.f["subtitle"], TEXT_DIM)
        y += 30

        for title, defs in self._btn_groups():
            ui.tracked(self.screen, title, (bx, y), self.f["caption"])
            y += 22
            i = 0
            col = 0                      # column of the next half-width button
            while i < len(defs):
                key, label = defs[i]
                small = key in HALF_KEYS or key[:3] in ("et_", "st_", "rb_")
                if small:
                    bw = (bw_full - 8) // 2
                    rect = pygame.Rect(bx + col * (bw + 8), y, bw, 32)
                    self._draw_button(rect, key, label, mx, my)
                    if col == 1:
                        y += 40
                    col = 1 - col
                    i += 1
                    continue
                if col == 1:                 # finish a half-filled row first
                    y += 40
                    col = 0
                rect = pygame.Rect(bx, y, bw_full, 34)
                self._draw_button(rect, key, label, mx, my)
                y += 42
                i += 1
            if col == 1:
                y += 40
            if title == "Robot model":
                y = self.draw_robot_card(bx, y, bw_full)
            y += 14

        # transform inspector (only when a furniture is selected)
        if self.selected is not None and self.tool == "furniture" and 0 <= self.selected < len(self.furniture):
            if self._scroll_to_transform:
                # bring the TRANSFORM block near the top of view (applied next frame)
                tf_top_abs = y + self.panel_scroll
                self.panel_scroll = max(0, tf_top_abs - 56)
                self._scroll_to_transform = False
            y = self.draw_transform_panel(px, y)
        else:
            self.field_rects = {}
            self._scroll_to_transform = False

        # palette (furniture list) - filtered by category + search
        self._pal_cat_rects = []
        ui.tracked(self.screen, "Furniture", (bx, y), self.f["caption"])
        y += 22

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

        # filtered items
        fp = self.filtered_palette()
        self._pal_rects = []
        for filt_idx, (name, _rad) in enumerate(fp):
            real_idx = self.palette.index((name, _rad))
            rect = pygame.Rect(bx - 6, y, bw_full + 12, 26)
            sel = (real_idx == self.pal_sel and self.tool == "furniture")
            if sel:
                ui.selected_row(self.screen, rect)
            elif rect.collidepoint(mx, my):
                pygame.draw.rect(self.screen, BTN_HOVER, rect, border_radius=6)
            ui.text(self.screen, name, (rect.x + 12, rect.y + 4), self.font_s,
                    C0 if sel else TEXT)
            self._pal_rects.append((real_idx, rect))
            y += 28
        if not fp:
            ui.text(self.screen, "No match", (bx, y + 4), self.font_s, TEXT_DIM)
            y += 28
        y += 10

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
                  or key == "rb_" + (self.robot.get("model") or robots.DEFAULT_ROBOT))
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
