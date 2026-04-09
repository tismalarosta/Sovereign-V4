"""
ChromaDB authority — the single source for all vector store operations.
Persists at data/chroma/. Singleton: import `store` and use its methods.
"""

from pathlib import Path
import chromadb
from chromadb.config import Settings

CHROMA_PATH = Path(__file__).parent.parent / "data" / "chroma"
COLLECTION_NAME = "docs"


class ChromaStore:
    def __init__(self) -> None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        """Upsert chunks into the collection. Idempotent by id."""
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Return top-k chunks with source citations.
        Each result: {id, document, source, score}
        Optionally filter by metadata with a ChromaDB `where` clause.
        """
        kwargs: dict = {
            "query_embeddings": [embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        results = self._collection.query(**kwargs)
        chunks = []
        ids = results["ids"][0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
            chunks.append({
                "id": chunk_id,
                "document": doc,
                "source": meta.get("source", "unknown"),
                "score": round(1 - dist, 4),  # cosine similarity
                **{k: v for k, v in meta.items() if k != "source"},
            })
        return chunks

    def get_where(self, where: dict, limit: int = 50) -> list[dict]:
        """Fetch chunks by metadata filter (no semantic ranking).
        Only use ChromaDB-supported operators: $eq, $ne, $in, $nin on any field;
        $gt/$gte/$lt/$lte only on numeric fields (not strings).
        Returns list of {id, document, source, ...metadata}.
        """
        results = self._collection.get(
            where=where,
            limit=limit,
            include=["documents", "metadatas"],
        )
        chunks = []
        for chunk_id, doc, meta in zip(results["ids"], results["documents"], results["metadatas"]):
            chunks.append({"id": chunk_id, "document": doc, **meta})
        return chunks

    def delete_by_filter(self, where: dict) -> int:
        """Delete all chunks matching a metadata filter. Returns count deleted."""
        results = self._collection.get(where=where, limit=10000, include=[])
        if results["ids"]:
            self._collection.delete(ids=results["ids"])
        return len(results["ids"])

    def count(self) -> int:
        return self._collection.count()

    def delete_by_source(self, source: str) -> None:
        """Remove all chunks from a given source file (for re-ingestion)."""
        results = self._collection.get(where={"source": source})
        if results["ids"]:
            self._collection.delete(ids=results["ids"])


# Module-level singleton
store = ChromaStore()
