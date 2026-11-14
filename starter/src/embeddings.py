"""Local text embeddings shared by all retrieval strategies."""
from typing import Protocol

import numpy as np
from sentence_transformers import SentenceTransformer


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, question: str) -> list[float]: ...


class MyEmbedder:
    def __init__(self, model_name: str, *, batch_size: int = 16,
                 local_files_only: bool = False) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(
            model_name,
            config_kwargs={"vision_config": None, "audio_config": None},
            local_files_only=local_files_only,
        )
        self.dimensions = self.model.get_embedding_dimension()
        if self.dimensions != 768:
            raise ValueError(f"Expected 768 dimensions, got {self.dimensions}")
        for name in ("Document", "SearchQuery"):
            if name not in self.model.prompts:
                raise ValueError(f"Model is missing prompt {name!r}")

    def _encode(self, texts: list[str], prompt_name: str) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding inputs must be non-empty strings")
        vectors = np.asarray(self.model.encode(
            texts, prompt_name=prompt_name, batch_size=self.batch_size,
            normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        ))
        if vectors.shape != (len(texts), self.dimensions):
            raise ValueError(f"Unexpected embedding shape: {vectors.shape}")
        if not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) == 0):
            raise ValueError("Model returned non-finite or zero vectors")
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "Document")

    def embed_query(self, question: str) -> list[float]:
        return self._encode([question], "SearchQuery")[0]
