# Báo cáo cá nhân — Day 6: Data Ingestion Engineering

**Họ và tên:** Nguyễn Xuân Hùng · **Mã học viên:** `2A202603599` · **Lớp:** `L3A`
**Repo bài nộp:** https://github.com/XuanHung1703/K5-L3A-DAY06-2A202603599-DataIngestion.git

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Chủ đề: Lịch sử thế giới hiện đại và Sinh học đại cương từ 2 sách giáo trình mở OpenStax (xuất qua LibreTexts):
    1. `openstax_1`: *World History II: From 1400 (OpenStax)* (`https://commons.libretexts.org/book/human-236231`), chọn trang vật lý `12–42` (Chapter 1 & đầu Chapter 2), loại trang `38` (chỉ có 67 ký tự sau lọc footer) $\rightarrow$ **30 trang hợp lệ** (`74,683` ký tự).
    2. `openstax_2`: *General Biology (OpenStax)* (`https://commons.libretexts.org/book/bio-1764`), chọn trang vật lý `97–125` (Chapter 3: Biological Macromolecules) $\rightarrow$ **29 trang hợp lệ** (`58,177` ký tự).
  - **Tổng cộng:** **59 trang nội dung hợp lệ** ($\ge 30$ trang yêu cầu), `132,860` ký tự chuẩn hóa.
  - **Giấy phép:** Mỗi trang được chọn trong cả hai file PDF đều in rõ dòng bản quyền ở chân trang: *"This page titled ... is shared under a CC BY 4.0 license and was authored, remixed, and/or curated by OpenStax."* Chi tiết khai báo tại `data/manifest.json`. Hai file PDF gốc (`~101 MB` và `~83 MB`) được đưa vào `.gitignore` để không vượt giới hạn dung lượng của GitHub; người chấm có thể tải lại từ URL trong manifest hoặc kiểm tra trực tiếp qua các file chunk, trace và kết quả đối chiếu đã lưu.
- **Chuẩn hóa, lỗi và giới hạn:**
  - Văn bản từng trang được trích xuất bằng `pypdfium2` (`5.15.2`), chuẩn hóa Unicode dựng sẵn (`NFC`), xóa dòng footer bản quyền lặp lại của LibreTexts và giữ ranh giới đoạn văn (`\n\n`).
  - Trang có dưới `100` ký tự sau làm sạch được tự động loại và ghi vào log (`starter/results/step4_20261113T112902_578828Z/ingestion_log.json`, ghi nhận trang `38` của `openstax_1`).
  - Giới hạn: Bản xuất PDF từ LibreTexts còn sót một vài mảnh thuộc tính HTML (như `-ny9bj0-0 hwsygj page-content" tabindex="0">`) ở đầu một số mục và các câu bị ngắt qua ranh giới hai trang vật lý liên tiếp.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - **Embedding model:** Model thực chạy local `google/embeddinggemma-2` (**768 chiều**, `sentence-transformers 6.3.0`, `transformers 5.22.2`, `torch 2.15.0+cpu`). Xử lý bất đối xứng theo cấu hình gốc của model: văn bản chunk dùng prompt `document` (`"title: none | text: "`), câu hỏi dùng prompt `query` (`"task: search result | query: "`), chuẩn hóa vector đơn vị (`normalize_embeddings=True`). Không sử dụng hay fallback sang vector ngẫu nhiên/mock.
  - **Vector store:** PostgreSQL `16.16` + extension `pgvector 0.8.7` chạy trên Docker (`127.0.0.1:55433`), truy cập qua `psycopg 3.3.8`. Lưu 3 bảng độc lập / chiến lược `A`, `B`, `C` với khóa chính ổn định `(strategy, chunk_id)` và cơ chế `ON CONFLICT ... DO UPDATE` kết hợp xóa chunk cũ theo `(strategy, document_id)` để nạp lại không bị trùng lặp (idempotent).
  - **Metric:** Cosine distance (`<=>`, trả về điểm tương đồng `1 - cosine_distance`), tìm kiếm chính xác (exact search) và có tạo chỉ mục HNSW (`vector_cosine_ops`).
  - **Chi phí:** `0 USD` (chạy local hoàn toàn trên CPU; không phát sinh phí API).
  - **Lệnh chạy:**
    ```powershell
    cd starter
    docker compose -p day6_student_starter up -d --wait
    python scripts/check_setup.py
    python scripts/run_lab6_step4.py --repo ".."
    python -m src.run --split dev
    python -m src.run --split test --config "results/step5_dev_20261113T115144_309787Z/run_config.json"
    python scripts/verify_metadata.py
    ```
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - Mỗi chunk lưu đủ `document_id`, `source`, `page` (số trang PDF vật lý 1-based) và trường lọc bổ sung `section` (kiểu chuỗi, ví dụ `"1.3: Primary Sources"`, `"3.3: Lipids"`, `"3.4: Proteins"`, `"3.E: Biological Macromolecules (Exercises)"`).
  - Nguồn giá trị `section`: Xác định từ ranh giới dòng footer kết thúc từng mục (`"This page titled <section> is shared under..."`) in trực tiếp trong PDF gốc của LibreTexts. Chọn `section` vì tài liệu giáo trình có cấu trúc mục rõ ràng, cho phép thu hẹp phạm vi truy xuất theo đúng chủ đề con.

## Cấu hình và benchmark
- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **Chiến lược A (`fixed_size`):** Cắt cửa sổ cố định `size = 500` ký tự, `overlap = 50` ký tự trên từng trang; lưu metadata `document_id, source, page, section`; truy xuất **không lọc** (`filters = None`).
  - **Chiến lược B (`by_paragraph`):** Gom theo đoạn văn (`\n\n`) và ranh giới câu (`. ? !`) với kích thước tối đa `max_size = 1000` ký tự, không cắt ngang từ; lưu cùng metadata; truy xuất **không lọc** (`filters = None`).
  - **Chiến lược C (`by_paragraph` + metadata filter):** Dùng **cùng tập chunk và cùng vector embedding với B**; khác biệt duy nhất là khi câu hỏi đầu vào có trường `filter` (`{"section": "..."}`), truy vấn SQL áp dụng mệnh đề `WHERE metadata->>'section' = %(section)s` trước khi xếp hạng cosine (với câu hỏi `filter = null`, C truy xuất không lọc giống B).
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - Bộ câu hỏi tại `benchmark/questions.json` gồm **20 câu** được thiết kế và khóa trước khi chạy thử nghiệm: **15 câu `dev`** (`q01`–`q15`) và **5 câu `test`** (`q16`–`q20`).
  - Gồm 6 câu trực tiếp (`truc_tiep`), 7 câu diễn đạt lại (`dien_dat_lai`), 3 câu điều kiện/ngoại lệ (`dieu_kien_ngoai_le`), và **4 câu kiểm tra metadata filter** (`metadata_filter`: `q05`, `q11`, `q13` ở `dev` và `q20` ở `test`).
  - Tất cả `20/20` đoạn `evidence_quote` đã được kiểm chứng bằng script tồn tại nguyên văn trên đúng `gold_page` của `gold_source_id` sau khi chuẩn hóa NFC.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:**
  - Chốt ở Bước 2 (trước khi chạy `dev` và `test`): Ưu tiên chiến lược có **`dev Evidence Hit@3` cao nhất** $\rightarrow$ nếu bằng nhau, chọn chiến lược có **`dev Hit@1` cao hơn** $\rightarrow$ nếu vẫn bằng nhau, ưu tiên chiến lược có **Coherence/Grounding tốt hơn, hỗ trợ lọc phạm vi khi có yêu cầu (`filter`) và tốn ít tài nguyên lưu trữ (số chunk) hơn**.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian (embed + store) | Chi phí |
|---|---|---:|---:|---:|---:|---:|
| **A** | `dev` | `10/15` (66.7%) | `13/15` (86.7%) | 319 | `237.65s + 0.70s` | `0 USD` |
| **B** | `dev` | `14/15` (93.3%) | `15/15` (100.0%) | 171 | `179.65s + 0.34s` | `0 USD` |
| **C** | `dev` | `14/15` (93.3%) | `15/15` (100.0%) | 171 | `dùng lại vector B + 0.32s` | `0 USD` |
| **A** | `test` | `4/5` (80.0%) | `4/5` (80.0%) | 319 | *(đã nạp ở bước 4)* | `0 USD` |
| **B** | `test` | `5/5` (100.0%) | `5/5` (100.0%) | 171 | *(đã nạp ở bước 4)* | `0 USD` |
| **C** | `test` | `5/5` (100.0%) | `5/5` (100.0%) | 171 | *(đã nạp ở bước 4)* | `0 USD` |

| Strategy | Coherence trung bình /2 (`n=10`) | Metadata đủ và đúng (`n/N`) | Filter tuân thủ (`n/N` hoặc `N/A`) | Grounding 0/1/2 (số câu) và trung bình /2 (`n=5`) |
|---|---:|---:|---|---|
| **A** | `1.10 / 2` (`0/9/1`) | `15/15` (100%) | `N/A` (không áp filter) | `0 / 1 / 4` — **`1.80 / 2`** |
| **B** | `1.80 / 2` (`0/2/8`) | `15/15` (100%) | `N/A` (không áp filter) | `0 / 0 / 5` — **`2.00 / 2`** |
| **C** | `1.80 / 2` (`0/2/8`) | `15/15` (100%) | `1/1` câu (`3/3` bản ghi của `q20`) | `0 / 0 / 5` — **`2.00 / 2`** |

- **Đường dẫn trace, nhãn audit và cách chọn mẫu:**
  - Trace `dev` và `test`: `starter/results/step5_dev_20261113T115144_309787Z/traces_dev.json` và `starter/results/step5_test_20261113T115434_648655Z/traces_test.json`.
  - Nhãn audit 5 khía cạnh: `starter/results/step6_ai_review/` (`audit_coherence.csv`, `audit_metadata.csv`, `audit_grounding.csv`, `audit_summary.md`, `audit_filled.xlsx`).
  - Đối chiếu độc lập Metadata với PDF gốc: `starter/results/metadata_verification/metadata_verification.csv` (sinh bởi `starter/scripts/verify_metadata.py`).
  - Cách chọn mẫu Coherence: Chọn cố định chunk đầu tiên trên 10 trang vật lý đầu tiên của corpus đã sắp xếp (`openstax_1`, trang `12–21`) trước khi xem điểm truy xuất.

## Phân tích và kết luận
- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**
  - **A vs B (Tác động của chunking):** Việc chuyển từ cắt cố định 500 ký tự (A) sang cắt theo đoạn/câu tối đa 1000 ký tự (B) giúp giảm số chunk từ `319` xuống `171` (`-46.4%`), giảm thời gian tính embedding từ `237.65s` xuống `179.65s`, nâng Coherence từ `1.10/2` lên `1.80/2`, và tăng `Evidence Hit@3` từ `13/15` lên `15/15` (dev) và từ `4/5` lên `5/5` (test).
  - **2 ví dụ lỗi cụ thể của Chiến lược A:**
    1. **`q17` (`test`, nguồn `openstax_1`, trang `16`):** Câu hỏi hỏi về khảo sát BBC 2015–2016 tại 18 quốc gia. Ở Chiến lược A, câu bằng chứng bị cắt đôi giữa `openstax_1_p16_fix_0` (kết thúc ở `"respondents believed"`) và `openstax_1_p16_fix_1` (bắt đầu cụt từ `"ound that"`), làm không có chunk đơn lẻ nào chứa đủ bằng chứng và mất ngữ cảnh giới thiệu cuộc khảo sát (Hit@3 = False, Grounding = `1/2`). Ở Chiến lược B, `openstax_1_p16_para_0` giữ nguyên vẹn cả đoạn nên đạt Hit@1 và Grounding = `2/2`.
    2. **`q09` (`dev`, nguồn `openstax_2`, trang `100`) và `q13` (`dev`, nguồn `openstax_2`, trang `110`):** Bằng chứng gồm 2 câu liên tiếp (về tế bào dự trữ mỡ `adipocytes` ở động vật có vú và hạt ở thực vật tại `q09`; hoặc đột biến chuỗi $\beta$ hemoglobin thay thế `glutamic acid` bằng `valine` tại `q13`) bị cửa sổ 500 ký tự của A cắt qua 2 chunk liên tiếp, dẫn đến trượt `Evidence Hit@3` theo tiêu chí nghiêm ngặt (một chunk phải chứa trọn vẹn `evidence_quote`).
  - **B vs C (Tác động của metadata filter):** B và C đạt cùng điểm Hit@1/Hit@3 trên bộ câu hỏi hiện tại vì vector embedding của `google/embeddinggemma-2` đã xếp hạng chunk đúng lên top-1. Tuy nhiên, tại câu hỏi có filter `q20` (`section = "3.E: Biological Macromolecules (Exercises)"`), Chiến lược B trả về top-3 gồm trang `125, 100, 123` (lẫn trang `100` thuộc mục `3.3: Lipids`), trong khi Chiến lược C loại bỏ hoàn toàn các chunk ngoài mục `3.E` và trả về `125, 123, 121` (`3/3` bản ghi tuân thủ filter).
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - **Lựa chọn:** Chọn **Chiến lược C** (chunk theo đoạn/câu `<= 1000` ký tự kết hợp lọc `section` khi có filter) cho hệ thống truy xuất trên corpus này.
  - **Đánh đổi:** Chunk của B/C dài hơn trung bình (`776.3` ký tự so với `457.0` của A) nên mỗi top-3 chứa nhiều văn bản hơn và đôi khi kèm các câu hỏi ôn tập lân cận trên cùng trang (như ở trang 125 của `q20`); ngoài ra nếu người dùng truyền sai nhãn `section` vào filter thì C sẽ không tìm thấy kết quả. Do đó chỉ bật filter ở C khi ngữ cảnh `section` đầu vào đáng tin cậy.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Tập `test` chỉ gồm 5 câu (1 câu có filter), mẫu Coherence chỉ khảo sát 10 trang đầu của `openstax_1` — quy mô mẫu nhỏ nên kết quả `5/5` trên `test` chỉ mang tính minh họa trên corpus đã chọn, **không tuyên bố là chiến lược tối ưu tổng quát** cho mọi loại tài liệu.
  - Nhãn audit được tác giả thực hiện với sự hỗ trợ của công cụ AI (Claude/ChatGPT) để soạn thảo lý do và kiểm tra chéo với PDF gốc, nên có thể tồn tại thiên lệch xác nhận của tác giả.
  - Nhãn `section` đang gán theo đơn vị trang vật lý nên chưa tách riêng được hai mục cùng nằm trên một trang chuyển tiếp; phép đo `approx_tokens` trong log thống kê đang đếm số từ theo khoảng trắng, không phải tokenizer của Gemma.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Dùng parser nhận diện cấu trúc DOM/heading trực tiếp (như `docling`) để nối các câu bị ngắt qua ranh giới hai trang PDF và gắn nhãn `section` ở cấp độ từng đoạn thay vì từng trang; loại bỏ triệt để chuỗi rác HTML còn sót từ LibreTexts; mở rộng kích thước tập `test` và thử nghiệm kết hợp tìm kiếm từ khóa (BM25 + dense vector hybrid search).
