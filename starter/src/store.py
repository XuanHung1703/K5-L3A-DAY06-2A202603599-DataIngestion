"""PostgreSQL + pgvector storage; database writes happen only when called."""
import json
import math
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        if dimensions != 768:
            raise ValueError("This lab requires 768-dimensional vectors")
        self.database_url = database_url
        self.dimensions = dimensions

    @staticmethod
    def _table(strategy: str) -> sql.Identifier:
        if not isinstance(strategy, str) or strategy.upper() not in {"A", "B", "C"}:
            raise ValueError("strategy must be A, B or C")
        return sql.Identifier("chunks_" + strategy.lower())

    def _vector(self, values: list[float]) -> str:
        if len(values) != self.dimensions:
            raise ValueError(f"Expected {self.dimensions} vector dimensions")
        numbers = [float(value) for value in values]
        if not all(math.isfinite(value) for value in numbers):
            raise ValueError("Vector values must be finite")
        if not any(value != 0 for value in numbers):
            raise ValueError("Cosine distance requires a non-zero vector")
        return json.dumps(numbers, allow_nan=False)

    def create_schema(self) -> None:
        """Create tables and cosine indexes; requires explicit caller action."""
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                for strategy in ("A", "B", "C"):
                    table = self._table(strategy)
                    cursor.execute(sql.SQL("""
                        CREATE TABLE IF NOT EXISTS {} (
                            chunk_id TEXT PRIMARY KEY,
                            document_id TEXT NOT NULL,
                            source TEXT NOT NULL,
                            page INTEGER NOT NULL CHECK (page > 0),
                            text TEXT NOT NULL,
                            metadata JSONB NOT NULL,
                            embedding vector(768) NOT NULL
                        )
                    """).format(table))
                    cursor.execute(sql.SQL(
                        "CREATE INDEX IF NOT EXISTS {} ON {} "
                        "USING hnsw (embedding vector_cosine_ops)"
                    ).format(sql.Identifier(f"chunks_{strategy.lower()}_cosine_idx"), table))

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               *, document_ids: list[str] | None = None,
               replace_obsolete: bool = False) -> None:
        """Ingest COMPLETE document snapshots, never partial page batches.

        Pass document_ids for documents now containing zero chunks. Obsolete
        rows are removed only with explicit replace_obsolete=True; otherwise a
        changed snapshot raises and the transaction rolls back.
        """
        table = self._table(strategy)
        if len(chunks) != len(vectors):
            raise ValueError("Number of chunks must equal number of vectors")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("Duplicate chunk IDs in input")
        documents = set(document_ids) if document_ids is not None else {
            chunk.document_id for chunk in chunks
        }
        if any(not isinstance(doc, str) or not doc for doc in documents):
            raise ValueError("document_ids must contain non-empty strings")
        grouped: dict[str, list[str]] = {doc: [] for doc in documents}
        rows = []
        for chunk, vector in zip(chunks, vectors):
            if chunk.document_id not in grouped:
                raise ValueError("Chunk document_id is outside document_ids")
            if (not chunk.chunk_id or not chunk.source or not chunk.text.strip()
                    or type(chunk.page) is not int or chunk.page <= 0):
                raise ValueError("Chunk requires ID, source, positive page and text")
            if not isinstance(chunk.metadata, dict):
                raise ValueError("Chunk metadata must be a dictionary")
            json.dumps(chunk.metadata, allow_nan=False)
            grouped[chunk.document_id].append(chunk.chunk_id)
            rows.append((chunk.chunk_id, chunk.document_id, chunk.source, chunk.page,
                         chunk.text, Jsonb(chunk.metadata), self._vector(vector)))
        if not documents:
            return
        with psycopg.connect(self.database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(table))
                for document_id, chunk_ids in sorted(grouped.items()):
                    cursor.execute(sql.SQL(
                        "SELECT chunk_id FROM {} WHERE document_id = %s "
                        "AND NOT (chunk_id = ANY(%s::text[]))"
                    ).format(table), (document_id, chunk_ids))
                    obsolete = [row[0] for row in cursor.fetchall()]
                    if obsolete and not replace_obsolete:
                        raise ValueError(
                            f"{document_id}: {len(obsolete)} obsolete chunks. "
                            "Approve removal, then pass replace_obsolete=True."
                        )
                    if obsolete:
                        cursor.execute(sql.SQL(
                            "DELETE FROM {} WHERE document_id = %s "
                            "AND chunk_id = ANY(%s::text[])"
                        ).format(table), (document_id, obsolete))
                if rows:
                    cursor.executemany(sql.SQL("""
                        INSERT INTO {} AS existing
                        (chunk_id, document_id, source, page, text, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            source = EXCLUDED.source, page = EXCLUDED.page,
                            text = EXCLUDED.text, metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                        WHERE existing.document_id = EXCLUDED.document_id
                    """).format(table), rows)
                    cursor.execute(sql.SQL(
                        "SELECT chunk_id, document_id FROM {} "
                        "WHERE chunk_id = ANY(%s::text[])"
                    ).format(table), ([chunk.chunk_id for chunk in chunks],))
                    owners = dict(cursor.fetchall())
                    if any(owners.get(chunk.chunk_id) != chunk.document_id for chunk in chunks):
                        raise ValueError("Chunk ID collision across documents")

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        table = self._table(strategy)
        vector = self._vector(query_vector)
        if type(top_k) is not int or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        filters = {} if filters is None else filters
        allowed = {"document_id", "source", "page", "section", "chapter"}
        if not isinstance(filters, dict) or set(filters) - allowed:
            raise ValueError(f"Allowed filters: {sorted(allowed)}")
        conditions = []
        parameters: list[Any] = []
        for key, value in filters.items():
            if key == "page":
                if type(value) is not int or value <= 0:
                    raise ValueError("page filter must be a positive integer")
            elif not isinstance(value, str) or not value:
                raise ValueError(f"{key} filter must be a non-empty string")
            if key in {"document_id", "source", "page"}:
                conditions.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
                parameters.append(value)
            else:
                conditions.append(sql.SQL("metadata @> %s"))
                parameters.append(Jsonb({key: value}))
        # Use the same exact ranking for A/B/C on this small lab corpus.
        # ANN post-filtering could underfill top_k and confound the comparison.
        where = sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("TRUE")
        prefix = sql.SQL("WITH candidates AS MATERIALIZED (SELECT * FROM {} WHERE {}) ").format(
            table, where
        )
        source = sql.Identifier("candidates")
        statement = prefix + sql.SQL("""
            SELECT chunk_id, document_id, source, page, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM {} ORDER BY embedding <=> %s::vector LIMIT %s
        """).format(source)
        parameters.extend((vector, vector, top_k))
        with psycopg.connect(self.database_url, connect_timeout=10, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                hits = cursor.fetchall()
        for hit in hits:
            hit["metadata"] = {
                **hit["metadata"], "document_id": hit["document_id"],
                "source": hit["source"], "page": hit["page"],
            }
        return hits
