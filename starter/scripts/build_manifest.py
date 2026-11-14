"""Build data/manifest.json for the two selected OpenStax PDFs (pages 12-42 of OpenStax1.pdf and 97-125 of OpenStax2.pdf).

Run from starter/:  python scripts/build_manifest.py
"""
import json
import re
import unicodedata
from pathlib import Path
import pypdfium2 as pdfium

REPO = Path(__file__).resolve().parents[2]
OUT_PATH = REPO / "data" / "manifest.json"
MIN_CHARS = 100

FOOTER = re.compile(
    r"This page titled .+? is shared under .+? license and was authored, remixed, and/or curated by [^.]*\.?",
    re.S,
)

SOURCES_SPEC = [
    {
        "source_id": "openstax_1",
        "title": "World History II: From 1400 (OpenStax)",
        "source_path_or_url": "https://commons.libretexts.org/book/human-236231",
        "license_or_permission": "CC BY 4.0 (https://commons.libretexts.org/)",
        "accessed_at": "2026-11-13",
        "pdf_file": REPO / "data" / "OpenStax1.pdf",
        "page_range": (12, 42),
    },
    {
        "source_id": "openstax_2",
        "title": "General Biology",
        "source_path_or_url": "https://commons.libretexts.org/book/bio-1764",
        "license_or_permission": "CC BY 4.0 (https://commons.libretexts.org/)",
        "accessed_at": "2026-11-13",
        "pdf_file": REPO / "data" / "OpenStax2.pdf",
        "page_range": (97, 125),
    },
]


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = FOOTER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    sources_out = []
    for spec in SOURCES_SPEC:
        pdf = pdfium.PdfDocument(str(spec["pdf_file"]))
        first, last = spec["page_range"]
        valid_pages, total_chars = [], 0
        for p in range(first, last + 1):
            n = len(clean(pdf[p - 1].get_textpage().get_text_bounded()))
            if n >= MIN_CHARS:
                valid_pages.append(p)
                total_chars += n
        sources_out.append({
            "source_id": spec["source_id"],
            "title": spec["title"],
            "source_path_or_url": spec["source_path_or_url"],
            "license_or_permission": spec["license_or_permission"],
            "accessed_at": spec["accessed_at"],
            "physical_pages_total": len(pdf),
            "content_page_count": len(valid_pages),
            "content_pages": valid_pages,
            "char_count": total_chars,
        })

    manifest = {
        "corpus_note": (
            "Pages counted = physical PDF pages (1-based) inside the selected ranges "
            "(pages 12-42 of openstax_1 and pages 97-125 of openstax_2) with >= 100 characters "
            "of text after Unicode NFC normalization, whitespace collapsing, and removal of the "
            "LibreTexts license footer. Cover, front matter, table of contents, blank/near-empty "
            "pages (page 38 of openstax_1), reference-only pages and appendices are not counted."
        ),
        "sources": sources_out,
    }
    OUT_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Updated", OUT_PATH)


if __name__ == "__main__":
    main()
