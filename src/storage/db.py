import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List

from src.crawler.twitter_crawler import Tweet

logger = logging.getLogger(__name__)

_CREATE_TWEETS_TABLE = """
CREATE TABLE IF NOT EXISTS tweets (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    url TEXT NOT NULL,
    timestamp TEXT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    feed_type TEXT NOT NULL,
    crawl_session_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS crawl_sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    total_tweets INTEGER DEFAULT 0,
    ai_tweets_count INTEGER DEFAULT 0
)
"""


class TweetDatabase:
    def __init__(self, db_path: str = "data/tweets.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(_CREATE_TWEETS_TABLE)
            conn.execute(_CREATE_SESSIONS_TABLE)
            conn.commit()
        finally:
            conn.close()

    def save_tweet(self, tweet: Tweet, session_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tweets "
                "(id, text, author, url, timestamp, likes, retweets, "
                "feed_type, crawl_session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tweet.id, tweet.text, tweet.author, tweet.url,
                    tweet.timestamp, tweet.likes, tweet.retweets,
                    tweet.feed_type, session_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def save_tweets(self, tweets: List[Tweet], session_id: str) -> int:
        saved = 0
        for tweet in tweets:
            if self.save_tweet(tweet, session_id):
                saved += 1
        return saved

    def get_tweets_by_session(self, session_id: str) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM tweets WHERE crawl_session_id = ? ORDER BY id",
                (session_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO crawl_sessions (id, started_at) VALUES (?, ?)",
                (session_id, now),
            )
            conn.commit()
            return session_id
        finally:
            conn.close()

    def complete_session(
        self, session_id: str, total_tweets: int, ai_tweets_count: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE crawl_sessions "
                "SET completed_at = ?, total_tweets = ?, ai_tweets_count = ? "
                "WHERE id = ?",
                (now, total_tweets, ai_tweets_count, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_tweets(self, hours: int = 24) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE created_at >= datetime('now', ? || ' hours') "
                "ORDER BY created_at DESC",
                (f"-{hours}",),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
