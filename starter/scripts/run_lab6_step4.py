"""Run step 4 locally using the existing ingestion and chunking code."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
from time import perf_counter


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(
        r"D:\Lab\Lab6\K5-L3-Day06-DataIngestionEngineering"))
    args = parser.parse_args()
    repo = args.repo.resolve()
    starter = repo / "starter"
    sys.path.insert(0, str(starter))

    import psycopg
    from psycopg import sql
    from dotenv import load_dotenv
    from src.chunking import fixed_size, by_paragraph, measure_chunks
    from src.embeddings import MyEmbedder
    from src.ingestion import load_pdf
    from src.store import PgVectorStore

    load_dotenv(starter / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing from starter/.env")
    # Preflight existing tables without making schema changes.
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        for strategy in "abc":
            connection.execute(sql.SQL("SELECT 1 FROM {} LIMIT 0").format(
                sql.Identifier(f"chunks_{strategy}")))

    manifest = json.loads((repo / "data" / "manifest.json").read_text(encoding="utf-8"))
    files = {"openstax_1": repo / "data" / "OpenStax1.pdf",
             "openstax_2": repo / "data" / "OpenStax2.pdf"}
    sources = manifest["sources"]
    document_ids = [source["source_id"] for source in sources]
    if len(set(document_ids)) != len(document_ids):
        raise ValueError("Duplicate source IDs in manifest")
    for source in sources:
        if not files[source["source_id"]].is_file():
            raise FileNotFoundError(files[source["source_id"]])

    # A new run directory preserves previous results.
    started = datetime.now(timezone.utc)
    output = starter / "results" / ("step4_" + started.strftime("%Y%m%dT%H%M%S_%fZ"))
    output.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    total_start = perf_counter()
    pages, skipped = [], []
    for source in sources:
        source_id = source["source_id"]
        selected = source["content_pages"]
        print(f"Processing {source_id}: {len(selected)} selected pages", flush=True)
        loaded, log = load_pdf(files[source_id], source_id, source_id, valid_pages=selected)
        pages.extend(loaded)
        skipped.extend(log)
        save("ingestion_log.json", skipped)
        if {page.page for page in loaded} != set(selected):
            raise ValueError(f"{source_id}: selected pages were skipped; inspect ingestion_log.json")
    if len(pages) < 30:
        raise ValueError("Corpus must contain at least 30 content pages")
    chunks_a = [chunk for page in pages for chunk in fixed_size(page)]
    chunks_b = [chunk for page in pages for chunk in by_paragraph(page)]
    if not chunks_a or not chunks_b:
        raise ValueError("Chunking returned no chunks")
    save("chunks_a.json", [asdict(chunk) for chunk in chunks_a])
    save("chunks_b.json", [asdict(chunk) for chunk in chunks_b])
    metrics = {
        "started_at_utc": started.isoformat(), "model": "google/embeddinggemma-2",
        "dimensions": 768, "page_count": len(pages), "batch_size": 16,
        "api_cost": 0, "cost_note": "Local inference; excludes hardware and electricity.",
        "versions": {name: version(name) for name in
                     ("sentence-transformers", "transformers", "psycopg", "pypdfium2")},
        "ingest_chunk_seconds": perf_counter() - total_start,
        "chunks": {"A": measure_chunks(chunks_a), "B": measure_chunks(chunks_b),
                   "C": measure_chunks(chunks_b)},
        "ranking": "Exact cosine ranking for all strategies; HNSW indexes available.",
        "c_reuses_b_embeddings": True,
    }
    save("metrics.json", metrics)
    print(f"Chunks: A={len(chunks_a)}, B=C={len(chunks_b)}", flush=True)
    start = perf_counter()
    embedder = MyEmbedder(metrics["model"], batch_size=16)
    metrics["model_load_seconds"] = perf_counter() - start
    store = PgVectorStore(database_url, embedder.dimensions)
    vectors_b = None
    counts = {}
    for strategy, chunks in (("A", chunks_a), ("B", chunks_b), ("C", chunks_b)):
        print(f"Embedding/storing {strategy}...", flush=True)
        start = perf_counter()
        if strategy == "C":
            vectors = vectors_b
        else:
            vectors = embedder.embed_documents([chunk.text for chunk in chunks])
            if strategy == "B":
                vectors_b = vectors
        metrics[f"embed_{strategy}_seconds"] = perf_counter() - start
        start = perf_counter()
        # Complete document snapshots; no automatic deletion of obsolete rows.
        store.upsert(strategy, chunks, vectors, document_ids=document_ids)
        metrics[f"store_{strategy}_seconds"] = perf_counter() - start
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            count = connection.execute(sql.SQL(
                "SELECT count(*) FROM {} WHERE document_id = ANY(%s::text[])"
            ).format(sql.Identifier(f"chunks_{strategy.lower()}")), (document_ids,)).fetchone()[0]
        if count != len(chunks):
            raise ValueError(f"{strategy}: stored {count}, expected {len(chunks)}")
        counts[strategy] = count
        metrics["stored_counts"] = counts
        save("metrics.json", metrics)
        print(f"{strategy}: {count} rows verified", flush=True)
    metrics["total_seconds"] = perf_counter() - total_start
    save("metrics.json", metrics)
    print("Step 4 OK")
    print(f"Results: {output}")


if __name__ == "__main__":
    main()
