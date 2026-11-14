"""Evaluate retrieved evidence without generating an LLM answer."""
import re
import unicodedata
from typing import Any


def normalize_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = normalize_evidence(question["evidence_quote"])
    if not evidence:
        raise ValueError("Gold evidence must not be empty")
    assessed = []
    for rank, hit in enumerate(hits[:3], start=1):
        metadata = hit.get("metadata") or {}
        source_id = hit.get("document_id", metadata.get("document_id"))
        if source_id is None:
            source_id = hit.get("source", metadata.get("source"))
        source_match = source_id == question["gold_source_id"]
        page_match = hit.get("page", metadata.get("page")) == question["gold_page"]
        evidence_match = evidence in normalize_evidence(hit["text"])
        assessed.append({
            **hit, "rank": rank, "source_match": source_match,
            "page_match": page_match, "evidence_match": evidence_match,
            "is_hit": source_match and page_match and evidence_match,
        })
    return {
        "question_id": question["id"], "split": question["split"],
        "question": question["question"], "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"], "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "requested_filter": question.get("filter") or {}, "hits": assessed,
        "hit_at_1": bool(assessed and assessed[0]["is_hit"]),
        "hit_at_3": any(hit["is_hit"] for hit in assessed),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen = set()
    for trace in traces:
        identity = (trace["strategy"], trace["split"], trace["question_id"])
        if identity in seen:
            raise ValueError(f"Duplicate trace: {identity}")
        seen.add(identity)
        groups.setdefault(identity[:2], []).append(trace)
    rows = []
    for (strategy, split), entries in sorted(groups.items()):
        total = len(entries)
        hits1 = sum(entry["hit_at_1"] for entry in entries)
        hits3 = sum(entry["hit_at_3"] for entry in entries)
        rows.append({
            "strategy": strategy, "split": split, "total": total,
            "hit_at_1_count": hits1, "hit_at_1": hits1 / total,
            "hit_at_3_count": hits3, "hit_at_3": hits3 / total,
        })
    return {"groups": rows}
