"""
shape_tools.py - Logic thuan (khong pygame) cho viec do bounding box/sphere va
cat shape tu anh BEV render nen trang. Dung Pillow.

Quy uoc:
- Anh render (tu isaac_bev_capture.py) duoc dong khung vua khit 1 o 3x3 met,
  tuc chieu rong anh = CELL met -> met/pixel = CELL / img_width.
- "Nen trang, chi thu khong trang la object": pixel duoc coi la OBJECT neu no
  du toi/du bao hoa so voi trang (xem is_object_mask).
- Shape mask xuat ra la anh grayscale mode "L": OBJECT = 0 (den, occupied),
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
    """Tra numpy bool mask (True = object) tu anh RGB nen trang."""
    if np is None:
        raise RuntimeError("Pillow/numpy chua cai.")
    arr = np.asarray(pil_img.convert("RGB"), dtype=np.int16)
    mn = arr.min(axis=2)
    mx = arr.max(axis=2)
    darkness = 255 - mn
    saturation = mx - mn
    return (darkness > WHITE_TOL) | (saturation > SAT_TOL)


def auto_bbox(pil_img):
    """Bounding box cac pixel object -> (x0,y0,x1,y1) pixel, hoac None neu toan trang."""
    mask = is_object_mask(pil_img)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def radius_from_center_px(pil_img):
    """Ban kinh (px) hinh tron TAM TAI GIUA ANH bao het object. Tra None neu toan trang."""
    mask = is_object_mask(pil_img)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    h, w = mask.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    return float(d.max())


def bbox_to_wh(box, img_w, cell=CELL):
    """(x0,y0,x1,y1) pixel -> (w,h) met."""
    mpp = meters_per_pixel(img_w, cell)
    x0, y0, x1, y1 = box
    return abs(x1 - x0) * mpp, abs(y1 - y0) * mpp


def radius_to_m(radius_px, img_w, cell=CELL):
    return radius_px * meters_per_pixel(img_w, cell)


def cut_shape(pil_img, box=None):
    """Cat shape trong 'box' (hoac toan anh) -> PIL 'L': object=0, nen=255."""
    if np is None:
        raise RuntimeError("Pillow/numpy chua cai.")
    mask = is_object_mask(pil_img)
    if box is not None:
        x0, y0, x1, y1 = box
        sub = mask[y0:y1, x0:x1]
    else:
        sub = mask
    out = np.where(sub, 0, 255).astype("uint8")
    return Image.fromarray(out, mode="L")


def circle_mask_shape(pil_img, cx, cy, radius_px):
    """Cat shape trong hinh tron (cx,cy,radius_px) -> PIL 'L': object=0."""
    if np is None:
        raise RuntimeError("Pillow/numpy chua cai.")
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
    """Luu mask shape vao mesh_dir/<asset>.png."""
    if not os.path.isdir(mesh_dir):
        os.makedirs(mesh_dir)
    path = os.path.join(mesh_dir, asset + ".png")
    pil_L.save(path)
    return path
