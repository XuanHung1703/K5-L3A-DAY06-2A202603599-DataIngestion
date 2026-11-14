"""Step 5: query stored vectors, evaluate evidence and preserve traces."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from .evaluation import evaluate_query, summarize


def validate_questions(questions: list[dict]) -> None:
    seen = set()
    for question in questions:
        for field in ("id", "question", "expected_answer", "gold_source_id", "evidence_quote"):
            if not isinstance(question.get(field), str) or not question[field].strip():
                raise ValueError(f"Missing or empty question field: {field}")
        if question["id"] in seen:
            raise ValueError(f"Duplicate question ID: {question['id']}")
        seen.add(question["id"])
        if type(question.get("gold_page")) is not int or question["gold_page"] <= 0:
            raise ValueError(f"Invalid gold_page: {question['id']}")
        filters = question.get("filter") or {}
        if not isinstance(filters, dict):
            raise ValueError("filter must be a dictionary or null")
        for key, value in filters.items():
            if key not in {"document_id", "source", "page", "section", "chapter"}:
                raise ValueError(f"Unsupported filter: {key}")
            if key == "page":
                if type(value) is not int or value <= 0:
                    raise ValueError("page filter must be a positive integer")
            elif not isinstance(value, str) or not value:
                raise ValueError(f"Invalid {key} filter")


def snapshot_database(database_url: str) -> dict:
    """Fingerprint corpus/vectors and counts without changing the database."""
    import psycopg
    from psycopg import sql

    result = {}
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for strategy in ("A", "B", "C"):
            rows = connection.execute(sql.SQL(
                "SELECT chunk_id, document_id, source, page, text, metadata::text, "
                "embedding::text FROM {} ORDER BY chunk_id"
            ).format(sql.Identifier(f"chunks_{strategy.lower()}")))
            digest = hashlib.sha256()
            count = 0
            for row in rows:
                digest.update(json.dumps(row, ensure_ascii=False).encode("utf-8"))
                digest.update(b"\n")
                count += 1
            if count == 0:
                raise ValueError(f"chunks_{strategy.lower()} is empty; finish step 4 first")
            result[strategy] = {"count": count, "sha256": digest.hexdigest()}
    if result["B"] != result["C"]:
        raise ValueError("B and C must contain identical chunks and vectors")
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--config", type=Path, help="Frozen run_config.json from a successful dev run")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-root", type=Path, help="Default: starter/results")
    args = parser.parse_args()
    if args.split == "test" and args.config is None:
        parser.error("Test requires --config pointing to a completed dev run_config.json")

    from dotenv import load_dotenv
    from .embeddings import MyEmbedder
    from .store import PgVectorStore

    repo = args.repo.resolve()
    starter = repo / "starter"
    load_dotenv(starter / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing")
    benchmark_path = repo / "benchmark" / "questions.json"
    benchmark_bytes = benchmark_path.read_bytes()
    benchmark = json.loads(benchmark_bytes)
    if not isinstance(benchmark, list):
        raise ValueError("Benchmark must be a list")
    split_counts = {split: sum(q.get("split") == split for q in benchmark) for split in ("dev", "test")}
    if len(benchmark) < 20 or split_counts["dev"] < 15 or split_counts["test"] < 5:
        raise ValueError("Benchmark requires at least 20 questions, 15 dev and 5 test")
    if sum(split_counts.values()) != len(benchmark):
        raise ValueError("Every question must belong to dev or test")
    if (sum(bool(q.get("filter")) for q in benchmark) < 3
            or not any(q.get("split") == "test" and q.get("filter") for q in benchmark)):
        raise ValueError("Benchmark requires at least 3 filtered questions, including 1 test")
    questions = [question for question in benchmark if question.get("split") == args.split]
    validate_questions(questions)
    source_dir = Path(__file__).resolve().parent
    settings = {
        "model": "google/embeddinggemma-2", "dimensions": 768, "top_k": 3,
        "document_prompt": "Document", "query_prompt": "SearchQuery",
        "ranking": "exact_cosine", "filter_policy": "C uses only the supplied question filter",
        "evidence_normalization": "Unicode NFC and collapsed whitespace, case-sensitive",
        "benchmark_sha256": hashlib.sha256(benchmark_bytes).hexdigest(),
        "code_sha256": {name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
                        for name in ("evaluation.py", "run.py", "embeddings.py", "store.py")},
        "versions": {name: version(name) for name in
                     ("sentence-transformers", "transformers", "psycopg")},
        "database_snapshot": snapshot_database(database_url),
    }
    if args.split == "test":
        frozen = json.loads(args.config.read_text(encoding="utf-8"))
        if frozen.get("split") != "dev" or frozen.get("status") != "completed":
            raise ValueError("Reference config must come from a completed dev run")
        if frozen.get("settings") != settings:
            raise ValueError("Configuration, code, benchmark or vectors changed since dev; refusing test")

    started = datetime.now(timezone.utc)
    output_root = args.output_root.resolve() if args.output_root else starter / "results"
    output = output_root / (f"step5_{args.split}_" + started.strftime("%Y%m%dT%H%M%S_%fZ"))
    output.mkdir(parents=True, exist_ok=False)

    def save(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    config = {"split": args.split, "status": "running", "started_at_utc": started.isoformat(),
              "settings": settings, "question_count": len(questions),
              "reference_dev_config": str(args.config.resolve()) if args.config else None}
    save("run_config.json", config)
    total_start = perf_counter()
    embedder = MyEmbedder(settings["model"])
    store = PgVectorStore(database_url, embedder.dimensions)
    traces = []
    for index, question in enumerate(questions, start=1):
        print(f"{args.split}: {index}/{len(questions)} ({question['id']})", flush=True)
        start = perf_counter()
        vector = embedder.embed_query(question["question"])
        embed_seconds = perf_counter() - start
        for strategy in ("A", "B", "C"):
            filters = (question.get("filter") or {}) if strategy == "C" else {}
            start = perf_counter()
            hits = store.search(strategy, vector, top_k=3, filters=filters or None)
            search_seconds = perf_counter() - start
            for hit in hits:
                for key, value in filters.items():
                    actual = hit.get(key) if key in {"document_id", "source", "page"} else hit["metadata"].get(key)
                    if actual != value:
                        raise ValueError(f"Filter violation: {question['id']}, {strategy}, {key}")
            trace = evaluate_query(question, hits)
            trace.update({"strategy": strategy, "applied_filter": filters,
                          "filter_applied": bool(filters), "query_embed_seconds": embed_seconds,
                          "search_seconds": search_seconds})
            traces.append(trace)
        save(f"traces_{args.split}.json", traces)
    if snapshot_database(database_url) != settings["database_snapshot"]:
        raise ValueError("Stored corpus changed during evaluation; rerun with a stable database")
    summary = summarize(traces)
    save("summary.json", summary)
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary["groups"][0]))
        writer.writeheader()
        writer.writerows(summary["groups"])
    config.update({"status": "completed", "total_seconds": perf_counter() - total_start})
    save("run_config.json", config)
    for row in summary["groups"]:
        print(f"{row['strategy']} {row['split']}: Hit@1={row['hit_at_1_count']}/{row['total']}, "
              f"Hit@3={row['hit_at_3_count']}/{row['total']}")
    print(f"Step 5 {args.split} OK")
    print(f"Results: {output}")
    if args.split == "dev":
        print("After reviewing dev and freezing the configuration, run:")
        print(f'python -m src.run --split test --config "{output / "run_config.json"}"')


if __name__ == "__main__":
    main()
