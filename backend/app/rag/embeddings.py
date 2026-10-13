"""Text embeddings that run on this machine: no key, no per-token cost."""

import hashlib
import math
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.config import settings

DIMENSIONS = 384  # of the default model; the `chunks.embedding` column has this size


class LocalEmbeddings(Embeddings):
    """A multilingual sentence model through fastembed (ONNX, CPU). The model file is
    downloaded once into the data directory."""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        cache = settings.data_dir / "models"
        cache.mkdir(parents=True, exist_ok=True)
        self._model = TextEmbedding(model_name, cache_dir=str(cache))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class HashEmbeddings(Embeddings):
    """Bag of word stems hashed into a vector. No model, no download: for tests, and for
    trying the app where the real model cannot be fetched. Finds shared words, not meaning."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for word in re.findall(r"\w{3,}", text.casefold()):
            digest = hashlib.md5(word[:5].encode(), usedforsecurity=False).digest()
            vector[int.from_bytes(digest[:4], "big") % DIMENSIONS] += 1.0
        length = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / length for v in vector]


@lru_cache
def get_embeddings() -> Embeddings:
    if settings.embedding_model == "hash":
        return HashEmbeddings()
    return LocalEmbeddings(settings.embedding_model)
