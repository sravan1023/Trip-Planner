from __future__ import annotations

import re
import threading

import chromadb

from config import (
    CHROMA_DB_PATH,
    RAG_COLLECTION_NAME,
    RAG_MIN_SCORE,
    RAG_TOP_K,
)

_client: chromadb.PersistentClient | None = None


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _client


def get_collection() -> chromadb.Collection:
    client = get_client()
    return client.get_or_create_collection(
        name=RAG_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


# Chroma's Rust binding caps a single upsert at ~5461 records. We chunk
# defensively so a corpus of any size ingests cleanly.
_MAX_UPSERT_BATCH = 4000


def add_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    coll = get_collection()
    for start in range(0, len(ids), _MAX_UPSERT_BATCH):
        end = start + _MAX_UPSERT_BATCH
        coll.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
        )


# ── BM25 lexical index ────────────────────────────────────────────────────────
# Lazily built from the Chroma collection. Rebuilt when the collection size
# changes (so re-ingest invalidates the cache automatically).

_bm25_lock = threading.Lock()
_bm25_state: dict = {
    "size": -1,
    "bm25": None,
    "ids": [],
    "docs": [],
    "metas": [],
}


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _ensure_bm25() -> dict:
    """Return the cached BM25 state, rebuilding if the collection size changed.
    Returns an empty state with bm25=None when rank_bm25 isn't installed or the
    collection is empty."""
    coll = get_collection()
    size = coll.count()

    with _bm25_lock:
        if _bm25_state["size"] == size and _bm25_state["bm25"] is not None:
            return _bm25_state
        if size == 0:
            _bm25_state.update(size=0, bm25=None, ids=[], docs=[], metas=[])
            return _bm25_state

        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            _bm25_state.update(size=size, bm25=None, ids=[], docs=[], metas=[])
            return _bm25_state

        data = coll.get(include=["documents", "metadatas"])
        ids = data.get("ids", []) or []
        docs = data.get("documents", []) or []
        metas = data.get("metadatas", []) or []
        tokens = [_tokenize(d) for d in docs]
        bm25 = BM25Okapi(tokens) if tokens else None

        _bm25_state.update(size=size, bm25=bm25, ids=ids, docs=docs, metas=metas)
        return _bm25_state


def _meta_matches(meta: dict, where: dict | None) -> bool:
    if not where:
        return True
    for k, v in where.items():
        if (meta.get(k) or "") != v:
            return False
    return True


def _dense_query(
    query_embedding: list[float],
    n_results: int,
    where: dict | None,
) -> list[tuple[str, str, dict, float]]:
    """Return list of (id, doc, meta, normalized_score) from the dense index."""
    kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    results = get_collection().query(**kwargs)
    out: list[tuple[str, str, dict, float]] = []
    if not results.get("ids") or not results["ids"][0]:
        return out
    for cid, doc, meta, dist in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        # Chroma cosine distance lives in [0, 2]; map to similarity in [0, 1].
        score = max(0.0, 1.0 - (dist / 2.0))
        out.append((cid, doc, meta or {}, score))
    return out


def _bm25_query(
    query: str,
    n_results: int,
    where: dict | None,
) -> list[tuple[str, str, dict, float]]:
    state = _ensure_bm25()
    bm25 = state["bm25"]
    if bm25 is None:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    # Pre-filter by where clause then take top-N by raw BM25 score.
    candidates = []
    for i, raw in enumerate(scores):
        if raw <= 0:
            continue
        meta = state["metas"][i] or {}
        if not _meta_matches(meta, where):
            continue
        candidates.append((i, float(raw)))
    candidates.sort(key=lambda x: x[1], reverse=True)
    candidates = candidates[:n_results]
    return [
        (state["ids"][i], state["docs"][i], state["metas"][i] or {}, raw)
        for i, raw in candidates
    ]


def query_similar(
    query_embedding: list[float],
    *,
    query_text: str = "",
    top_k: int = RAG_TOP_K,
    min_score: float = RAG_MIN_SCORE,
    where: dict | None = None,
) -> list[dict]:
    """Hybrid dense + BM25 retrieval with reciprocal-rank fusion.

    - `query_embedding`: dense vector for the query.
    - `query_text`: original query string, used for the BM25 leg. If empty,
      falls back to dense-only.
    - `where`: optional Chroma metadata filter (e.g. {"city": "San Francisco"}).
    - `min_score` thresholding is applied to the *normalized dense* score so
      callers see only chunks the dense model itself rates as relevant; pure
      BM25 hits are kept even without a strong dense signal so exact-name
      matches still surface.
    """
    n_per_leg = max(top_k * 3, 20)

    where_clause = where or None
    # Chroma rejects empty {} where clauses, and a single-key filter doesn't
    # need an $and wrapper.
    if where_clause and len(where_clause) > 1:
        where_clause = {"$and": [{k: v} for k, v in where_clause.items()]}

    dense_hits = _dense_query(query_embedding, n_per_leg, where_clause)
    bm25_hits = _bm25_query(query_text, n_per_leg, where) if query_text else []

    # Stash dense scores by id so we can keep the meaningful score post-fusion.
    dense_score_by_id = {cid: score for cid, _, _, score in dense_hits}
    record_by_id: dict[str, tuple[str, dict]] = {}
    for cid, doc, meta, _ in dense_hits:
        record_by_id[cid] = (doc, meta)
    for cid, doc, meta, _ in bm25_hits:
        record_by_id.setdefault(cid, (doc, meta))

    # Reciprocal Rank Fusion across the two lists.
    K = 60
    rrf: dict[str, float] = {}
    for rank, (cid, _, _, _) in enumerate(dense_hits):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (K + rank + 1)
    for rank, (cid, _, _, _) in enumerate(bm25_hits):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (K + rank + 1)

    fused_ids = sorted(rrf.keys(), key=lambda i: rrf[i], reverse=True)

    chunks: list[dict] = []
    for cid in fused_ids:
        doc, meta = record_by_id[cid]
        # Use dense similarity as the user-facing score; bm25-only hits get a
        # neutral 0.5 so they're still surfaced.
        score = dense_score_by_id.get(cid, 0.5)
        if cid in dense_score_by_id and score < min_score:
            # Below the dense threshold and the model isn't confident — skip
            # unless BM25 also pulled it in (signals exact term match).
            if cid not in {b[0] for b in bm25_hits}:
                continue
        chunks.append({
            "text": doc,
            "source": meta.get("source", "unknown"),
            "score": round(score, 4),
            "metadata": meta,
        })
        if len(chunks) >= top_k:
            break

    return chunks


def collection_count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
