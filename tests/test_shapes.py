"""Tests for per-prop capture frames, mesh scale and colored top-down cut-outs."""
import os

import numpy as np
from PIL import Image

import shape_tools as st
from config import CELL


def _render(frame_px=600, obj=(150, 250, 450, 350), color=(200, 30, 30)):
    """White-bg render with one colored rectangle (x0, y0, x1, y1) px."""
    a = np.full((frame_px, frame_px, 3), 255, np.uint8)
    x0, y0, x1, y1 = obj
    a[y0:y1, x0:x1] = color
    return Image.fromarray(a, "RGB")


class TestPickFrame:
    def test_small_prop_keeps_cell(self):
        assert st.pick_frame((-0.4, -0.3, 0), (0.4, 0.3, 1)) == 3.0

    def test_large_prop_grows(self):
        # 4.26 m conference table centered on origin -> needs > 4.26 + margin
        assert st.pick_frame((-2.13, -0.6, 0), (2.13, 0.6, 0.8)) == 6.0

    def test_offset_origin_counts(self):
        # footprint not centered: frame must cover the farthest side from the origin
        assert st.pick_frame((0.0, 0.0, 0), (2.5, 0.5, 1)) == 6.0

    def test_huge_prop_caps_at_last_step(self):
        assert st.pick_frame((-20, -1, 0), (20, 1, 1)) == 18.0


class TestRenderMeta:
    def test_roundtrip(self, tmp_path):
        png = str(tmp_path / "AV_Steam.png")
        st.write_render_meta(png, 6.0, res=1024)
        assert st.render_frame_m(png) == 6.0

    def test_legacy_render_is_one_cell(self, tmp_path):
        assert st.render_frame_m(str(tmp_path / "SM_Chair.png")) == CELL


class TestMeshMpp:
    def test_entry_value(self):
        assert st.mesh_mpp({"mesh_mpp": 0.01}, 600) == 0.01

    def test_legacy(self):
        assert st.mesh_mpp({}, 600) == CELL / 600
        assert st.mesh_mpp(None, 300) == CELL / 300


class TestColorCutout:
    def test_colors_and_alpha(self):
        img = _render()
        rgba = np.asarray(st.color_cutout(img))
        assert rgba.shape == (600, 600, 4)
        assert tuple(rgba[300, 300]) == (200, 30, 30, 255)    # object keeps its color
        assert rgba[10, 10, 3] == 0                            # background transparent

    def test_matches_mask_framing(self):
        img = _render()
        box = (100, 200, 500, 400)
        mask = np.asarray(st.cut_shape(img, box))
        rgba = np.asarray(st.color_cutout(img, box))
        assert mask.shape == rgba.shape[:2]
        assert ((mask < 128) == (rgba[..., 3] > 0)).all()


class TestMeasure:
    def test_six_meter_frame(self, tmp_path, monkeypatch):
        import build_furniture_shapes as bfs
        saved = {}
        monkeypatch.setattr(bfs.bev, "save_prop_shape",
                            lambda *a, **k: saved.update(args=a, kw=k))
        monkeypatch.setattr(bfs, "MESH_DIR", str(tmp_path / "mesh"))
        monkeypatch.setattr(bfs, "COLOR_DIR", str(tmp_path / "color"))
        png = str(tmp_path / "AV_Steam.png")
        _render().save(png)                     # 300 x 100 px object in a 600 px image
        st.write_render_meta(png, 6.0)          # -> 0.01 m/px
        w, h, r, frame = bfs.measure("AV_Steam", png)
        assert frame == 6.0
        assert abs(w - 3.0) < 1e-6 and abs(h - 1.0) < 1e-6
        assert saved["kw"]["mesh_mpp"] == 0.01
        assert os.path.isfile(str(tmp_path / "mesh" / "AV_Steam.png"))
        assert os.path.isfile(str(tmp_path / "color" / "AV_Steam.png"))


class TestBevStamp:
    def test_stamp_uses_mesh_mpp(self, tmp_path, monkeypatch):
        import bev_export as bev
        mask = np.full((600, 600), 255, np.uint8)
        mask[250:350, 150:450] = 0                       # 3 m x 1 m at 0.01 m/px
        Image.fromarray(mask, "L").save(str(tmp_path / "AV_Steam.png"))
        monkeypatch.setattr(bev, "MESH_DIR", str(tmp_path))
        monkeypatch.setattr(bev, "load_prop_shapes",
                            lambda: {"AV_Steam": {"mesh_mpp": 0.01}})
        img = Image.new("L", (400, 400), 254)
        assert bev._mesh_stamp("AV_Steam", img, 200, 200, 0.0, 40)   # 40 px / m
        occ = np.asarray(img) == bev.OCC
        ys, xs = np.where(occ)
        assert abs((xs.max() - xs.min() + 1) - 120) <= 2               # 3 m -> 120 px
        assert abs((ys.max() - ys.min() + 1) - 40) <= 2                # 1 m -> 40 px
