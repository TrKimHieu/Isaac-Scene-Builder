"""
shape_tools.py - Pure logic (no pygame) to measure bounding box/sphere and
cut the shape from a white-background BEV render. Uses Pillow.

Quy uoc:
- The render (from isaac_bev_capture.py) is framed exactly to one 3x3 m cell,
  i.e. image width = CELL meters -> meters/pixel = CELL / img_width.
- "White bg, anything non-white is object": a pixel is OBJECT if it
  is dark enough / saturated enough vs white (see is_object_mask).
- The output shape mask is grayscale "L": OBJECT = 0 (black, occupied),
  NEN = 255 (trang) -> khop voi bev_export._mesh_stamp / quy uoc ROS.
"""
import os

from config import CELL, WHITE_TOL, SAT_TOL

try:
    from PIL import Image
    import numpy as np
except ImportError:  # pragma: no cover
    Image = None
    np = None


def meters_per_pixel(img_w, cell=CELL):
    return float(cell) / float(img_w)


def is_object_mask(pil_img):
    """Return a numpy bool mask (True = object) from a white-bg RGB image."""
    if np is None:
        raise RuntimeError("Pillow/numpy not installed.")
    arr = np.asarray(pil_img.convert("RGB"), dtype=np.int16)
    mn = arr.min(axis=2)
    mx = arr.max(axis=2)
    darkness = 255 - mn
    saturation = mx - mn
    return (darkness > WHITE_TOL) | (saturation > SAT_TOL)


def auto_bbox(pil_img):
    """Bounding box of object pixels -> (x0,y0,x1,y1) px, or None if all white."""
    mask = is_object_mask(pil_img)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def radius_from_center_px(pil_img):
    """Radius (px) of a circle CENTERED ON THE IMAGE enclosing all object pixels. None if all white."""
    mask = is_object_mask(pil_img)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    h, w = mask.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    return float(d.max())


def bbox_to_wh(box, img_w, cell=CELL):
    """(x0,y0,x1,y1) px -> (w,h) meters."""
    mpp = meters_per_pixel(img_w, cell)
    x0, y0, x1, y1 = box
    return abs(x1 - x0) * mpp, abs(y1 - y0) * mpp


def radius_to_m(radius_px, img_w, cell=CELL):
    return radius_px * meters_per_pixel(img_w, cell)


def cut_shape(pil_img, box=None):
    """Cut the shape in 'box' (or the whole image) -> PIL 'L': object=0, bg=255."""
    if np is None:
        raise RuntimeError("Pillow/numpy not installed.")
    mask = is_object_mask(pil_img)
    if box is not None:
        x0, y0, x1, y1 = box
        sub = mask[y0:y1, x0:x1]
    else:
        sub = mask
    out = np.where(sub, 0, 255).astype("uint8")
    return Image.fromarray(out, mode="L")


def circle_mask_shape(pil_img, cx, cy, radius_px):
    """Cut the shape within a circle (cx,cy,radius_px) -> PIL 'L': object=0."""
    if np is None:
        raise RuntimeError("Pillow/numpy not installed.")
    mask = is_object_mask(pil_img)
    h, w = mask.shape
    yy, xx = np.ogrid[:h, :w]
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius_px ** 2
    obj = mask & inside
    x0 = max(0, int(cx - radius_px))
    x1 = min(w, int(cx + radius_px) + 1)
    y0 = max(0, int(cy - radius_px))
    y1 = min(h, int(cy + radius_px) + 1)
    out = np.where(obj[y0:y1, x0:x1], 0, 255).astype("uint8")
    return Image.fromarray(out, mode="L")


def save_shape_png(pil_L, asset, mesh_dir):
    """Save the shape mask to mesh_dir/<asset>.png."""
    if not os.path.isdir(mesh_dir):
        os.makedirs(mesh_dir)
    path = os.path.join(mesh_dir, asset + ".png")
    pil_L.save(path)
    return path
