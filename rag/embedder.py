from __future__ import annotations
from sentence_transformers import SentenceTransformer
from config import EMBED_MODEL

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedder()
    return model.encode(texts, convert_to_numpy=True).tolist()
