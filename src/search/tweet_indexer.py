from __future__ import annotations
import json
import logging
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
