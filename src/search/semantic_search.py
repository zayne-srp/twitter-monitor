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
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticSearch:
    def __init__(self, db):
        self.db = db
        self.client = OpenAI()

    def search(self, query: str, top_k: int = 10) -> List[dict]:
        """Search tweets by semantic similarity to query."""
        logger.info("Semantic search: query=%r, top_k=%d", query, top_k)
        query_embedding = embed_text(query, self.client)

        all_tweets = self.db.get_tweets_with_embeddings()
        if not all_tweets:
            logger.warning("No tweets with embeddings found")
            return []

        scored = []
        for tweet in all_tweets:
            emb_json = tweet.get("embedding")
            if not emb_json:
                continue
            try:
                emb = json.loads(emb_json)
                score = cosine_similarity(query_embedding, emb)
                scored.append((score, tweet))
            except Exception as e:
                logger.debug("Skipping tweet %s: %s", tweet.get("id"), e)

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, tweet in scored[:top_k]:
            t = dict(tweet)
            t["similarity_score"] = round(score, 4)
            results.append(t)

        logger.info("Found %d results", len(results))
        return results
