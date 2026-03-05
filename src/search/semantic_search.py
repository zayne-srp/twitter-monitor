from __future__ import annotations
import json
import logging
import math
from typing import List

from openai import OpenAI

logger = logging.getLogger(__name__)


def embed_text(text: str, client: OpenAI = None) -> List[float]:
    """Generate embedding for text using OpenAI text-embedding-3-small."""
    if client is None:
        client = OpenAI()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000],  # safe limit
    )
    return response.data[0].embedding


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
