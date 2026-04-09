"""
Embeddings authority — the single source for all embedding operations.
Uses sentence-transformers MiniLM-L6-v2, local, zero-cost.
Singleton: import `embedder` and call embedder.embed(texts).
"""

from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder:
    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings. Returns list of float vectors."""
        model = self._load()
        vectors = model.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


# Module-level singleton — the single authority for embeddings
embedder = Embedder()
