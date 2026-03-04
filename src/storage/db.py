import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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



def _get(obj, key, default=None):
    """Get field from either a dict or a dataclass."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


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
            self._migrate_columns(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(tweets)")
        existing = {row[1] for row in cursor.fetchall()}
        migrations = [
            ("is_ai_related", "INTEGER DEFAULT 0"),
            ("sent", "INTEGER DEFAULT 0"),
            ("sent_at", "TEXT"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE tweets ADD COLUMN {col_name} {col_def}"
                )

    def save_tweet(self, tweet: Dict[str, Any], session_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tweets "
                "(id, text, author, url, timestamp, likes, retweets, "
                "feed_type, crawl_session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _get(tweet,"id"), _get(tweet,"text"), _get(tweet,"author"), _get(tweet,"url"),
                    _get(tweet,"timestamp",""), _get(tweet,"likes",0),
                    _get(tweet,"retweets",0), _get(tweet,"feed_type"), session_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def save_tweets(self, tweets: List[Dict[str, Any]], session_id: str) -> int:
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

    def mark_ai_related(self, tweet_ids: List[str]) -> int:
        """Mark tweets as AI-related. Returns count updated."""
        if not tweet_ids:
            return 0
        conn = sqlite3.connect(self.db_path)
        try:
            placeholders = ",".join("?" for _ in tweet_ids)
            cursor = conn.execute(
                f"UPDATE tweets SET is_ai_related = 1 "
                f"WHERE id IN ({placeholders})",
                tweet_ids,
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_unsent_ai_tweets(self) -> List[dict]:
        """Return tweets where is_ai_related=1 AND sent=0."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE is_ai_related = 1 AND sent = 0 "
                "ORDER BY id",
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_all_tweet_ids(self) -> set[str]:
        """Return all tweet ids currently in the DB."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("SELECT id FROM tweets")
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_existing_ids(self, ids: list) -> set[str]:
        """Return which of the given ids already exist in the DB."""
        if not ids:
            return set()
        conn = sqlite3.connect(self.db_path)
        try:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"SELECT id FROM tweets WHERE id IN ({placeholders})", ids
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_last_crawl_start(self) -> Optional[str]:
        """Return the earliest tweet timestamp from the most recent completed crawl session."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT MIN(t.timestamp) FROM tweets t "
                "JOIN crawl_sessions s ON t.crawl_session_id = s.id "
                "WHERE s.id = (SELECT id FROM crawl_sessions "
                "WHERE completed_at IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1)"
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def mark_sent(self, tweet_ids: List[str]) -> int:
        """Mark tweets as sent (sent=1, sent_at=now()). Returns count updated."""
        if not tweet_ids:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            placeholders = ",".join("?" for _ in tweet_ids)
            cursor = conn.execute(
                f"UPDATE tweets SET sent = 1, sent_at = ? "
                f"WHERE id IN ({placeholders})",
                [now, *tweet_ids],
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
