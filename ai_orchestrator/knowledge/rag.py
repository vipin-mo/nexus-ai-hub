"""Hybrid retrieval over the internal knowledge base.

Two retrievers run on every query and their rankings are merged with
reciprocal-rank fusion (RRF):

* dense  - LlamaIndex + ChromaDB, embeddings from Ollama ``nomic-embed-text``
           (or a hashing embedding when ``NEXUS_EMBEDDINGS=hash``, for offline CI);
* sparse - BM25 keyword search (``bm25s`` via LlamaIndex).

The Chroma collection stores a hash of the document set; when a document is
added or edited the collection is rebuilt instead of silently serving stale text.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from ai_orchestrator.config import Settings, get_settings

log = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent / "documents"
RRF_K = 60  # standard constant from Cormack et al. (2009)


@dataclass
class RetrievedChunk:
    source: str
    text: str
    score: float
    dense_rank: int | None
    sparse_rank: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def _hash_embedding_class():
    from llama_index.core.embeddings import BaseEmbedding

    class HashEmbedding(BaseEmbedding):
        """Deterministic bag-of-words hashing embedding (no model download).

        Only used for offline tests/CI so the dense path is exercised without Ollama;
        retrieval quality numbers in BENCHMARKS.md use nomic-embed-text.
        """

        dim: int = 384

        @staticmethod
        def _tokens(text: str) -> list[str]:
            return re.findall(r"[a-z0-9]+", text.lower())

        def _embed(self, text: str) -> list[float]:
            vec = np.zeros(self.dim, dtype=np.float32)
            for tok in self._tokens(text):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            norm = np.linalg.norm(vec)
            return (vec / norm).tolist() if norm else vec.tolist()

        def _get_query_embedding(self, query: str) -> list[float]:
            return self._embed(query)

        def _get_text_embedding(self, text: str) -> list[float]:
            return self._embed(text)

        async def _aget_query_embedding(self, query: str) -> list[float]:
            return self._embed(query)

    return HashEmbedding


def _make_embedding(settings: Settings):
    if settings.embeddings == "hash":
        return _hash_embedding_class()(model_name="hash-384")
    from llama_index.embeddings.ollama import OllamaEmbedding

    return OllamaEmbedding(model_name=settings.embed_model, base_url=settings.ollama_base_url)


def documents_manifest(docs_dir: Path = DOCS_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(docs_dir.glob("*.md")):
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16]


class HybridRetriever:
    def __init__(self, settings: Settings, docs_dir: Path = DOCS_DIR):
        self.settings = settings
        self.docs_dir = docs_dir
        self._lock = threading.Lock()
        self._ready = False

    def _build(self) -> None:
        import chromadb
        from llama_index.core import Document, StorageContext, VectorStoreIndex
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.retrievers.bm25 import BM25Retriever
        from llama_index.vector_stores.chroma import ChromaVectorStore

        s = self.settings
        paths = sorted(self.docs_dir.glob("*.md"))
        if not paths:
            raise RuntimeError(f"No knowledge documents found in {self.docs_dir}")
        documents = [Document(text=p.read_text(encoding="utf-8"), metadata={"source": p.name},
                              excluded_embed_metadata_keys=["source"]) for p in paths]
        splitter = SentenceSplitter(chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap)
        nodes = splitter.get_nodes_from_documents(documents)

        manifest = documents_manifest(self.docs_dir)
        embed = _make_embedding(s)
        s.chroma_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(s.chroma_dir),
                                           settings=chromadb.config.Settings(anonymized_telemetry=False))
        name = f"nexus_kb_{s.embeddings}"
        existing = {c.name for c in client.list_collections()}
        if name in existing:
            collection = client.get_collection(name, embedding_function=None)
            if (collection.metadata or {}).get("manifest") != manifest:
                log.info("Knowledge base changed (manifest %s); rebuilding vector index", manifest)
                client.delete_collection(name)
                existing.discard(name)
        if name not in existing:
            collection = client.create_collection(name, embedding_function=None,
                                                  metadata={"manifest": manifest, "hnsw:space": "cosine"})
            store = ChromaVectorStore(chroma_collection=collection)
            VectorStoreIndex(nodes, storage_context=StorageContext.from_defaults(vector_store=store),
                             embed_model=embed)
            log.info("Indexed %d chunks from %d documents", len(nodes), len(paths))
        store = ChromaVectorStore(chroma_collection=collection)
        index = VectorStoreIndex.from_vector_store(store, embed_model=embed)

        candidates = max(self.settings.retrieval_top_k * 2, 6)
        self._dense = index.as_retriever(similarity_top_k=candidates)
        self._sparse = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=candidates, language="english")
        self.manifest = manifest
        self.chunk_count = len(nodes)
        self._ready = True

    def ensure_ready(self) -> None:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self._build()

    def retrieve(self, query: str, top_k: int | None = None, mode: str = "hybrid") -> list[RetrievedChunk]:
        """Return up to ``top_k`` chunks. ``mode`` is hybrid | dense | sparse (the latter two for evals)."""
        self.ensure_ready()
        top_k = top_k or self.settings.retrieval_top_k
        ranked: dict[str, dict] = {}
        lists = []
        if mode in ("hybrid", "dense"):
            lists.append(("dense", self._dense.retrieve(query)))
        if mode in ("hybrid", "sparse"):
            lists.append(("sparse", self._sparse.retrieve(query)))
        for kind, hits in lists:
            for rank, hit in enumerate(hits, start=1):
                entry = ranked.setdefault(hit.node.node_id, {
                    "source": hit.node.metadata.get("source", "unknown"),
                    "text": hit.node.get_content(), "score": 0.0, "dense": None, "sparse": None})
                entry["score"] += 1.0 / (RRF_K + rank)
                entry[kind] = rank
        fused = sorted(ranked.values(), key=lambda e: e["score"], reverse=True)
        return [RetrievedChunk(e["source"], e["text"], round(e["score"], 5), e["dense"], e["sparse"])
                for e in fused[:top_k]]


@lru_cache(maxsize=1)
def get_retriever() -> HybridRetriever:
    return HybridRetriever(get_settings())


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    question = " ".join(sys.argv[1:]) or "Who must approve destructive database writes?"
    for chunk in get_retriever().retrieve(question):
        print(f"{chunk.score:.4f}  dense={chunk.dense_rank} sparse={chunk.sparse_rank}  {chunk.source}")
        print("   ", chunk.text[:160].replace("\n", " "), "...")
