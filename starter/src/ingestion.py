"""Read and normalize source data."""
from pathlib import Path
import re
import unicodedata
import pypdfium2 as pdfium
from .models import DocumentPage

# Regex xóa dòng footer bản quyền lặp lại ở chân mỗi trang LibreTexts
FOOTER_PATTERN = re.compile(
    r"This page titled .+? is shared under .+? license and was authored, remixed, and/or curated by [^.]*\.?",
    re.DOTALL,
)

# =====================================================================
# [PHẦN BẠN CẦN ĐIỀN 1]: Ngưỡng ký tự tối thiểu để 1 trang được tính là hợp lệ
# - Cách tìm: Xem lại quy tắc bạn đã ghi trong "corpus_note" của file data/manifest.json
#   (trang có ít hơn bao nhiêu ký tự thì bị coi là trang trống/gần trống?).
# =====================================================================
MIN_PAGE_CHARS: int = 100  # <--- [ĐIỀN SỐ VÀO ĐÂY, ví dụ: 100]


# =====================================================================
# [PHẦN BẠN CẦN ĐIỀN 2]: Bảng ánh xạ khoảng trang -> tên mục (section)
# dùng để gắn nhãn metadata["section"] cho từng trang, phục vụ câu hỏi có filter.
# - Cách tìm: Xem trường "filter" của 4 câu hỏi (q05, q11, q13, q20) trong
#   file benchmark/questions.json hoặc mở PDF xem mục đó bắt đầu từ trang nào đến trang nào.
# - Cấu trúc mỗi dòng: (trang_bắt_đầu, trang_kết_thúc, "Tên section")
# =====================================================================
SECTION_RANGES: dict[str, list[tuple[int, int, str]]] = {
    "openstax_1": [
        (12, 12, "Chapter 1: Understanding the Past"),
        (13, 13, "1.1: Introduction"),
        (14, 18, "1.2: Developing a Global Perspective"),
        (19, 29, "1.3: Primary Sources"),
        (30, 35, "1.4: Causation and Interpretation in History"),
        (36, 36, "1.5: Key Terms"),
        (37, 37, "1.6: Section Summary"),
        (38, 41, "1.7: Assessments"),
        (42, 42, "Chapter 2: Exchange in East Asia and the Indian Ocean"),
    ],
    "openstax_2": [
        (97, 97, "3: Biological Macromolecules"),
        (98, 105, "3.3: Lipids"),
        (106, 114, "3.4: Proteins"),
        (115, 120, "3.5: Nucleic Acids"),
        (121, 125, "3.E: Biological Macromolecules (Exercises)"),
    ],
}


def get_section_for_page(document_id: str, page_num: int) -> str:
    """Tra cứu tên section từ bảng SECTION_RANGES theo document_id và số trang."""
    for start_page, end_page, section_title in SECTION_RANGES.get(document_id, []):
        if start_page <= page_num <= end_page:
            return section_title
    return "unknown"


def normalize_text(text: str) -> str:
    """Chuẩn hóa Unicode NFC, xóa footer LibreTexts, giữ ranh giới đoạn văn (\n\n)."""
    # 1. Chuẩn hóa Unicode về dựng sẵn (NFC)
    text = unicodedata.normalize("NFC", text)
    # 2. Xóa dòng footer bản quyền ở chân trang
    text = FOOTER_PATTERN.sub(" ", text)
    # 3. Chuẩn hóa xuống dòng (\r\n -> \n), giữ lại ngắt đoạn (\n\n) cho chunking B
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [re.sub(r"[ \t\n]+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]
    return "\n\n".join(paragraphs)


def load_pdf(
    path: Path,
    document_id: str,
    source: str,
    valid_pages: list[int] | None = None,
) -> tuple[list[DocumentPage], list[dict]]:
    """Đọc các trang PDF, chuẩn hóa văn bản, gắn metadata section và ghi log trang rỗng/lỗi.

    Trả về: (danh_sách_DocumentPage_hợp_lệ, danh_sách_log_trang_bị_loại)
    """
    pdf = pdfium.PdfDocument(str(path))
    pages_to_read = valid_pages if valid_pages is not None else list(range(1, len(pdf) + 1))

    loaded_pages: list[DocumentPage] = []
    skipped_log: list[dict] = []

    for page_num in pages_to_read:
        try:
            raw_text = pdf[page_num - 1].get_textpage().get_text_bounded()
            cleaned = normalize_text(raw_text)
            char_len = len(re.sub(r"\s+", " ", cleaned))

            if char_len < MIN_PAGE_CHARS:
                skipped_log.append({
                    "document_id": document_id,
                    "page": page_num,
                    "chars": char_len,
                    "reason": f"near-empty (< {MIN_PAGE_CHARS} chars)",
                })
                continue

            loaded_pages.append(
                DocumentPage(
                    document_id=document_id,
                    source=source,
                    page=page_num,
                    text=cleaned,
                    metadata={"section": get_section_for_page(document_id, page_num)},
                )
            )
        except Exception as exc:
            skipped_log.append({
                "document_id": document_id,
                "page": page_num,
                "chars": 0,
                "reason": f"read_error: {exc}",
            })

    return loaded_pages, skipped_log

