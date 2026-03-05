from __future__ import annotations
import json
import logging
import time
from typing import List

from openai import OpenAI

from src.search.semantic_search import embed_text

logger = logging.getLogger(__name__)


class TweetIndexer:
    def __init__(self, db):
        self.db = db
        self.client = OpenAI()

    def index_tweet(self, tweet_id: str, text: str) -> bool:
        """Generate and store embedding for a tweet."""
        try:
            embedding = embed_text(text, self.client)
            emb_json = json.dumps(embedding)
            self.db.save_embedding(tweet_id, emb_json)
            return True
        except Exception as e:
            logger.error("Failed to index tweet %s: %s", tweet_id, e)
            return False

    def index_tweets(self, tweets: List[dict]) -> int:
        """Batch index multiple tweets. Returns count indexed."""
        count = 0
        for tweet in tweets:
            tweet_id = tweet.get("id")
            text = tweet.get("text", "")
            if tweet_id and text:
                if self.index_tweet(tweet_id, text):
                    count += 1
        logger.info("Indexed %d/%d tweets", count, len(tweets))
        return count

    def index_missing(self, db, batch_size: int = 50) -> int:
        """Find tweets with NULL embedding and is_ai_related=1, generate embeddings."""
        rows = db.get_tweets_missing_embeddings(batch_size)
        count = 0
        for row in rows:
            tweet_id = row["id"]
            text = row["text"]
            if tweet_id and text:
                if self._index_with_retry(tweet_id, text):
                    count += 1
        logger.info("Compensated %d missing embeddings", count)
        return count

    def _index_with_retry(self, tweet_id: str, text: str, max_retries: int = 2) -> bool:
        for attempt in range(max_retries + 1):
            try:
                embedding = embed_text(text, self.client)
                emb_json = json.dumps(embedding)
                self.db.save_embedding(tweet_id, emb_json)
                return True
            except Exception as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning("Embedding retry %d/%d for %s: %s", attempt + 1, max_retries, tweet_id, e)
                    time.sleep(wait)
                else:
                    logger.warning("Skipping embedding for %s after %d retries: %s", tweet_id, max_retries, e)
        return False
