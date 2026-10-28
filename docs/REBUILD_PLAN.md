# Kế hoạch dựng lại phần bị mất (2026-10-27)

Code, map, catalog, docs đã được khôi phục từ GitHub (`90c2df8`). Những phần **không có trên GitHub**
và cần dựng lại:

| Phần mất | Cách lấy lại |
|---|---|
| `assets/office/` (Office pack) | Tải lại từ server asset công khai của NVIDIA (đã kiểm tra: còn đủ) |
| `assets/extra/AV_*.usd` (13 asset SimReady) | Tìm lại trong Isaac Sim Asset Browser / SimReady |
| `output/mesh_shapes/*.png` (mesh footprint) | Chạy lại capture BEV + build shapes |
| `output/scenes/*.usd`, `output/bev/` | Sinh lại từ `data/maps/*.json` |
| `tools/batch_generate_scenes.py` | Viết lại từ đầu |
| `tools/check_density_distribution.py` | Viết lại từ đầu |

---

## Giai đoạn 1: Asset 3D

### 1a. Office pack: script tải tự động — ✅ XONG (2026-10-27)

`tools/fetch_office_assets.py` + `fetch_assets.bat` đã viết; đã tải Isaac 5.1: 543 prop + 365 file
Materials (~676 MB), đủ 63 prop mà `config.py` cần, 42 texture tham chiếu trong `.mdl` đều có.
Chưa kiểm tra bằng Isaac Sim (máy chặn DLL của `usd-core`) — xem bước 1c.
Office pack chính là `Isaac/Environments/Office/` trong bộ asset Isaac Sim, public trên S3:

```
https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/Environments/Office/
  Props/       543 file, ~8 MB    (SM_*.usd, dạng usdc)
  Materials/   >1000 file, ~20+ MB (.mdl + texture)
```

Các prop tham chiếu `../Materials/...`, nên phải tải **cả hai thư mục** và giữ nguyên cấu trúc:
`assets/office/Props/` và `assets/office/Materials/`.

Việc cần làm: viết `tools/fetch_office_assets.py`
- Liệt kê bucket S3 theo `prefix` (có phân trang `marker` vì `IsTruncated=true`), tải song song,
  bỏ qua file đã có cùng kích thước (chạy lại được nhiều lần).
- `--version` (mặc định `5.1`; đã kiểm tra 4.5 / 5.0 / 5.1 đều có), `--dest assets/office`.
- Sau khi tải, kiểm tra đủ `config.REQUIRED`, `FURNITURE`, `EXTRA_FURNITURE`, `STRUCTURE_CHOICES`
  và in ra danh sách còn thiếu.
- Thêm `fetch_assets.bat`.

### 1b. Asset SimReady (`assets/extra/`)
`data/props_shapes.json` còn ghi 13 asset ngoài Office pack:
`AV_Caprice_A/B/C`, `AV_CapriceBackless_A`, `AV_CapriceTable_A/B`, `AV_Contemporary_Hutch`,
`AV_Contemporary_LockedStorage`, `AV_Contemporary_OpenStorage`, `AV_Contemporary_StorageCube`,
`AV_Standard_HalfUnit/LargeUnit/SmallUnit`.

- Tìm theo tên trong Isaac Sim → *Asset Browser* / *SimReady Explorer* và export ra `.usd` tự chứa
  (hoặc `.usdz`) vào `assets/extra/`.
- Khi tìm được đường dẫn gốc trên S3, thêm vào `fetch_office_assets.py` (cờ `--extra`) để lần sau
  chỉ cần một lệnh là tải lại đủ.

### 1c. Kiểm tra
- `editor.bat` → palette hiện đủ đồ nội thất, mở `map8.json` không báo thiếu asset.
- Export `.usd` một map rồi mở trong Isaac Sim: material hiển thị đúng, không bị tím hoặc trắng.

---

## Giai đoạn 2: Dữ liệu sinh ra (`output/`)

Làm theo thứ tự, sau khi xong Giai đoạn 1:
1. `capture.bat` (chạy bằng `python.bat` của Isaac Sim) → ảnh BEV cho từng prop.
2. `build_shapes.bat` → `output/mesh_shapes/*.png` và cập nhật `data/props_shapes.json`.
   So sánh `git diff data/props_shapes.json`: W/H/R chỉ nên lệch rất ít so với bản cũ.
   Lệch lớn nghĩa là asset hoặc version khác.
3. Từ editor, export lại `.usd` + BEV cho `map1…map8`. Hoặc dùng `batch_generate_scenes.py --from-maps`
   ở Giai đoạn 3.

---

## Giai đoạn 3: Viết lại `tools/`

> Hai script này chưa từng được commit, nên phần mô tả dưới đây được suy ra từ tên file và từ code
> trong `src/`. **Cần bạn xác nhận hoặc bổ sung** những gì còn nhớ (tham số, định dạng output)
> trước khi code.

### 3a. `tools/batch_generate_scenes.py` — ✅ XONG (2026-10-28, `src/map_generator.py`)
Sinh hàng loạt map ngẫu nhiên theo đúng định dạng `data/maps/*.json`
(`grid`, `cells`, `vedges`, `hedges`, `furniture`, `structure`), rồi build USD + BEV.

- **Layout**: sinh mặt bằng gồm các phòng hình chữ nhật nối nhau bằng hành lang trên lưới ô 3 m.
  Tường đặt ở biên vùng (`boundary_edges`), cửa đặt ở cạnh chung giữa các phòng hoặc giữa phòng và hành lang.
- **Nội thất**: rải theo mật độ mục tiêu, kiểm tra va chạm bằng shape thật trong `props_shapes.json`
  (bbox xoay hoặc bán kính), chừa lối đi. Có thể gom theo nhóm (bàn + ghế) qua `FURNITURE_CATEGORIES`.
- **Output**: `data/maps/gen_XXXX.json`, `output/bev/<stem>/` (qua `bev_export.export_scene`, không cần Isaac)
  và tuỳ chọn `output/scenes/<stem>.usd` (qua `scene_builder.build_scene`, cần `pxr` / Python của Isaac).
- **CLI**: `--count`, `--seed`, `--grid-min/--grid-max`, `--density-min/--density-max`, `--no-usd`,
  `--from-maps` (chỉ build lại các map có sẵn), `--out-prefix`.
- Tách logic sinh map thành `src/map_generator.py` (thuần Python) để test được, giữ `tools/` mỏng.

### 3b. `tools/check_density_distribution.py` — ✅ XONG (2026-10-28)
Thống kê phân bố mật độ của một tập map, dùng để kiểm tra dataset sinh ra có cân bằng không.

- Với mỗi map: diện tích sàn, tổng footprint nội thất, **density = footprint / diện tích sàn**,
  số vật trên mỗi ô, tỷ lệ ô trống, độ rộng lối đi nhỏ nhất (từ raster BEV).
- Tổng hợp: histogram theo bin, min/mean/max, danh sách map ngoại lai (ngoài khoảng mục tiêu).
- **Output**: bảng in ra console, `output/density_report.csv`, `output/density_hist.png` (vẽ bằng Pillow,
  không thêm dependency).
- **CLI**: `--maps "data/maps/*.json"`, `--bins`, `--target-min/--target-max`.

### 3c. Test
- `tests/test_map_generator.py`: map sinh ra hợp lệ (parse được bằng `parse_map`, sàn liên thông,
  có cửa, nội thất không chồng nhau và nằm trên sàn), cùng seed thì ra cùng kết quả.
- `tests/test_density.py`: density tính đúng trên map mẫu dựng tay.
- Cài pytest: `pip install pytest -r requirements.txt`, chạy `python -m pytest -q`.

---

## Giai đoạn 4: Chống mất dữ liệu lần sau
- Commit và push `tools/`, `*.bat`, `docs/REBUILD_PLAN.md` lên GitHub ngay khi viết xong.
- Asset thì không đưa vào git, nhưng vì đã có `fetch_office_assets.py` nên lúc nào cũng tải lại được bằng một lệnh.
- Cập nhật `README.md` / `docs/ASSETS.md`: thêm bước "chạy `fetch_assets.bat`" vào phần cài đặt.

## Thứ tự đề xuất
1. `fetch_office_assets.py` + tải Office pack (nhanh, mở khoá mọi thứ khác)
2. Tìm lại 13 asset `AV_*`
3. Capture + build shapes
4. `map_generator.py` + `batch_generate_scenes.py` + test
5. `check_density_distribution.py` + test
6. Commit / push, cập nhật docs
