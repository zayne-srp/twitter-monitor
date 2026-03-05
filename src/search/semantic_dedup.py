from __future__ import annotations

import json
import logging
import os
from typing import List, Tuple

from src.search.semantic_search import cosine_similarity

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

        Returns list of (new_tweet_id, existing_tweet_id) for duplicates.
        """
        existing_parsed = []
        for tweet in existing_tweets:
            emb_json = tweet.get("embedding")
            if not emb_json:
                continue
            try:
                emb = json.loads(emb_json) if isinstance(emb_json, str) else emb_json
                existing_parsed.append((tweet["id"], emb))
            except (json.JSONDecodeError, KeyError):
                continue

        if not existing_parsed:
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
            for existing_id, existing_emb in existing_parsed:
                if new_id == existing_id:
                    continue
                similarity = cosine_similarity(new_emb, existing_emb)
                if similarity >= self.threshold:
                    duplicates.append((new_id, existing_id))
                    logger.debug(
                        "Duplicate: %s ~ %s (%.4f)", new_id, existing_id, similarity
                    )
                    break

        return duplicates
