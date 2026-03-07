from __future__ import annotations
import json
import logging
import math
from typing import List

from openai import OpenAI

logger = logging.getLogger(__name__)


def embed_text(text: str, client: OpenAI = None) -> List[float]:
    """Generate embedding for a single text using OpenAI text-embedding-3-small."""
    if client is None:
        client = OpenAI()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000],  # safe limit
    )
    return response.data[0].embedding


def embed_texts_batch(texts: List[str], client: OpenAI = None, batch_size: int = 100) -> List[List[float]]:
    """Generate embeddings for multiple texts in batched API calls.

    Sends texts in batches of `batch_size` (default 100) to the OpenAI
    embeddings endpoint, returning one embedding vector per input text.
    Order is preserved.

    Args:
        texts: List of texts to embed. Each is truncated to 8000 chars.
        client: OpenAI client (created if not provided).
        batch_size: Max texts per API request (OpenAI supports up to 2048).

    Returns:
        List of embedding vectors in the same order as `texts`.
    """
    if client is None:
        client = OpenAI()
    if not texts:
        return []

    results: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = [t[:8000] for t in texts[i : i + batch_size]]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch,
        )
        # API guarantees order matches input, but sort by index to be safe
        sorted_data = sorted(response.data, key=lambda e: e.index)
        results.extend(e.embedding for e in sorted_data)

    return results


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors (pure-Python fallback).

    Prefer ``cosine_similarities_matrix`` for batch operations — it is orders
    of magnitude faster thanks to numpy BLAS kernels.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def cosine_similarities_matrix(query: List[float], corpus: List[List[float]]) -> List[float]:
    """Compute cosine similarity between *query* and every vector in *corpus*.

    Uses numpy for vectorised computation: stacks all corpus vectors into an
    (N, D) matrix and computes the dot products in a single BLAS call, then
    divides by the precomputed norms.  This is 10–100× faster than calling
    :func:`cosine_similarity` in a Python loop.

    OpenAI ``text-embedding-3-small`` embeddings are already L2-normalised,
    so the division step degenerates to a no-op in practice — but we keep it
    for correctness with arbitrary vectors.

    Args:
        query:  Single query vector of dimension D.
        corpus: List of N vectors each of dimension D.

    Returns:
        List of N similarity scores in the same order as *corpus*.
    """
    try:
        import numpy as np  # optional fast path
    except ImportError:  # pragma: no cover — fallback for environments without numpy
        return [cosine_similarity(query, v) for v in corpus]

    if not corpus:
        return []

    q = np.array(query, dtype=np.float32)

    # Zero query vector → all similarities are 0
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return [0.0] * len(corpus)

    C = np.array(corpus, dtype=np.float32)  # (N, D)

    # Dot products: (N,)
    dots = C @ q

    # Norms – use np.maximum so the denominator is never zero
    c_norms = np.maximum(np.linalg.norm(C, axis=1), 1e-10)

    return (dots / (c_norms * q_norm)).tolist()


class SemanticSearch:
    def __init__(self, db):
        self.db = db
        self.client = OpenAI()

    def search(self, query: str, top_k: int = 10) -> List[dict]:
        """Search tweets by semantic similarity to query.

        Uses ``cosine_similarities_matrix`` for a single vectorised BLAS pass
        over all stored embeddings instead of a per-tweet Python loop.
        """
        logger.info("Semantic search: query=%r, top_k=%d", query, top_k)
        query_embedding = embed_text(query, self.client)

        all_tweets = self.db.get_tweets_with_embeddings()
        if not all_tweets:
            logger.warning("No tweets with embeddings found")
            return []

        # Parse embeddings and keep only valid ones
        valid_tweets: List[dict] = []
        corpus: List[List[float]] = []
        for tweet in all_tweets:
            emb_json = tweet.get("embedding")
            if not emb_json:
                continue
            try:
                emb = json.loads(emb_json) if isinstance(emb_json, str) else emb_json
                valid_tweets.append(tweet)
                corpus.append(emb)
            except Exception as e:
                logger.debug("Skipping tweet %s: %s", tweet.get("id"), e)

        if not corpus:
            return []

        # Single vectorised similarity computation — replaces the O(N) Python loop
        scores = cosine_similarities_matrix(query_embedding, corpus)

        scored = sorted(
            zip(scores, valid_tweets),
            key=lambda x: x[0],
            reverse=True,
        )

        results = []
        for score, tweet in scored[:top_k]:
            t = dict(tweet)
            t["similarity_score"] = round(score, 4)
            results.append(t)

        logger.info("Found %d results", len(results))
        return results
