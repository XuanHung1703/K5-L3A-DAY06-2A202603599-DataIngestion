# Hướng dẫn chạy và tái lập bài làm Lab 6

- **Học viên:** Nguyễn Xuân Hùng (`2A202603599` · `L3A`)
- **Báo cáo cá nhân:** [report/individual/2A202603599_NguyenXuanHung.md](report/individual/2A202603599_NguyenXuanHung.md)

## 1. Cài đặt môi trường và khởi động PostgreSQL + pgvector

Mở PowerShell tại thư mục `starter/`:

```powershell
cd starter
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Kỳ vọng: in `Database: day6_lab | PostgreSQL: 16.16 ... | pgvector: 0.8.7` và `Setup OK`.

## 2. Dữ liệu PDF gốc (`data/`)

- Hai file PDF nguồn (`data/OpenStax1.pdf` ~101 MB và `data/OpenStax2.pdf` ~83 MB) được đưa vào `.gitignore` (`data/*.pdf`) để tuân thủ giới hạn file 100 MB của GitHub.
- Để chạy lại bước đọc PDF từ đầu, tải 2 file từ URL trong `data/manifest.json` (`source_path_or_url`) và lưu vào `data/OpenStax1.pdf`, `data/OpenStax2.pdf`.
- Người chấm có thể kiểm tra ngay toàn bộ chunk, trace, kết quả đánh giá và nhãn audit đã lưu sẵn trong `starter/results/` mà không cần tải lại 2 file PDF.

## 3. Chạy Pipeline (Ingest, Embed, Store và Benchmark)

Từ thư mục `starter/`:

```powershell
# Bước 3 & 4: Đọc 59 trang nội dung, chia chunk A/B/C, tạo embedding với google/embeddinggemma-2 và lưu vào pgvector
python scripts/run_lab6_step4.py --repo ".."

# Bước 5: Chạy truy xuất top-3 và tính Hit@1, Evidence Hit@3 trên tập dev (15 câu) và test (5 câu)
python -m src.run --split dev
python -m src.run --split test --config "results/step5_dev_20261113T115144_309787Z/run_config.json"

# Bước 6: Kiểm chứng chéo metadata (source, page, section, filter) của 45 bản ghi test top-3 với PDF gốc
python scripts/verify_metadata.py
```

## 4. Vị trí các Artifacts & Kết quả đã lưu

- **Manifest:** `data/manifest.json`
- **Benchmark (20 câu):** `benchmark/questions.json`
- **Experiment log:** `artifacts/experiment_log.csv`
- **Thống kê chunk & thời gian Ingest/Embed:** `starter/results/step4_20261113T112902_578828Z/`
- **Trace & điểm Hit@1/Hit@3 tập `dev`:** `starter/results/step5_dev_20261113T115144_309787Z/`
- **Trace & điểm Hit@1/Hit@3 tập `test`:** `starter/results/step5_test_20261113T115434_648655Z/`
- **Bảng nhãn Audit 5 khía cạnh:** `starter/results/step6_ai_review/`
- **Bằng chứng đối chiếu Metadata với PDF gốc:** `starter/results/metadata_verification/`
