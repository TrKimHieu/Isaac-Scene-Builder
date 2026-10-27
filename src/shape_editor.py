"""
shape_editor.py - Window to manually draw a bounding box/sphere on a BEV render
(white background) to set w,h or r and auto-cut the shape.

Usage:
    python src/shape_editor.py [render_dir]

Reads renders from: output/mesh_shapes/renders/*.png by default
(produced by isaac_bev_capture.py - square frame centered on the prop, frame_m from the
<asset>.json sidecar; legacy renders = one 3x3 m cell).

Controls:
  BOX    (1): drag to draw the bounding rectangle -> auto W,H (m)
  CIRCLE (2): drag from the CENTER outward to set the radius -> auto R (m)
  Auto-fit (A): auto-fit the non-white region (object)
  Cut & Save (S): cut the shape (object=black, bg=white) into mesh_shapes/<asset>.png
                  and write W/H or R into props_shapes.json (used as default by scene_editor)
  <- / -> : previous / next image | Esc quit
"""
import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

from config import (CELL, RENDER_DIR, COLOR_DIR, C0, MESH_MARK, BG, PANEL_BG, TEXT, TEXT_DIM,
                    BTN, BTN_HOVER, BTN_ACTIVE, ACCENT, GRID_LINE, SECTION_LINE)
import bev_export as bev
import shape_tools as st

WIN_W, WIN_H = 1160, 760
PANEL_W = 300
PAD = 16
STATUS_H = 40

GRID = GRID_LINE
SECTION = SECTION_LINE


class ShapeEditor:
    def __init__(self, render_dir=RENDER_DIR):
        pygame.init()
        pygame.display.set_caption("Isaac Scene Builder - Shape Editor")
        self.screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
        self.win_w, self.win_h = WIN_W, WIN_H
        self.font = pygame.font.SysFont("consolas", 15)
        self.font_s = pygame.font.SysFont("consolas", 13)
        self.font_b = pygame.font.SysFont("consolas", 17, bold=True)
        self.font_big = pygame.font.SysFont("consolas", 40, bold=True)
        self.clock = pygame.time.Clock()

        self.render_dir = render_dir
        self.files = self._scan()
        self.idx = 0
        self.img = None            # original PIL RGB image
        self.tex = None            # pygame Surface for display
        self.mode = "box"          # "box" | "circle"
        self.box = None            # (x0,y0,x1,y1) in IMAGE PIXEL coords
        self.circle = None         # (cx,cy,rad) in image pixels
        self.drag_from = None      # drag start point (image pixels)
        self.buttons = []
        self.msg = "Drag to draw a bounding shape. A = auto-fit, S = cut & save."
        if self.files:
            self.load(0)
        else:
            self.msg = "No renders found in: %s" % self.render_dir
        self._recalc()

    # ---- data ----
    def _scan(self):
        if not os.path.isdir(self.render_dir):
            return []
        return sorted(f for f in os.listdir(self.render_dir) if f.lower().endswith(".png"))

    @property
    def asset(self):
        if not self.files:
            return None
        return os.path.splitext(self.files[self.idx])[0]

    def load(self, i):
        self.idx = i % len(self.files)
        path = os.path.join(self.render_dir, self.files[self.idx])
        self.img = st.Image.open(path).convert("RGB")
        self.frame_m = st.render_frame_m(path)
        self.box = None
        self.circle = None
        self.drag_from = None
        self._make_tex()
        self.msg = "Image: %s (%dx%d px, frame %.1f m, %.4f m/px)" % (
            self.files[self.idx], self.img.width, self.img.height, self.frame_m,
            st.meters_per_pixel(self.img.width, self.frame_m))

    def _make_tex(self):
        mode = self.img.mode
        data = self.img.tobytes()
        self.tex = pygame.image.fromstring(data, self.img.size, mode).convert()

    # ---- layout / mapping ----
    def _recalc(self):
        self.canvas = pygame.Rect(PAD, PAD, self.win_w - PANEL_W - 2 * PAD,
                                  self.win_h - 2 * PAD - STATUS_H)
        if self.img:
            iw, ih = self.img.size
            self.disp = min(self.canvas.w / iw, self.canvas.h / ih)
            dw, dh = int(iw * self.disp), int(ih * self.disp)
            self.dispx = self.canvas.x + (self.canvas.w - dw) // 2
            self.dispy = self.canvas.y + (self.canvas.h - dh) // 2

    def scr_to_img(self, mx, my):
        return (mx - self.dispx) / self.disp, (my - self.dispy) / self.disp

    def img_to_scr(self, ix, iy):
        return self.dispx + ix * self.disp, self.dispy + iy * self.disp

    def in_canvas(self, mx, my):
        return self.canvas.collidepoint(mx, my)

    # ---- actions ----
    def auto_fit(self):
        if self.img is None:
            return
        box = st.auto_bbox(self.img)
        if box is None:
            self.msg = "Image is all white - no object found."
            return
        if self.mode == "box":
            self.box = box
        else:
            x0, y0, x1, y1 = box
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            rad = max(x1 - x0, y1 - y0) / 2
            self.circle = (cx, cy, rad)
        self.msg = "Auto-fit done. Adjust if needed, then press S to save."

    def measured(self):
        """Return (shape, w, h, r) in meters for the current shape, or None."""
        if self.img is None:
            return None
        iw = self.img.width
        if self.mode == "box" and self.box:
            w, h = st.bbox_to_wh(self.box, iw, self.frame_m)
            return "bbox", w, h, max(w, h) / 2
        if self.mode == "circle" and self.circle:
            r = st.radius_to_m(self.circle[2], iw, self.frame_m)
            return "sphere", 2 * r, 2 * r, r
        return None

    def cut_and_save(self):
        m = self.measured()
        if m is None or self.asset is None:
            self.msg = "No bounding drawn yet."
            return
        shape, w, h, r = m
        mesh_dir = bev.MESH_DIR
        if self.mode == "box":
            x0, y0, x1, y1 = [int(round(v)) for v in self.box]
            x0, y0 = max(0, x0), max(0, y0)
            mask = st.cut_shape(self.img, (x0, y0, x1, y1))
            color = st.color_cutout(self.img, (x0, y0, x1, y1))
        else:
            cx, cy, rad = self.circle
            mask = st.circle_mask_shape(self.img, cx, cy, rad)
            x0, y0 = max(0, int(cx - rad)), max(0, int(cy - rad))
            color = st.color_cutout(self.img, (x0, y0, x0 + mask.width, y0 + mask.height))
            color.putalpha(st.Image.eval(mask, lambda v: 255 if v < 128 else 0))
        st.save_shape_png(mask, self.asset, mesh_dir)
        os.makedirs(COLOR_DIR, exist_ok=True)
        color.save(os.path.join(COLOR_DIR, self.asset + ".png"))
        rel = "mesh_shapes/%s.png" % self.asset
        bev.save_prop_shape(self.asset, shape, w, h, r, mesh=rel,
                            mesh_mpp=st.meters_per_pixel(self.img.width, self.frame_m),
                            color="mesh_shapes/color/%s.png" % self.asset)
        self.msg = "Saved %s.png + props_shapes.json | %s w=%.2f h=%.2f r=%.2f" % (
            self.asset, shape, w, h, r)

    # ---- input ----
    def on_down(self, mx, my, button):
        if mx >= self.win_w - PANEL_W:
            for rect, key in self.buttons:
                if rect.collidepoint(mx, my):
                    self.do(key)
                    return
            return
        if button == 1 and self.in_canvas(mx, my) and self.img is not None:
            self.drag_from = self.scr_to_img(mx, my)

    def on_motion(self, mx, my):
        if self.drag_from is None:
            return
        ix, iy = self.scr_to_img(mx, my)
        x0, y0 = self.drag_from
        if self.mode == "box":
            self.box = (min(x0, ix), min(y0, iy), max(x0, ix), max(y0, iy))
        else:
            rad = ((ix - x0) ** 2 + (iy - y0) ** 2) ** 0.5
            self.circle = (x0, y0, rad)

    def on_up(self, mx, my, button):
        self.drag_from = None

    def do(self, key):
        if key == "box": self.mode = "box"
        elif key == "circle": self.mode = "circle"
        elif key == "auto": self.auto_fit()
        elif key == "save": self.cut_and_save()
        elif key == "prev": self.load(self.idx - 1)
        elif key == "next": self.load(self.idx + 1)
        elif key == "reload":
            self.files = self._scan()
            if self.files:
                self.load(self.idx % len(self.files))

    def on_key(self, k):
        if k == pygame.K_1: self.mode = "box"
        elif k == pygame.K_2: self.mode = "circle"
        elif k == pygame.K_a: self.auto_fit()
        elif k == pygame.K_s: self.cut_and_save()
        elif k == pygame.K_LEFT and self.files: self.load(self.idx - 1)
        elif k == pygame.K_RIGHT and self.files: self.load(self.idx + 1)
        elif k == pygame.K_r: self.do("reload")

    # ---- draw ----
    def draw(self):
        self.screen.fill(BG)
        self._recalc()
        self.draw_canvas()
        self.draw_panel()
        self.draw_status()
        pygame.display.flip()

    def draw_canvas(self):
        pygame.draw.rect(self.screen, SECTION, self.canvas, 1)
        if self.tex is None:
            return
        iw, ih = self.img.size
        scaled = pygame.transform.smoothscale(self.tex, (int(iw * self.disp), int(ih * self.disp)))
        self.screen.blit(scaled, (self.dispx, self.dispy))
        # overlay bounding
        if self.mode == "box" and self.box:
            x0, y0 = self.img_to_scr(self.box[0], self.box[1])
            x1, y1 = self.img_to_scr(self.box[2], self.box[3])
            pygame.draw.rect(self.screen, ACCENT, pygame.Rect(x0, y0, x1 - x0, y1 - y0), 2)
        elif self.mode == "circle" and self.circle:
            cx, cy = self.img_to_scr(self.circle[0], self.circle[1])
            pygame.draw.circle(self.screen, ACCENT, (int(cx), int(cy)),
                               int(self.circle[2] * self.disp), 2)
            pygame.draw.circle(self.screen, ACCENT, (int(cx), int(cy)), 3)

    def draw_panel(self):
        px = self.win_w - PANEL_W
        pygame.draw.rect(self.screen, PANEL_BG, (px, 0, PANEL_W, self.win_h))
        pygame.draw.line(self.screen, SECTION, (px, 0), (px, self.win_h))
        self.buttons = []
        mx, my = pygame.mouse.get_pos()
        y = 16
        self.screen.blit(self.font_b.render("SHAPE EDITOR", True, TEXT), (px + 16, y)); y += 30
        pygame.draw.line(self.screen, SECTION, (px + 16, y), (px + PANEL_W - 16, y)); y += 12

        # asset info
        name = self.asset or "(no image)"
        self.screen.blit(self.font.render(name, True, TEXT), (px + 16, y)); y += 20
        if self.files:
            self.screen.blit(self.font_s.render("%d / %d" % (self.idx + 1, len(self.files)),
                             True, TEXT_DIM), (px + 16, y)); y += 22
        bw = (PANEL_W - 32 - 10) // 2
        self._btn(px + 16, y, bw, "< Prev", "prev", mx, my)
        self._btn(px + 16 + bw + 10, y, bw, "Next >", "next", mx, my); y += 34
        pygame.draw.line(self.screen, SECTION, (px + 16, y), (px + PANEL_W - 16, y)); y += 12

        # mode
        self.screen.blit(self.font_s.render("BOUNDING TYPE", True, TEXT_DIM), (px + 16, y)); y += 18
        self._btn(px + 16, y, bw, "1 Box", "box", mx, my, active=(self.mode == "box"))
        self._btn(px + 16 + bw + 10, y, bw, "2 Circle", "circle", mx, my, active=(self.mode == "circle"))
        y += 34

        # measured
        m = self.measured()
        self.screen.blit(self.font_s.render("SIZE (meters)", True, TEXT_DIM), (px + 16, y)); y += 20
        if m:
            shape, w, h, r = m
            if shape == "bbox":
                lines = ["W = %.3f" % w, "H = %.3f" % h]
            else:
                lines = ["R = %.3f" % r]
        else:
            lines = ["(no bounding yet)"]
        for ln in lines:
            self.screen.blit(self.font.render(ln, True, ACCENT), (px + 24, y)); y += 22
        y += 6

        self._btn(px + 16, y, PANEL_W - 32, "Auto-fit object (A)", "auto", mx, my); y += 34
        self._btn(px + 16, y, PANEL_W - 32, "Cut & Save shape (S)", "save", mx, my); y += 40
        pygame.draw.line(self.screen, SECTION, (px + 16, y), (px + PANEL_W - 16, y)); y += 10
        self._btn(px + 16, y, PANEL_W - 32, "Reload list (R)", "reload", mx, my)

    def _btn(self, x, y, w, label, key, mx, my, active=False, h=28):
        rect = pygame.Rect(x, y, w, h)
        hover = rect.collidepoint(mx, my)
        col = BTN_ACTIVE if active else (BTN_HOVER if hover else BTN)
        pygame.draw.rect(self.screen, col, rect, border_radius=5)
        self.screen.blit(self.font_s.render(label, True, TEXT), (rect.x + 8, rect.y + h // 2 - 8))
        self.buttons.append((rect, key))

    def draw_status(self):
        y = self.win_h - STATUS_H
        pygame.draw.rect(self.screen, C0, (0, y, self.win_w, STATUS_H))
        pygame.draw.line(self.screen, SECTION, (0, y), (self.win_w, y))
        self.screen.blit(self.font_s.render(self.msg, True, TEXT), (12, y + 12))

    # ---- loop ----
    def run(self):
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.VIDEORESIZE:
                    self.win_w = max(760, ev.w); self.win_h = max(520, ev.h)
                    self.screen = pygame.display.set_mode((self.win_w, self.win_h), pygame.RESIZABLE)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
                    self.on_down(ev.pos[0], ev.pos[1], ev.button)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button in (1, 3):
                    self.on_up(ev.pos[0], ev.pos[1], ev.button)
                elif ev.type == pygame.MOUSEMOTION:
                    self.on_motion(ev.pos[0], ev.pos[1])
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        self.on_key(ev.key)
            self.draw()
            self.clock.tick(60)
        pygame.quit()


if __name__ == "__main__":
    rdir = sys.argv[1] if len(sys.argv) > 1 else RENDER_DIR
    ShapeEditor(rdir).run()
