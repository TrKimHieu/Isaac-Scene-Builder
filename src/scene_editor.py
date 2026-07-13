"""
scene_editor.py - GUI luoi (pygame) de thiet ke ban do -> sinh sceneX.usd + BEV.

Cach dung:
    python src/scene_editor.py

3 cong cu:
  FLOOR (1) - Click gan TAM o: rong -> san -> san+den -> rong.
              KEO-THA de to ca vung san hinh chu nhat. Phai-click xoa o.
  WALL  (2) - Click gan CANH o: none -> tuong -> tuong-cua -> none.
              KEO-THA doc theo hang/cot de ve doan tuong dai. Phai-click xoa canh.
  FURNITURE (3) - Chon prop o palette, click o trong de dat (tu dong duoc chon).
              Click vat da dat de CHON; GIU trai + keo de DI CHUYEN (keo-tha).
              Panel TRANSFORM: sua X/Y/Yaw va chon SHAPE (BBox / Sphere / Mesh) -
              chon dang nao thi cac prop dat sau se auto dung dang do. Phai-click
              mo menu (Chon/Nhan ban/Xoay 90/Xoa). Lan chuot = xoay 5 do/nac.
Tam nhin:
  Ctrl + lan chuot = ZOOM (quanh con tro) | GIU nut con lan + keo = PAN (di tam nhin)
  Home / 0 = reset tam nhin ve 100%%
Phim tat:
  1 floor | 2 wall | 3/F furniture | Tab doi cong cu | W auto-walls | C clear
  S save USD (sceneX.usd) | Ctrl+S save map JSON | L load map moi nhat
  B  export BEV (CSV + SVG + PNG/PGM) vao output/bev/
  + / -  doi kich thuoc luoi | R xoay noi that 5 do (dang chon hoac sap dat)
  F11  bat/tat toan man hinh | keo canh cua so de doi kich thuoc
  Esc  thoat toan man hinh -> dong menu -> bo chon -> ve floor
"""
import os
import json
import glob
import math

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

import scene_builder as sb
import bev_export as bev

from config import (PROJECT_ROOT, MAPS_DIR, CELL, SNAP as _SNAP, FURNITURE_CATEGORIES)
from config import (C0, C1, C2, C3, C4, MESH_MARK, BG, GRID_LINE, FLOOR_COL,
                    FLOOR_HOVER, LIGHT_COL, WALL_COL, DOOR_COL, HOVER_EDGE,
                    PANEL_BG, BTN, BTN_HOVER, BTN_ACTIVE, TEXT, TEXT_DIM,
                    FURNI_COL, FURNI_SEL, ACCENT, ACCENT_DIM, PANEL_ROW_ALT,
                    FIELD_BG, FIELD_ACTIVE_BG, DANGER, SECTION_LINE)
from utils import bbox_corners, load_prop_shapes

SNAP = _SNAP

WIN_W, WIN_H = 1240, 820
MIN_W, MIN_H = 900, 680
PANEL_W = 340
PAD = 20
STATUS_H = 46
EDGE_HIT = 0.24          # nguong bat canh (ti le o)


class Editor:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Isaac Scene Builder")
        self.win_w, self.win_h = WIN_W, WIN_H
        self.windowed_size = (WIN_W, WIN_H)
        self.fullscreen = False
        self.screen = pygame.display.set_mode((self.win_w, self.win_h), pygame.RESIZABLE)
        self.font = pygame.font.SysFont("consolas", 16)
        self.font_s = pygame.font.SysFont("consolas", 13)
        self.font_b = pygame.font.SysFont("consolas", 18, bold=True)
        self.clock = pygame.time.Clock()

        self.nx, self.ny = 10, 8
        self.cells = {}        # (i,j) -> 1|2
        self.vedges = {}       # (i,j) -> 1|2
        self.hedges = {}       # (i,j) -> 1|2
        self.furniture = []    # {asset,x,y,yaw,shape,w,h,r}

        self.tool = "floor"    # "floor" | "wall" | "furniture"
        self.palette = sb.available_furniture()
        self.pal_sel = 0
        self.structure = {}    # override prop cau truc: {"wall":..,"floor":..}
        self.place_shape = "bbox"   # dang shape mac dinh khi dat prop moi
        self.cur_yaw = 0.0
        self.msg = "San sang. Cong cu FLOOR: click / keo-tha de to san."
        self.buttons = []       # (rect, key, label)

        self.panel_scroll = 0        # cuon toan bo panel ben phai
        self._panel_max_scroll = 0
        self._pal_rects = []         # [(idx, Rect)] cho hit-test palette
        self._scroll_to_transform = False
        self._pal_filter = ""        # search filter cho furniture palette
        self._pal_cat = "Tat ca"     # category filter
        self._pal_search_active = False  # dang nhap search
        self._pal_cat_rects = []     # [(cat_name, Rect)] cho hit-test category tabs
        self._pal_search_rect = None # Rect cua search field

        self.selected = None        # index vao self.furniture, hoac None
        self.ctx_menu = None         # {"pos","target","items"}
        self.active_field = None     # "x" | "y" | "yaw" | "w" | "h" | "r" | None
        self.field_buffer = ""
        self.field_rects = {}        # ten field -> Rect (cho hit-test click)

        self.drag_start = None       # ("cell",i,j) | ("edge",kind,i,j)
        self.drag_cur = None         # (mx,my) hien tai khi keo
        self._mesh_cache = {}        # asset -> (mask_surface, w_m, h_m) | None

        # zoom / pan (tam nhin)
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.base_cs = 20
        self.panning = False         # dang keo tam nhin bang nut con lan
        self.pan_last = None
        self.move_drag = None        # index furniture dang keo-tha di chuyen

        # undo / redo
        self._undo_stack = []
        self._redo_stack = []
        self._max_undo = 50

        # named save
        self.current_map_name = None  # ten file dang edit (None = chua luu)

        self._recalc_layout()

    # ---- undo / redo ----
    def _snapshot(self):
        """Luu state hien tai vao undo stack."""
        self._undo_stack.append(self.map_data())
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            self.msg = "Khong co buoc nao de hoan tac."
            return
        self._redo_stack.append(self.map_data())
        self.load_map_data(self._undo_stack.pop())
        self.msg = "Da hoan tac."

    def redo(self):
        if not self._redo_stack:
            self.msg = "Khong co buoc nao de phuc hoi."
            return
        self._undo_stack.append(self.map_data())
        self.load_map_data(self._redo_stack.pop())
        self.msg = "Da phuc hoi."

    # ---- furniture palette filter ----
    def filtered_palette(self):
        """Tra ve danh sach palette da loc theo category + search text."""
        cats = FURNITURE_CATEGORIES
        if self._pal_cat != "Tat ca" and self._pal_cat in cats:
            allowed = set(cats[self._pal_cat])
            items = [(n, r) for (n, r) in self.palette if n in allowed]
        else:
            items = list(self.palette)
        if self._pal_filter:
            q = self._pal_filter.lower()
            items = [(n, r) for (n, r) in items if q in n.lower()]
        return items

    # ---- layout / view ----
    def _recalc_layout(self):
        area_w = self.win_w - PANEL_W - 2 * PAD
        area_h = self.win_h - 2 * PAD - STATUS_H
        self.base_cs = max(14, int(min(area_w / self.nx, area_h / self.ny)))
        self._apply_view()

    def _apply_view(self):
        """Cap nhat cs/ox/oy hieu dung tu base_cs + zoom + pan."""
        self.cs = max(4.0, self.base_cs * self.zoom)
        self.ox = PAD + self.pan_x
        self.oy = PAD + self.pan_y

    def zoom_at(self, mx, my, factor):
        """Zoom quanh diem (mx,my): giu diem the gioi duoi con tro co dinh."""
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
        self.msg = "Da reset tam nhin (zoom 100%%)."

    def on_resize(self, w, h):
        """Nguoi dung keo gian cua so -> cap nhat kich thuoc & bo cuc."""
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
        # khoang cach toi 4 canh
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
        """Luon tra ('cell', i, j) cho cong cu FLOOR."""
        fx, fy = self.screen_to_cellfrac(mx, my)
        return ("cell", int(fx), int(fy))

    def nearest_edge(self, mx, my):
        """Luon tra canh gan nhat ('vedge'|'hedge', i, j) cho cong cu WALL."""
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
        s = (d.get((i, j), 0) + 1) % 3
        if s == 0:
            d.pop((i, j), None)
        else:
            d[(i, j)] = s

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
        """To san (state 1) cho toan bo o trong khung; khong ha cap den (state 2)."""
        self._snapshot()
        lo_i, hi_i = sorted((i0, i1))
        lo_j, hi_j = sorted((j0, j1))
        n = 0
        for i in range(max(0, lo_i), min(self.nx, hi_i + 1)):
            for j in range(max(0, lo_j), min(self.ny, hi_j + 1)):
                if self.cells.get((i, j), 0) == 0:
                    self.cells[(i, j)] = 1
                    n += 1
        self.msg = "To san: them %d o." % n

    def draw_wall_run(self, start_edge, mx, my):
        """Ve doan tuong (state 1) tu canh bat dau toi vi tri chuot theo truc chinh."""
        self._snapshot()
        kind, i0, j0 = start_edge
        end = self.nearest_edge(mx, my)
        d = self.vedges if kind == "vedge" else self.hedges
        n = 0
        if kind == "vedge":
            # cot co dinh i0, chay theo j
            j1 = end[2] if end[0] == "vedge" else j0
            for j in range(min(j0, j1), max(j0, j1) + 1):
                if 0 <= i0 <= self.nx and 0 <= j <= self.ny - 1 and d.get((i0, j), 0) == 0:
                    d[(i0, j)] = 1
                    n += 1
        else:
            # hang co dinh j0, chay theo i
            i1 = end[1] if end[0] == "hedge" else i0
            for i in range(min(i0, i1), max(i0, i1) + 1):
                if 0 <= i <= self.nx - 1 and 0 <= j0 <= self.ny and d.get((i, j0), 0) == 0:
                    d[(i, j0)] = 1
                    n += 1
        self.msg = "Ve tuong: them %d doan." % n

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
        self.msg = "Auto-walls: them %d doan tuong bao." % added

    def place_furniture(self, mx, my):
        if not self.palette:
            self.msg = "Khong co prop noi that."
            return
        self._snapshot()
        x, y = self.screen_to_usd(mx, my)
        x = round(x / SNAP) * SNAP
        y = round(y / SNAP) * SNAP
        name = self.palette[self.pal_sel][0]
        sh = bev.default_shape(name)   # w/h/r do duoc; shape theo che do dat hien tai
        self.furniture.append({"asset": name, "x": x, "y": y, "yaw": self.cur_yaw,
                               "shape": self.place_shape,
                               "w": sh["w"], "h": sh["h"], "r": sh["r"]})
        self.msg = "Dat %s (%s) @ (%.1f, %.1f)" % (name, self.place_shape, x, y)

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
            self.msg = "Da xoa %s" % best["asset"]

    def find_furniture_at(self, mx, my):
        """Tra ve index vat noi that gan (mx,my) nhat trong ban kinh footprint, hoac None."""
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
            self._scroll_to_transform = True   # tu cuon panel toi o TRANSFORM
            self.msg = "Da chon %s" % self.furniture[idx]["asset"]

    def switch_tool(self, t):
        self.tool = t
        self.panel_scroll = 0          # ve dau panel de thay cum nut cong cu

    def deselect(self):
        self.panel_scroll = 0
        self.selected = None
        self.active_field = None

    def open_ctx_menu(self, mx, my):
        idx = self.find_furniture_at(mx, my)
        if idx is not None:
            items = [("select", "Chon"), ("duplicate", "Nhan ban"),
                     ("rot90", "Xoay 90"), ("delete", "Xoa")]
        else:
            items = [("close", "Dong")]
        self.ctx_menu = {"pos": (mx, my), "target": idx, "items": items}

    def duplicate_furniture(self, idx):
        self._snapshot()
        src = self.furniture[idx]
        clone = dict(src)
        clone["x"] = src["x"] + SNAP
        self.furniture.append(clone)
        self.select_furniture(len(self.furniture) - 1)
        self.msg = "Da nhan ban %s" % clone["asset"]

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
        self.msg = "Da xoa %s" % f["asset"]

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
            return max(0.05, v)   # kich thuoc duong toi thieu
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
        # dat lam dang mac dinh khi dat prop moi
        self.place_shape = shape
        # neu dang chon 1 prop thi doi luon dang cua no
        if self.selected is not None:
            self.furniture[self.selected]["shape"] = shape
            self.active_field = None
        self.msg = "Dang dat: %s" % shape

    # ---- data model io ----
    def map_data(self):
        return {
            "grid": [self.nx, self.ny],
            "cells": {"%d,%d" % k: v for k, v in self.cells.items()},
            "vedges": {"%d,%d" % k: v for k, v in self.vedges.items()},
            "hedges": {"%d,%d" % k: v for k, v in self.hedges.items()},
            "furniture": [dict(f) for f in self.furniture],
            "structure": dict(self.structure),
        }

    def load_map_data(self, m):
        self.nx, self.ny = m["grid"]
        self.cells = sb._ikey(m.get("cells"))
        self.vedges = sb._ikey(m.get("vedges"))
        self.hedges = sb._ikey(m.get("hedges"))
        self.furniture = list(m.get("furniture", []))
        self.structure = dict(m.get("structure") or {})
        self.deselect()
        self.ctx_menu = None
        self._recalc_layout()

    def cycle_structure(self, key):
        """Xoay vong lua chon prop cau truc (wall/floor)."""
        choices = sb.STRUCTURE_CHOICES.get(key, [])
        if not choices:
            return
        cur = self.structure.get(key, choices[0])
        nxt = choices[(choices.index(cur) + 1) % len(choices)] if cur in choices else choices[0]
        self.structure[key] = nxt
        self.msg = "Cau truc %s -> %s" % (key, nxt)

    def save_map(self, name=None):
        """Luu map. name=None + chua co ten -> auto-increment. name co gia tri -> dat ten/overwrite."""
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
        self.msg = "Da luu ban do: %s" % filename

    def list_maps(self):
        """Tra ve danh sach map da luu, sap xep theo thoi gian moi nhat."""
        if not os.path.isdir(MAPS_DIR):
            return []
        files = sorted(glob.glob(os.path.join(MAPS_DIR, "*.json")), key=os.path.getmtime)
        return [os.path.basename(f) for f in files]

    def load_map_by_name(self, filename):
        """Load map theo ten cu the."""
        path = os.path.join(MAPS_DIR, filename)
        if not os.path.isfile(path):
            self.msg = "Khong thay ban do: %s" % filename
            return
        with open(path, encoding="utf-8") as fh:
            self.load_map_data(json.load(fh))
        self.current_map_name = filename
        self.msg = "Da mo: %s" % filename

    def load_latest_map(self):
        files = sorted(glob.glob(os.path.join(MAPS_DIR, "*.json")), key=os.path.getmtime)
        if not files:
            self.msg = "Khong co ban do da luu."
            return
        with open(files[-1], encoding="utf-8") as fh:
            self.load_map_data(json.load(fh))
        self.current_map_name = os.path.basename(files[-1])
        self.msg = "Da mo: %s" % self.current_map_name

    def validate_map(self):
        """Kiem tra ban do va tra ve danh sach canh bao (list of str)."""
        warnings = []
        if not self.cells:
            warnings.append("Khong co o san nao.")
        if not self.hedges and not self.vedges:
            warnings.append("Khong co tuong nao.")
        for fi, f in enumerate(self.furniture):
            name = f.get("asset", "?")
            x, y = f.get("x", 0), f.get("y", 0)
            if not (-2.0 <= x <= (self.nx + 2) * CELL and -2.0 <= y <= (self.ny + 2) * CELL):
                warnings.append("Noi that #%d (%s) nam ngoai luoi." % (fi + 1, name))
        # kiem tra trung lap
        pos_map = {}
        for fi, f in enumerate(self.furniture):
            key = (round(f.get("x", 0), 2), round(f.get("y", 0), 2))
            if key in pos_map:
                name = f.get("asset", "?")
                warnings.append("Noi that #%d (%s) trung vi tri voi #%d." % (fi + 1, name, pos_map[key] + 1))
            pos_map[key] = fi
        return warnings

    def save_usd(self):
        warnings = self.validate_map()
        if not self.cells:
            self.msg = "Chua co o san nao de xuat."
            return
        if warnings:
            self.msg = "Canh bao: " + " | ".join(warnings) + " — dang xuat..."
        out = sb.next_scene_path()
        try:
            st = sb.build_scene(self.map_data(), out)
        except Exception as e:
            self.msg = "Loi build: %s" % e
            return
        self.msg = "Xuat %s | san %d, den %d, tuong %d, cua %d, noi that %d" % (
            os.path.basename(out), st["floor"], st["light"], st["wall"], st["door"], st["furniture"])

    def export_bev(self):
        if not self.cells and not self.furniture:
            self.msg = "Chua co gi de xuat BEV."
            return
        warnings = self.validate_map()
        if warnings:
            self.msg = "Canh bao: " + " | ".join(warnings) + " — dang xuat BEV..."
        stem = os.path.splitext(os.path.basename(sb.next_scene_path()))[0]
        try:
            st = bev.export_scene(self.map_data(), stem=stem)
        except Exception as e:
            self.msg = "Loi export BEV: %s" % e
            return
        self.msg = "BEV -> output/bev/%s/ (csv,svg,png,pgm,yaml) | san %d, tuong %d, vat %d" % (
            stem, st["floor"], st["wall"], st["prop"])

    def clear(self):
        self.cells.clear(); self.vedges.clear(); self.hedges.clear(); self.furniture.clear()
        self.deselect()
        self.ctx_menu = None
        self.msg = "Da xoa toan bo ban do."

    def resize_grid(self, dnx, dny):
        self.nx = max(2, min(40, self.nx + dnx))
        self.ny = max(2, min(40, self.ny + dny))
        # bo phan tu ngoai luoi
        self.cells = {k: v for k, v in self.cells.items() if 0 <= k[0] < self.nx and 0 <= k[1] < self.ny}
        self.vedges = {k: v for k, v in self.vedges.items() if 0 <= k[0] <= self.nx and 0 <= k[1] < self.ny}
        self.hedges = {k: v for k, v in self.hedges.items() if 0 <= k[0] < self.nx and 0 <= k[1] <= self.ny}
        self._recalc_layout()

    # ---- input ----
    def on_mouse_down(self, mx, my, button):
        # nut con lan (button 2) -> keo tam nhin (pan) o bat ky dau
        if button == 2:
            self.panning = True
            self.pan_last = (mx, my)
            return
        # menu chuot phai dang mo -> uu tien xu ly, nuot moi click
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
        # click ra khoi panel -> chot field dang sua (neu co)
        self.commit_active_field()
        if not self.in_grid(mx, my):
            return
        if self.tool == "furniture":
            if button == 1:
                idx = self.find_furniture_at(mx, my)
                if idx is not None:
                    self.select_furniture(idx)
                    self._snapshot()                    # luu truoc khi keo
                    self.move_drag = idx          # giu trai + keo -> di chuyen
                else:
                    self.place_furniture(mx, my)
                    self.select_furniture(len(self.furniture) - 1)
                    self.move_drag = self.selected
            elif button == 3:
                self.open_ctx_menu(mx, my)
            return
        # FLOOR / WALL: nut trai bat dau keo; nut phai xoa don ngay
        if self.tool == "floor":
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
            self.msg = "Di chuyen %s @ (%.1f, %.1f)" % (f["asset"], f["x"], f["y"])
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
            if (i0, j0) == (i1, j1):
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
        # field o panel Transform
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
                self.msg = "Chon: %s" % self.palette[idx][0]
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
        # dang go so trong field cua panel Transform
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
        # dang nhap search filter
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
        # Ctrl + lan chuot -> zoom quanh con tro
        if ctrl and not over_panel:
            self.zoom_at(mx, my, 1.15 if dy > 0 else 1.0 / 1.15)
            return
        if over_panel:
            self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll - dy * 40))
        elif self.tool == "furniture":
            if self.selected is not None:
                self.rotate_furniture(self.selected, dy * 5)   # xoay 5 do moi nac
            else:
                self.cur_yaw = (self.cur_yaw + dy * 5) % 360

    # ---- draw ----
    def draw(self):
        self.screen.fill(BG)
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
            if self.tool == "floor":
                hover = self.hit_cell(mx, my)
            elif self.tool == "wall":
                hover = self.nearest_edge(mx, my)
        # cells
        for (i, j), s in self.cells.items():
            r = self.cell_rect(i, j)
            pygame.draw.rect(self.screen, FLOOR_COL, r)
            if s == 2:
                pygame.draw.circle(self.screen, LIGHT_COL, r.center, max(4, int(self.cs) // 6))
        # hover cell
        if hover and hover[0] == "cell" and 0 <= hover[1] < self.nx and 0 <= hover[2] < self.ny:
            if (hover[1], hover[2]) not in self.cells:
                r = self.cell_rect(hover[1], hover[2])
                pygame.draw.rect(self.screen, FLOOR_HOVER, r, 2)
        # preview keo-tha
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
        w = max(4, int(self.cs) // 8)
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
        col = DOOR_COL if s == 2 else WALL_COL
        if s == 2:
            # tuong co cua: chua khe o giua
            mxp = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            a = (p0[0] * 0.7 + p1[0] * 0.3, p0[1] * 0.7 + p1[1] * 0.3)
            b = (p0[0] * 0.3 + p1[0] * 0.7, p0[1] * 0.3 + p1[1] * 0.7)
            pygame.draw.line(self.screen, WALL_COL, p0, a, w)
            pygame.draw.line(self.screen, WALL_COL, b, p1, w)
            pygame.draw.circle(self.screen, DOOR_COL, (int(mxp[0]), int(mxp[1])), max(3, w))
        else:
            pygame.draw.line(self.screen, col, p0, p1, w)

    def _get_mesh_surface(self, asset):
        """Surface mask footprint tu mesh_shapes/<asset>.png (cache).

        Tra (mask_surface, w_m, h_m) - mask trang doi tuong / trong suot nen -
        hoac None neu chua co mesh. Mask da crop khit doi tuong.
        """
        if asset in self._mesh_cache:
            return self._mesh_cache[asset]
        result = None
        path = os.path.join(bev.MESH_DIR, asset + ".png")
        if os.path.isfile(path):
            try:
                from PIL import Image
                import numpy as np
                im = Image.open(path).convert("L")
                a = np.asarray(im)
                ys, xs = np.where(a < 128)          # object = pixel toi
                if len(xs) > 0:
                    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
                    obj = a[y0:y1, x0:x1] < 128
                    ch, cw = obj.shape
                    rgba = np.zeros((ch, cw, 4), dtype=np.uint8)
                    rgba[obj] = (255, 255, 255, 255)   # trang, se to mau khi ve
                    surf = pygame.image.frombuffer(rgba.tobytes(), (cw, ch), "RGBA").convert_alpha()
                    scl = min(1.0, 160.0 / max(ch, cw))   # thu nho cho nhe
                    if scl < 1.0:
                        surf = pygame.transform.smoothscale(surf, (max(1, int(cw * scl)), max(1, int(ch * scl))))
                    mpp = sb.CELL / float(im.width)
                    result = (surf, (x1 - x0) * mpp, (y1 - y0) * mpp)
            except Exception:
                result = None
        self._mesh_cache[asset] = result
        return result

    def _rot_rect_pts(self, cx, cy, wpx, hpx, yaw_deg):
        """4 goc chu nhat (tam cx,cy) xoay yaw_deg trong khong gian man hinh (y xuong)."""
        return bbox_corners(cx, cy, wpx, hpx, yaw_deg)

    def draw_furni(self, f, selected=False):
        sx, sy = self.usd_to_screen(f["x"], f["y"])
        shape = f.get("shape", "bbox")
        fill = FURNI_SEL if selected else FURNI_COL
        yaw = f.get("yaw", 0.0)

        if shape == "mesh":
            mesh = self._get_mesh_surface(f["asset"])
            if mesh is None:
                # chua co du lieu mesh -> danh dau bang dau '?' mau do
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
            surf.fill(fill + (255,), special_flags=pygame.BLEND_RGBA_MULT)  # to mau theo trang thai
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
            pygame.draw.circle(self.screen, BG, (int(sx), int(sy)), rpx, 1)
            ex, ey = sx + math.cos(math.radians(yaw)) * rpx, sy + math.sin(math.radians(yaw)) * rpx
            pygame.draw.line(self.screen, ACCENT if selected else BG, (sx, sy), (ex, ey), 2)
            return

        # bbox (mac dinh): chu nhat w x h xoay theo yaw
        wpx = max(4, int(f.get("w", 0.8) / sb.CELL * self.cs))
        hpx = max(4, int(f.get("h", 0.8) / sb.CELL * self.cs))
        if selected:
            ring = self._rot_rect_pts(sx, sy, wpx + 8, hpx + 8, yaw)
            pygame.draw.polygon(self.screen, ACCENT, ring, 2)
        pts = self._rot_rect_pts(sx, sy, wpx, hpx, yaw)
        pygame.draw.polygon(self.screen, fill, pts)
        pygame.draw.polygon(self.screen, BG, pts, 1)
        ex, ey = sx + math.cos(math.radians(yaw)) * wpx / 2, sy + math.sin(math.radians(yaw)) * hpx / 2
        pygame.draw.line(self.screen, ACCENT if selected else BG, (sx, sy), (ex, ey), 2)

    def _btn_groups(self):
        wall = self.structure.get("wall", sb.STRUCTURE_CHOICES["wall"][0])
        floor = self.structure.get("floor", sb.STRUCTURE_CHOICES["floor"][0])
        return [
            ("CONG CU", [("floor", "1 Floor"), ("wall", "2 Wall"), ("furni", "3 Furniture")]),
            ("HOA TAC", [("undo", "Undo (Ctrl+Z)"), ("redo", "Redo (Ctrl+Y)")]),
            ("LUOI", [("walls", "Auto-walls (W)"), ("clear", "Clear (C)"),
                      ("gx-", "X -"), ("gx+", "X +"), ("gy-", "Y -"), ("gy+", "Y +")]),
            ("CAU TRUC (prop 3D)", [("cyc_wall", "Wall: " + wall.replace("SM_", "")),
                                    ("cyc_floor", "Floor: " + floor.replace("SM_", ""))]),
            ("TEP", [("usd", "SAVE .usd (S)"), ("export", "Export BEV (B)"),
                     ("savemap", "Save map (Ctrl+S)"), ("load", "Load map (L)")]),
        ]

    def draw_panel(self):
        px = self.win_w - PANEL_W
        pygame.draw.rect(self.screen, PANEL_BG, (px, 0, PANEL_W, self.win_h))
        mx, my = pygame.mouse.get_pos()
        bx = px + 16
        bw_full = PANEL_W - 32
        self.buttons = []
        self._pal_rects = []

        avail_h = self.win_h - STATUS_H
        # kep truoc khi ve (dung gioi han frame truoc) de tranh nhay khi resize
        self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll))
        # clip vung panel (khong ke status bar) -> noi dung cuon khong tran ra ngoai
        self.screen.set_clip(pygame.Rect(px, 0, PANEL_W, avail_h))
        y = 16 - self.panel_scroll

        self.screen.blit(self.font_b.render("SCENE EDITOR", True, TEXT), (px + 16, y)); y += 30
        pygame.draw.line(self.screen, SECTION_LINE, (px + 16, y), (px + PANEL_W - 16, y)); y += 10

        for title, defs in self._btn_groups():
            self.screen.blit(self.font_s.render(title, True, TEXT_DIM), (bx, y)); y += 18
            i = 0
            while i < len(defs):
                key, label = defs[i]
                small = key in ("gx-", "gx+", "gy-", "gy+")
                if small:
                    bw = (bw_full - 12) // 2
                    col = i % 2
                    rect = pygame.Rect(bx + col * (bw + 12), y, bw, 26)
                    self._draw_button(rect, key, label, mx, my)
                    if col == 1:
                        y += 32
                    i += 1
                    continue
                rect = pygame.Rect(bx, y, bw_full, 30)
                self._draw_button(rect, key, label, mx, my)
                y += 36
                i += 1
            y += 8
            pygame.draw.line(self.screen, SECTION_LINE, (px + 16, y - 2), (px + PANEL_W - 16, y - 2))
            y += 6

        # transform inspector (chi hien khi dang chon 1 vat noi that)
        if self.selected is not None and self.tool == "furniture" and 0 <= self.selected < len(self.furniture):
            if self._scroll_to_transform:
                # dua o TRANSFORM len gan dau vung nhin (ap dung tu frame sau)
                tf_top_abs = y + self.panel_scroll
                self.panel_scroll = max(0, tf_top_abs - 56)
                self._scroll_to_transform = False
            y = self.draw_transform_panel(px, y)
        else:
            self.field_rects = {}
            self._scroll_to_transform = False

        # palette (danh sach noi that) - filter theo category + search
        self._pal_cat_rects = []
        self.screen.blit(self.font.render("Noi that:", True, TEXT_DIM), (px + 16, y)); y += 22

        # category tabs
        categories = ["Tat ca"] + list(FURNITURE_CATEGORIES.keys())
        tab_x = px + 16
        for cat_name in categories:
            active = (cat_name == self._pal_cat)
            tab_w = self.font_s.size(cat_name)[0] + 12
            if tab_x + tab_w > px + PANEL_W - 16:
                tab_x = px + 16
                y += 22
            tab_rect = pygame.Rect(tab_x, y, tab_w, 18)
            col = BTN_ACTIVE if active else BTN
            pygame.draw.rect(self.screen, col, tab_rect, border_radius=4)
            self.screen.blit(self.font_s.render(cat_name, True, TEXT if active else TEXT_DIM),
                             (tab_rect.x + 6, tab_rect.y + 2))
            self._pal_cat_rects.append((cat_name, tab_rect))
            tab_x += tab_w + 6
        y += 24

        # search field
        search_label = self._pal_filter if self._pal_filter else "Tim kiem..."
        search_bg = FIELD_ACTIVE_BG if getattr(self, '_pal_search_active', False) else FIELD_BG
        self._pal_search_rect = pygame.Rect(px + 16, y, PANEL_W - 32, 22)
        pygame.draw.rect(self.screen, search_bg, self._pal_search_rect, border_radius=4)
        pygame.draw.rect(self.screen, SECTION_LINE, self._pal_search_rect, 1, border_radius=4)
        prefix = "> " if self._pal_search_active else "  "
        col = TEXT if self._pal_filter else TEXT_DIM
        self.screen.blit(self.font_s.render(prefix + search_label, True, col),
                         (self._pal_search_rect.x + 6, self._pal_search_rect.y + 3))
        y += 26

        # filtered items
        fp = self.filtered_palette()
        self._pal_rects = []
        for filt_idx, (name, _rad) in enumerate(fp):
            real_idx = self.palette.index((name, _rad))
            rect = pygame.Rect(px + 16, y, PANEL_W - 32, 19)
            sel = (real_idx == self.pal_sel and self.tool == "furniture")
            if sel:
                pygame.draw.rect(self.screen, FURNI_SEL, rect, border_radius=4)
            elif filt_idx % 2 == 1:
                pygame.draw.rect(self.screen, PANEL_ROW_ALT, rect, border_radius=4)
            self.screen.blit(self.font_s.render(name, True, TEXT if sel else TEXT_DIM),
                             (rect.x + 8, rect.y + 3))
            self._pal_rects.append((real_idx, rect))
            y += 22
        if not fp:
            self.screen.blit(self.font_s.render("(Khong tim thay)", True, TEXT_DIM), (px + 24, y))
            y += 22
        y += 6

        # tinh gioi han cuon + reset clip
        content_h = y + self.panel_scroll        # tong chieu cao noi dung (tu 16)
        self._panel_max_scroll = max(0, content_h - avail_h + 8)
        self.panel_scroll = max(0, min(self._panel_max_scroll, self.panel_scroll))
        self.screen.set_clip(None)

        # thanh cuon (chi khi noi dung tran)
        if self._panel_max_scroll > 0:
            bar_h = max(30, int(avail_h * avail_h / float(content_h)))
            bar_y = int((avail_h - bar_h) * self.panel_scroll / self._panel_max_scroll)
            pygame.draw.rect(self.screen, BTN_HOVER, (self.win_w - 5, bar_y, 4, bar_h), border_radius=2)

    def draw_transform_panel(self, px, y):
        f = self.furniture[self.selected]
        mx, my = pygame.mouse.get_pos()
        self.screen.blit(self.font_s.render("TRANSFORM", True, ACCENT), (px + 16, y)); y += 18
        pygame.draw.line(self.screen, ACCENT_DIM, (px + 16, y), (px + PANEL_W - 16, y)); y += 8
        self.screen.blit(self.font_s.render(f["asset"], True, TEXT_DIM), (px + 16, y)); y += 22

        self.field_rects = {}
        for name, label in (("x", "X (m)"), ("y", "Y (m)"), ("yaw", "Yaw (do)")):
            y = self._draw_field_row(px, y, name, label, f.get(name, 0.0), mx, my)
        y += 4

        # --- SHAPE ---
        shape = f.get("shape", "bbox")
        self.screen.blit(self.font_s.render("SHAPE", True, ACCENT), (px + 16, y)); y += 18
        bw = (PANEL_W - 32 - 2 * 8) // 3
        for k, (skey, slabel) in enumerate((("bbox", "BBox"), ("sphere", "Sphere"), ("mesh", "Mesh"))):
            rect = pygame.Rect(px + 16 + k * (bw + 8), y, bw, 26)
            self._draw_shape_button(rect, skey, slabel, shape, mx, my)
        y += 34
        if shape == "bbox":
            y = self._draw_field_row(px, y, "w", "W (m)", f.get("w", 0.8), mx, my)
            y = self._draw_field_row(px, y, "h", "H (m)", f.get("h", 0.8), mx, my)
        elif shape == "sphere":
            y = self._draw_field_row(px, y, "r", "R (m)", f.get("r", 0.4), mx, my)
        else:  # mesh
            self.screen.blit(self.font_s.render("Mesh: (chua co du lieu)", True, TEXT_DIM),
                             (px + 16, y + 2)); y += 22
        y += 6

        bw2 = (PANEL_W - 32 - 12) // 2
        dup_rect = pygame.Rect(px + 16, y, bw2, 26)
        del_rect = pygame.Rect(px + 16 + bw2 + 12, y, bw2, 26)
        self._draw_button(dup_rect, "tf_dup", "Nhan ban", mx, my)
        self._draw_button(del_rect, "tf_del", "Xoa", mx, my, danger=True)
        y += 34
        pygame.draw.line(self.screen, SECTION_LINE, (px + 16, y - 2), (px + PANEL_W - 16, y - 2))
        y += 8
        return y

    def _draw_shape_button(self, rect, skey, slabel, cur_shape, mx, my):
        active = (skey == cur_shape)
        hover = rect.collidepoint(mx, my)
        col = ACCENT_DIM if active else (BTN_HOVER if hover else BTN)
        pygame.draw.rect(self.screen, col, rect, border_radius=5)
        if active:
            pygame.draw.rect(self.screen, ACCENT, rect, 1, border_radius=5)
        self.screen.blit(self.font_s.render(slabel, True, TEXT), (rect.x + 8, rect.y + rect.h // 2 - 8))
        self.buttons.append((rect, "shape_" + skey, slabel))

    def _draw_field_row(self, px, y, name, label, value, mx, my):
        row_h = 24
        lbl_w = 58
        step_w = 22
        gap = 6
        self.screen.blit(self.font_s.render(label, True, TEXT_DIM), (px + 16, y + 5))
        minus_rect = pygame.Rect(px + 16 + lbl_w, y, step_w, row_h)
        box_w = (PANEL_W - 32) - lbl_w - 2 * step_w - 2 * gap
        box_rect = pygame.Rect(minus_rect.right + gap, y, box_w, row_h)
        plus_rect = pygame.Rect(box_rect.right + gap, y, step_w, row_h)

        self._draw_button(minus_rect, "step%s-" % name, "-", mx, my)
        self._draw_button(plus_rect, "step%s+" % name, "+", mx, my)

        active = (self.active_field == name)
        pygame.draw.rect(self.screen, FIELD_ACTIVE_BG if active else FIELD_BG, box_rect, border_radius=4)
        pygame.draw.rect(self.screen, ACCENT if active else SECTION_LINE, box_rect, 1, border_radius=4)
        if active:
            blink = (pygame.time.get_ticks() // 500) % 2 == 0
            txt = self.field_buffer + ("_" if blink else "")
        else:
            txt = ("%d" % int(round(value))) if name == "yaw" else ("%.2f" % value)
        self.screen.blit(self.font_s.render(txt, True, TEXT), (box_rect.x + 6, box_rect.y + 4))
        self.field_rects[name] = box_rect
        return y + row_h + 6

    def _draw_button(self, rect, key, label, mx, my, danger=False):
        tool_of = {"floor": "floor", "wall": "wall", "furni": "furniture"}
        active = tool_of.get(key) == self.tool
        hover = rect.collidepoint(mx, my)
        if danger:
            # nut Xoa: nen toi (C0) de phan biet, sang len khi hover
            col = C1 if hover else C0
        else:
            col = BTN_ACTIVE if active else (BTN_HOVER if hover else BTN)
        pygame.draw.rect(self.screen, col, rect, border_radius=5)
        self.screen.blit(self.font_s.render(label, True, TEXT), (rect.x + 8, rect.y + rect.h // 2 - 8))
        self.buttons.append((rect, key, label))

    def draw_status(self):
        y = self.win_h - STATUS_H
        pygame.draw.rect(self.screen, C0, (0, y, self.win_w, STATUS_H))
        pygame.draw.line(self.screen, SECTION_LINE, (0, y), (self.win_w, y))
        nxt = os.path.basename(sb.next_scene_path())
        badge_col = ACCENT if self.tool == "furniture" else BTN_ACTIVE
        badge_surf = self.font_s.render(self.tool.upper(), True, C0)
        badge_rect = pygame.Rect(12, y + 6, badge_surf.get_width() + 16, 20)
        pygame.draw.rect(self.screen, badge_col, badge_rect, border_radius=4)
        self.screen.blit(badge_surf, (badge_rect.x + 8, badge_rect.y + 3))
        info = "Luoi:%dx%d  san:%d den:%d vat:%d  dat:%s  yaw:%d  zoom:%d%%  -> %s" % (
            self.nx, self.ny,
            len(self.cells), sum(1 for v in self.cells.values() if v == 2),
            len(self.furniture), self.place_shape.upper(), int(self.cur_yaw),
            int(self.zoom * 100), nxt)
        self.screen.blit(self.font_s.render(info, True, TEXT_DIM), (badge_rect.right + 10, y + 8))
        self.screen.blit(self.font.render(self.msg, True, TEXT), (12, y + 24))

    # ---- menu chuot phai ----
    def _ctx_menu_geometry(self):
        if not self.ctx_menu:
            return None
        mx, my = self.ctx_menu["pos"]
        item_w, item_h = 150, 28
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
        geo = self._ctx_menu_geometry()
        x0, y0, w, h = geo
        n = len(self.ctx_menu["items"])
        pygame.draw.rect(self.screen, PANEL_BG, (x0 - 3, y0 - 3, w + 6, n * h + 6), border_radius=6)
        mx, my = pygame.mouse.get_pos()
        for i, (key, label) in enumerate(self.ctx_menu["items"]):
            rect = self._ctx_item_rect(i)
            col = BTN_HOVER if rect.collidepoint(mx, my) else BTN
            pygame.draw.rect(self.screen, col, rect, border_radius=4)
            txt_col = C0 if key == "delete" else TEXT
            self.screen.blit(self.font_s.render(label, True, txt_col), (rect.x + 10, rect.y + 7))

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
