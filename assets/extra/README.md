# ExtraProps — thả asset nội thất mới vào đây

Thả file `.usd` / `.usdz` **tự chứa** (material/texture nhúng sẵn) của một vật thể nội thất
vào thư mục này. Nó sẽ **tự xuất hiện trong palette** của `scene_editor.py`
(qua `scene_builder.available_furniture()`).

Yêu cầu asset:
- **Z-up, đơn vị mét** (nếu asset dựng bằng cm, để nguyên — prop office cũng scale 0.01;
  kiểm tra nhanh bằng cách chụp BEV, xem footprint có hợp lý ~mét không).
- Tốt nhất là **1 file tự chứa** (hoặc `.usdz`). Nếu asset phụ thuộc texture ngoài,
  gói lại thành `.usdz` hoặc để kèm thư mục texture bên cạnh.

Quy trình lấy đúng shape (bbox/sphere/mesh) cho asset mới:
1. Thả `<Ten>.usd` vào `ExtraProps/`.
2. Chụp BEV:  `%ISAACSIM%\python.bat isaac_bev_capture.py <Ten>`
3. Đo shape:  `python build_furniture_shapes.py`  (đo W/H/R + cắt mesh footprint)
4. Mở `scene_editor.py` — asset đã có trong palette với shape đúng.

Xem thêm `ASSETS.md` (thư mục gốc) để biết các nguồn tải asset tương thích.
