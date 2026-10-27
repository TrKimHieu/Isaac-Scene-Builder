[English](ASSETS.md) · **Tiếng Việt**

# Thêm asset nội thất & đổi prop cấu trúc

Dự án hiện dùng bộ asset **Office** (`assets/office/Props/*.usd`). Bạn có thể bổ sung thêm
nội thất và đổi prop tường/sàn như dưới đây.

**Lấy Office pack:** `fetch_assets.bat` / `python tools/fetch_office_assets.py [--version 5.1]`
tải `Isaac/Environments/Office/{Props,Materials}` (~700 MB) từ server asset công khai của NVIDIA về
`assets/office/`, bỏ qua file đã có, rồi kiểm tra đủ mọi prop khai báo trong `src/config.py`.

## 1. Thêm nội thất mới (tự đăng ký)

Palette lấy từ `scene_builder.available_furniture()` = danh sách curated (`FURNITURE`)
**+ mọi `.usd` trong `assets/extra/`**. Nên chỉ cần:

1. Thả file asset **tự chứa** vào `assets/extra/` (xem `assets/extra/README.md`).
2. (Khuyến nghị) lấy shape thật để BEV/editor chính xác:
   - `%ISAACSIM%\python.bat src/isaac_bev_capture.py <Ten>`  — chụp ảnh BEV nền trắng.
   - `python src/build_furniture_shapes.py`  — đo W/H/R + cắt mesh footprint, ghi `data/props_shapes.json`.
3. Mở `src/scene_editor.py` → asset có trong palette; bán kính/shape lấy từ `data/props_shapes.json`
   (nếu chưa đo thì mặc định R=0.5).

Nếu muốn thêm vào **danh sách curated** (kèm bán kính cố định): thêm `("<Ten>", <r>)`
vào `FURNITURE` trong `src/scene_builder.py` (và `src/generate_scene.py` nếu dùng bộ sinh ngẫu nhiên).

## 2. Nguồn tải asset USD tương thích Isaac Sim

Yêu cầu: **USD/USDZ, Z-up, đơn vị mét, tự chứa** (material nhúng hoặc kèm texture).

- **Isaac Sim built-in assets** (đã cài sẵn theo Isaac Sim): thư viện `Isaac/Props/`,
  `Isaac/Environments/`, và **SimReady Assets** (nội thất, thùng, pallet, …). Trỏ tới
  asset root của Isaac Sim (Nucleus local hoặc thư mục cài) và copy `.usd` cần dùng vào `assets/extra/`.
- **NVIDIA Omniverse — SimReady Explorer / Asset Browser**: kho nội thất/vật thể SimReady
  chuẩn USD, kéo-thả hoặc export `.usd`.
- **Nguồn USDZ công khai** (mẫu 3D): các thư viện cho tải `.usdz` (Apple Quick Look gallery,
  Sketchfab export USDZ, …). `.usdz` là gói tự chứa nên rất hợp để thả vào `assets/extra/`.

Lưu ý:
- Nếu asset dựng bằng **cm**, prop có thể có `xformOp:scale = 0.01` như bộ Office — không sao,
  cứ chụp BEV kiểm tra footprint có ra kích thước mét hợp lý.
- Nếu footprint bị lật/xoay khác, chỉnh `VERTICAL_FLIP` trong `src/isaac_bev_capture.py`
  hoặc xoay lại trong `shape_editor.py`.

## 3. Đổi prop tường/sàn (cấu trúc)

Trong `src/scene_editor.py`, nhóm **"STRUCTURE (3D)"** ở panel có 2 nút xoay vòng:
- **Wall:** `SM_Wall_3m` (mặc định) / `SM_Window_3m_A` / `SM_Window_3m_B` / `SM_Wall_3m_doorElevator`.
- **Floor:** `SM_Floor_3m`.

Lựa chọn được lưu vào map (`structure`) và truyền sang `build_scene` khi Export `.usd`.
Chỉ nên dùng prop **dài đúng 3 m** để khớp ô lưới (tường 2m/6m, sàn 6m không khớp).
Muốn thêm lựa chọn, sửa `STRUCTURE_CHOICES` trong `src/scene_builder.py`.

> Lưu ý: tường được **canh giữa đường lưới tự động** (theo bbox thật của prop) nên khi đổi
> prop tường khác kích thước độ dày vẫn nằm đúng đường lưới.
