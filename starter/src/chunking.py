"""Implement fixed-size and structure-aware chunking."""
import re
from typing import Any
from .models import Chunk, DocumentPage

# =====================================================================
# [PHẦN BẠN CẦN ĐIỀN]: Thông số kích thước chunk cho Chiến lược A và B
# - Cách tìm: Xem bảng ví dụ 3 cấu hình ở mục 3 của file GUIDE.md (dòng 29-33):
#   + Chiến lược A (fixed_size): kích thước cố định (ví dụ 500 ký tự), overlap (ví dụ 50 ký tự).
#   + Chiến lược B & C (by_paragraph): gộp theo đoạn văn/heading, giới hạn kích thước tối đa
#     mỗi chunk (ví dụ 1000 ký tự) để không cắt ngang câu như Chiến lược A.
# =====================================================================
DEFAULT_FIXED_SIZE: int = 500
DEFAULT_OVERLAP: int = 50
DEFAULT_MAX_PARAGRAPH_SIZE: int = 1000


def fixed_size(
    page: DocumentPage,
    size: int = DEFAULT_FIXED_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Chiến lược A: Cắt văn bản thành các cửa sổ kích thước cố định (size) có chồng lặp (overlap)."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError(
            f"Thông số chưa điền hoặc không hợp lệ: size={size}, overlap={overlap}. "
            "Hãy điền DEFAULT_FIXED_SIZE (vd: 500) và DEFAULT_OVERLAP (vd: 50) trong chunking.py."
        )

    flat_text = re.sub(r"\s+", " ", page.text).strip()
    if not flat_text:
        return []

    chunks: list[Chunk] = []
    step = size - overlap
    start = 0
    chunk_idx = 0

    while start < len(flat_text):
        window = flat_text[start : start + size].strip()
        if window:
            chunks.append(
                Chunk(
                    chunk_id=f"{page.document_id}_p{page.page}_fix_{chunk_idx}",
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=window,
                    metadata=dict(page.metadata),
                )
            )
            chunk_idx += 1
        if start + size >= len(flat_text):
            break
        start += step

    return chunks


def by_paragraph(
    page: DocumentPage,
    max_size: int = DEFAULT_MAX_PARAGRAPH_SIZE,
) -> list[Chunk]:
    """Chiến lược B & C: Gom các đoạn văn/câu trọn vẹn cho đến ngưỡng max_size, không cắt ngang chữ."""
    if max_size <= 0:
        raise ValueError(
            f"Thông số chưa điền hoặc không hợp lệ: max_size={max_size}. "
            "Hãy điền DEFAULT_MAX_PARAGRAPH_SIZE (vd: 1000) trong chunking.py."
        )

    raw_paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
    # Tách tiếp các khối văn bản quá dài thành từng câu theo dấu chấm câu (. ? !)
    units: list[str] = []
    for para in raw_paragraphs:
        if len(para) <= max_size:
            units.append(para)
        else:
            sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", para) if s.strip()]
            units.extend(sentences)

    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_len = 0
    chunk_idx = 0

    def flush_chunk(text_block: str) -> None:
        nonlocal chunk_idx
        cleaned_block = text_block.strip()
        if cleaned_block:
            chunks.append(
                Chunk(
                    chunk_id=f"{page.document_id}_p{page.page}_para_{chunk_idx}",
                    document_id=page.document_id,
                    source=page.source,
                    page=page.page,
                    text=cleaned_block,
                    metadata=dict(page.metadata),
                )
            )
            chunk_idx += 1

    for unit in units:
        # Nếu bản thân 1 câu vẫn dài hơn max_size thì cắt theo khoảng trắng gần nhất
        while len(unit) > max_size:
            if current_parts:
                flush_chunk(" ".join(current_parts))
                current_parts, current_len = [], 0
            split_pos = unit.rfind(" ", 0, max_size)
            if split_pos <= 0:
                split_pos = max_size
            flush_chunk(unit[:split_pos])
            unit = unit[split_pos:].strip()

        added_len = len(unit) if not current_parts else len(unit) + 1
        if current_len + added_len <= max_size:
            current_parts.append(unit)
            current_len += added_len
        else:
            flush_chunk(" ".join(current_parts))
            current_parts = [unit]
            current_len = len(unit)

    if current_parts:
        flush_chunk(" ".join(current_parts))

    return chunks


def measure_chunks(chunks: list[Chunk]) -> dict[str, Any]:
    """Hàm tự động đo thống kê chunk (số chunk, phân bố độ dài, tổng ký tự, tổng token xấp xỉ)."""
    if not chunks:
        return {"chunk_count": 0, "total_chars": 0, "approx_tokens": 0, "min_len": 0, "avg_len": 0.0, "max_len": 0}

    lengths = [len(c.text) for c in chunks]
    total_chars = sum(lengths)
    approx_tokens = sum(len(c.text.split()) for c in chunks)
    return {
        "chunk_count": len(chunks),
        "total_chars": total_chars,
        "approx_tokens": approx_tokens,
        "min_len": min(lengths),
        "avg_len": round(total_chars / len(chunks), 1),
        "max_len": max(lengths),
    }

