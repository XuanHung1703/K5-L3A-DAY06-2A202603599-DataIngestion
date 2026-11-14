"""Independent check of retrieval metadata against the source PDFs.

For every top-3 record of the TEST traces (strategies A/B/C) it verifies:
  source_ok  - document_id/source is a source_id listed in data/manifest.json
  page_ok    - the chunk text really occurs on the physical PDF page named in metadata
  section_ok - the stored section matches the official LibreTexts section footer boundary
               extracted directly from the PDF ("This page titled <section> is shared under...")
  filter_ok  - strategy C only, for questions with a filter: the record's section equals the
               requested value (A/B apply no filter, so N/A)

Run from starter/:
    python scripts/verify_metadata.py
"""
import csv
import glob
import json
import re
import unicodedata
from pathlib import Path

import pypdfium2 as pdfium

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "starter" / "results"
OUT_DIR = RESULTS / "metadata_verification"
PDFS = {"openstax_1": REPO / "data" / "OpenStax1.pdf", "openstax_2": REPO / "data" / "OpenStax2.pdf"}

FOOTER = re.compile(
    r"This page titled (.+?) is shared under (?:a |an )?(.+?) license and was authored, remixed, and/or curated by ([^.]*)\.?",
    re.S,
)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", FOOTER.sub(" ", text)).strip()


def section_by_pdf_footers(pdf, first: int, last: int) -> dict[int, str]:
    """Derive each page's section from LibreTexts section-closing footers inside [first, last]."""
    footer_on_page: dict[int, str] = {}
    for p in range(first, last + 1):
        raw = re.sub(r"\s+", " ", unicodedata.normalize("NFC", pdf[p - 1].get_textpage().get_text_bounded()))
        m = FOOTER.search(raw)
        if m:
            title = m.group(1).strip()
            # Normalize sub-assessment footers 1.7.1/1.7.2/1.7.3 to parent section 1.7: Assessments
            if title.startswith("1.7."):
                title = "1.7: Assessments"
            footer_on_page[p] = title

    # In LibreTexts exports, a section spans from (previous_footer_page + 1) up to its closing footer_page
    result: dict[int, str] = {}
    sorted_end_pages = sorted(footer_on_page.keys())
    start_p = first
    for end_p in sorted_end_pages:
        sec_title = footer_on_page[end_p]
        for p in range(start_p, end_p + 1):
            result[p] = sec_title
        start_p = end_p + 1
    return result


def main() -> None:
    manifest = json.loads((REPO / "data" / "manifest.json").read_text(encoding="utf-8"))
    sources = {s["source_id"]: s for s in manifest["sources"]}
    pdfs, texts, sec = {}, {}, {}
    for sid, src in sources.items():
        pdfs[sid] = pdfium.PdfDocument(str(PDFS[sid]))
        pages = src["content_pages"]
        first, last = min(pages), max(pages)
        texts[sid] = {p: norm(pdfs[sid][p - 1].get_textpage().get_text_bounded()) for p in pages}
        sec[sid] = section_by_pdf_footers(pdfs[sid], first, last)

    trace_file = glob.glob(str(RESULTS / "step5_test_*" / "traces_test.json"))[0]
    traces = json.loads(Path(trace_file).read_text(encoding="utf-8"))
    rows = []
    for tr in traces:
        req = tr.get("requested_filter") or {}
        for h in tr["hits"][:3]:
            sid, page = h["document_id"], h["page"]
            md = h.get("metadata", {})
            label = md.get("section", "")
            derived = sec.get(sid, {}).get(page, "unknown")
            source_ok = sid in sources and h.get("source") == sid and md.get("document_id") == sid
            page_ok = page in texts.get(sid, {}) and norm(h["text"]) in texts[sid][page]
            section_ok = bool(label) and label == derived
            if req and tr["strategy"] == "C":
                filter_ok = all(md.get(k) == v for k, v in req.items())
                filter_cell = str(filter_ok)
            else:
                filter_ok, filter_cell = None, "N/A"
            rows.append({
                "strategy": tr["strategy"], "question_id": tr["question_id"], "rank": h["rank"],
                "document_id": sid, "page": page, "stored_section": label,
                "pdf_footer_section": derived,
                "source_ok": source_ok, "page_ok": page_ok, "section_ok": section_ok,
                "filter_ok": filter_cell,
                "all_ok": source_ok and page_ok and section_ok and (filter_ok is not False),
            })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "metadata_verification.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    summary = {"trace_file": str(Path(trace_file).relative_to(REPO)), "method": "PDF text + LibreTexts footer cross-check", "by_strategy": {}}
    for strat in ("A", "B", "C"):
        rs = [r for r in rows if r["strategy"] == strat]
        fl = [r for r in rs if r["filter_ok"] != "N/A"]
        summary["by_strategy"][strat] = {
            "records": len(rs), "all_ok": sum(r["all_ok"] for r in rs),
            "source_ok": sum(r["source_ok"] for r in rs), "page_ok": sum(r["page_ok"] for r in rs),
            "section_ok": sum(r["section_ok"] for r in rs),
            "filter_questions_records": len(fl), "filter_ok": sum(r["filter_ok"] == "True" for r in fl),
        }
    summary["mismatches"] = [r for r in rows if not r["all_ok"]]
    (OUT_DIR / "metadata_verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
