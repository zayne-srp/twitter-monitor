from __future__ import annotations
import json
import logging
import time
from typing import List

from openai import OpenAI

from src.search.semantic_search import embed_texts_batch, embed_text

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 100  # max texts per OpenAI embeddings API call


class TweetIndexer:
    def __init__(self, db):
        self.db = db
        self.client = OpenAI()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_tweet(self, tweet_id: str, text: str) -> bool:
        """Generate and store embedding for a single tweet."""
        try:
            embedding = embed_text(text, self.client)
            self._save(tweet_id, embedding)
            return True
        except Exception as e:
            logger.error("Failed to index tweet %s: %s", tweet_id, e)
            return False

    def index_tweets(self, tweets: List[dict]) -> int:
        """Batch-index multiple tweets in as few API calls as possible.

        Instead of one API call per tweet this method collects all texts,
        sends them to the embeddings endpoint in batches of up to
        ``_EMBED_BATCH_SIZE`` items, then persists each result.
        This reduces N API calls to ceil(N / batch_size).

        Returns:
            Number of tweets successfully indexed.
        """
        valid = [(t["id"], t["text"]) for t in tweets if t.get("id") and t.get("text")]
        if not valid:
            return 0

        ids, texts = zip(*valid)
        try:
            embeddings = embed_texts_batch(list(texts), self.client, _EMBED_BATCH_SIZE)
        except Exception as e:
            logger.error("Batch embedding failed, falling back to per-tweet: %s", e)
            return self._index_one_by_one(list(valid))

        count = 0
        for tweet_id, embedding in zip(ids, embeddings):
            try:
                self._save(tweet_id, embedding)
                count += 1
            except Exception as e:
                logger.error("Failed to save embedding for %s: %s", tweet_id, e)

        logger.info("Indexed %d/%d tweets", count, len(valid))
        return count

    def index_missing(self, db, batch_size: int = 50) -> int:
        """Find AI-related tweets with NULL embedding and generate embeddings in batch."""
        rows = db.get_tweets_missing_embeddings(batch_size)
        if not rows:
            return 0

        valid = [(r["id"], r["text"]) for r in rows if r.get("id") and r.get("text")]
        if not valid:
            return 0

        ids, texts = zip(*valid)
        try:
            embeddings = embed_texts_batch(list(texts), self.client, _EMBED_BATCH_SIZE)
        except Exception as e:
            logger.warning("Batch embedding failed for missing, falling back: %s", e)
            return self._index_missing_one_by_one(list(valid))

        count = 0
        for tweet_id, embedding in zip(ids, embeddings):
            try:
                self._save(tweet_id, embedding)
                count += 1
            except Exception as e:
                logger.error("Failed to save compensated embedding %s: %s", tweet_id, e)

        logger.info("Compensated %d missing embeddings", count)
        return count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save(self, tweet_id: str, embedding: List[float]) -> None:
        self.db.save_embedding(tweet_id, json.dumps(embedding))

    def _index_one_by_one(self, id_text_pairs: List[tuple]) -> int:
        """Fallback: index tweets individually with retry."""
        count = 0
        for tweet_id, text in id_text_pairs:
            if self._index_with_retry(tweet_id, text):
                count += 1
        return count

    def _index_missing_one_by_one(self, id_text_pairs: List[tuple]) -> int:
        count = 0
        for tweet_id, text in id_text_pairs:
            if self._index_with_retry(tweet_id, text):
                count += 1
        return count

    def _index_with_retry(self, tweet_id: str, text: str, max_retries: int = 2) -> bool:
        for attempt in range(max_retries + 1):
            try:
                embedding = embed_text(text, self.client)
                self._save(tweet_id, embedding)
                return True
            except Exception as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "Embedding retry %d/%d for %s: %s",
                        attempt + 1, max_retries, tweet_id, e,
                    )
                    time.sleep(wait)
                else:
                    logger.warning(
                        "Skipping embedding for %s after %d retries: %s",
                        tweet_id, max_retries, e,
                    )
        return False
