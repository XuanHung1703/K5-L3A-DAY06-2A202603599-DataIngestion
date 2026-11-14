# Lab 6 — Tổng hợp Audit 5 khía cạnh

Người chấm: Nguyễn Xuân Hùng (AI hỗ trợ soạn thảo, đã đối chiếu PDF gốc)
Ngày cập nhật: 2026-11-14T09:40:00+07:00

| Chiến lược | Coherence trung bình /2 (`n=10`) | Metadata đủ và đúng (`n/N`) | Filter tuân thủ (`n/N` câu có filter) | Grounding 0/1/2 (số câu) & trung bình /2 (`n=5`) |
|---|---:|---:|---:|---:|
| **A** | `1.10` (`0/9/1`) | `15/15` | `N/A` (không áp filter) | `0/1/4` — `1.80` |
| **B** | `1.80` (`0/2/8`) | `15/15` | `N/A` (không áp filter) | `0/0/5` — `2.00` |
| **C** | `1.80` (`0/2/8`) | `15/15` | `1/1` câu (`3/3` bản ghi top-3 của `q20`) | `0/0/5` — `2.00` |

## 1. A–B: Tác động của chiến lược chunking
- Chiến lược A (`fixed_size=500, overlap=50`) tạo **319 chunk**; Chiến lược B (`by_paragraph, max_size=1000`) tạo **171 chunk**.
- Trên 10 vị trí cố định đầu tiên của corpus (trang 12–21 của `openstax_1`), điểm Coherence trung bình của A là **1.10/2** (9/10 mẫu bị cắt dở câu hoặc cắt ngang từ ở cuối cửa sổ 500 ký tự) so với **1.80/2** của B (8/10 mẫu đạt 2/2 nhờ giữ trọn ranh giới đoạn và câu; chỉ 2 mẫu trang 17 và 18 đạt 1/2 do câu đầu trang nối tiếp từ trang vật lý trước đó).
- Độ chính xác truy xuất tăng từ A sang B: trên `dev`, `Hit@1` tăng từ `10/15` lên `14/15`, `Evidence Hit@3` tăng từ `13/15` lên `15/15`; trên `test`, `Hit@1` và `Evidence Hit@3` tăng từ `4/5` lên `5/5`.

## 2. B–C: Tác động của metadata filter
- Chiến lược C dùng chung tập chunk và vector của B, chỉ thêm điều kiện lọc `WHERE metadata->>'section' = ...` khi câu hỏi đầu vào cung cấp `filter`.
- Trên bộ câu hỏi hiện tại, `Hit@1` và `Evidence Hit@3` của B và C bằng nhau (`14/15` và `15/15` trên `dev`; `5/5` và `5/5` trên `test`).
- Tuy nhiên, ở câu test có filter (`q20`, lọc `section = "3.E: Biological Macromolecules (Exercises)"`), B trả về các trang `125, 100, 123` (trong đó trang `100` thuộc mục `3.3: Lipids`), còn C lọc bỏ hoàn toàn trang `100` và chỉ trả về các trang `125, 123, 121` đều thuộc đúng mục `3.E`.

## 3. Tính hữu dụng và hạn chế của Metadata
- **Hữu dụng:** `document_id` / `source` và `page` giúp truy vết chính xác về trang vật lý trong PDF gốc (`15/15` bản ghi top-3 ở mỗi chiến lược khớp văn bản trang PDF và ranh giới footer LibreTexts qua kiểm chứng tại `starter/scripts/verify_metadata.py`). Trường `section` giúp Chiến lược C thu hẹp không gian tìm kiếm đúng phạm vi chương/mục khi người dùng cung cấp ngữ cảnh.
- **Hạn chế:** Nhãn `section` đang được gán ở cấp độ trang vật lý dựa trên dòng footer kết thúc mục của LibreTexts; nếu một trang chuyển giao chứa phần cuối của mục trước và phần đầu của mục sau thì các chunk trên trang đó vẫn mang cùng một nhãn `section`.

## 4. Ví dụ lỗi và đánh đổi (Trade-offs)
- **Lỗi cắt ngữ cảnh ở Chiến lược A (`q17` trên `test`, `openstax_1` trang 16):** Chunk top-1 (`openstax_1_p16_fix_1`) bắt đầu cụt giữa từ `"ound that"` (bị cắt mất cụm `"A BBC poll in 2015–2016 surveyed eighteen countries and f"` ở chunk trước), khiến bằng chứng thiếu tên cuộc khảo sát BBC và phạm vi 18 quốc gia (Grounding chỉ đạt `1/2`, và trượt `Evidence Hit@3` tự động). Chiến lược B giữ trọn cả đoạn trong một chunk (`openstax_1_p16_para_0`) nên đạt `2/2`.
- **Lỗi chia tách mệnh đề dài ở Chiến lược A (`q09` trang 100 và `q13` trang 110 của `openstax_2` trên `dev`):** Đoạn bằng chứng gồm 2 câu liên tiếp bị cửa sổ 500 ký tự cắt đôi qua 2 chunk nên không chunk đơn lẻ nào chứa trọn `evidence_quote`.
- **Đánh đổi:** Chiến lược B/C giảm 46.4% số chunk (`171` so với `319`) và giảm 24.4% thời gian tạo embedding (`179.65s` so với `237.65s`), đồng thời đạt Coherence và Hit@3 cao hơn; đổi lại độ dài trung bình mỗi chunk lớn hơn (`776.3` so với `457.0` ký tự), có thể kèm thêm câu hỏi ôn tập lân cận trên cùng trang (như ở `q20` trang 125).

## 5. Giới hạn
- Người chấm là tác giả bài lab (có sử dụng AI hỗ trợ soạn thảo nhận xét và đã đối chiếu lại với PDF gốc), nên vẫn tồn tại nguy cơ thiên lệch xác nhận (confirmation bias).
- Tập `test` chỉ gồm 5 câu hỏi (trong đó có 1 câu có filter) và mẫu Coherence gồm 10 vị trí đầu tiên trên `openstax_1`; vì vậy chỉ kết luận trong phạm vi corpus và benchmark của bài thực hành, không suy rộng thành kết luận tổng quát cho mọi bộ dữ liệu.
