from __future__ import annotations

import json
import logging
import os
from typing import List, Tuple

from src.search.semantic_search import cosine_similarities_matrix

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.92


class SemanticDeduplicator:
    def __init__(self, similarity_threshold: float = _DEFAULT_THRESHOLD):
        env_val = os.getenv("SEMANTIC_DEDUP_THRESHOLD")
        if env_val is not None:
            self.threshold = float(env_val)
        else:
            self.threshold = similarity_threshold

    def deduplicate(
        self,
        new_tweets: List[dict],
        existing_tweets: List[dict],
    ) -> List[Tuple[str, str]]:
        """Compare new tweets against existing tweets by cosine similarity.

        Uses ``cosine_similarities_matrix`` for a vectorised BLAS pass over
        the entire existing-tweet corpus per new tweet, instead of a nested
        Python loop.  For M new tweets and N existing tweets the old code ran
        M × N pure-Python iterations over 1536-dimensional vectors; this
        version replaces that with M numpy matrix-vector multiplications.

        Returns list of (new_tweet_id, existing_tweet_id) for duplicates.
        """
        # Parse existing embeddings once, up-front
        existing_ids: List[str] = []
        corpus: List[List[float]] = []
        for tweet in existing_tweets:
            emb_json = tweet.get("embedding")
            if not emb_json:
                continue
            try:
                emb = json.loads(emb_json) if isinstance(emb_json, str) else emb_json
                existing_ids.append(tweet["id"])
                corpus.append(emb)
            except (json.JSONDecodeError, KeyError):
                continue

        if not corpus:
            return []

        duplicates: List[Tuple[str, str]] = []
        for tweet in new_tweets:
            emb_json = tweet.get("embedding")
            if not emb_json:
                continue
            try:
                new_emb = json.loads(emb_json) if isinstance(emb_json, str) else emb_json
            except (json.JSONDecodeError, KeyError):
                continue

            new_id = tweet["id"]

            # Vectorised: compute similarity to all existing tweets in one call
            scores = cosine_similarities_matrix(new_emb, corpus)

            for existing_id, score in zip(existing_ids, scores):
                if existing_id == new_id:
                    continue
                if score >= self.threshold:
                    duplicates.append((new_id, existing_id))
                    logger.debug(
                        "Duplicate: %s ~ %s (%.4f)", new_id, existing_id, score
                    )
                    break

        return duplicates
