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

_INSERT_TWEET_SQL = (
    "INSERT OR IGNORE INTO tweets "
    "(id, text, author, url, timestamp, likes, retweets, "
    "feed_type, crawl_session_id, thread_root_id) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# Indexes that speed up the most common query patterns.
# All use CREATE INDEX IF NOT EXISTS so they are safe to apply on existing DBs.
_CREATE_INDEXES = [
    # Report generation: WHERE is_ai_related=1 AND is_duplicate=0 AND sent=0
    "CREATE INDEX IF NOT EXISTS idx_tweets_report ON tweets (is_ai_related, is_duplicate, sent)",
    # Embedding queries: WHERE embedding IS NOT NULL / IS NULL AND is_ai_related=1
    "CREATE INDEX IF NOT EXISTS idx_tweets_embedding ON tweets (is_ai_related, embedding)",
    # Time-range queries: WHERE created_at >= ...
    "CREATE INDEX IF NOT EXISTS idx_tweets_created_at ON tweets (created_at)",
    # Session lookup: WHERE crawl_session_id = ?
    "CREATE INDEX IF NOT EXISTS idx_tweets_session ON tweets (crawl_session_id)",
]


def _get(obj, key, default=None):
    """Get field from either a dict or a dataclass."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _tweet_row(tweet: Dict[str, Any], session_id: str) -> tuple:
    """Convert a tweet dict/dataclass to a DB row tuple."""
    return (
        _get(tweet, "id"),
        _get(tweet, "text"),
        _get(tweet, "author"),
        _get(tweet, "url"),
        _get(tweet, "timestamp", ""),
        _get(tweet, "likes", 0),
        _get(tweet, "retweets", 0),
        _get(tweet, "feed_type"),
        session_id,
        _get(tweet, "thread_root_id"),
    )


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
            conn.execute("""
CREATE TABLE IF NOT EXISTS followed_accounts (
    username TEXT PRIMARY KEY,
    followed_at TEXT NOT NULL
)
""")
            self._migrate_columns(conn)
            self._migrate_followed_accounts(conn)
            self._ensure_indexes(conn)
            conn.commit()
        finally:
            conn.close()

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        """Create performance indexes idempotently (IF NOT EXISTS)."""
        for ddl in _CREATE_INDEXES:
            conn.execute(ddl)
        logger.debug("DB indexes ensured (%d indexes)", len(_CREATE_INDEXES))

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(tweets)")
        existing = {row[1] for row in cursor.fetchall()}
        migrations = [
            ("is_ai_related", "INTEGER DEFAULT 0"),
            ("sent", "INTEGER DEFAULT 0"),
            ("sent_at", "TEXT"),
            ("embedding", "TEXT"),
            ("thread_root_id", "TEXT"),
            ("is_duplicate", "INTEGER DEFAULT 0"),
            ("duplicate_of", "TEXT"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE tweets ADD COLUMN {col_name} {col_def}"
                )

    def _migrate_followed_accounts(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(followed_accounts)")
        existing = {row[1] for row in cursor.fetchall()}
        if "verified_at" not in existing:
            conn.execute("ALTER TABLE followed_accounts ADD COLUMN verified_at TEXT")

    def save_tweet(self, tweet: Dict[str, Any], session_id: str) -> bool:
        """Insert a single tweet. Returns True if the tweet was new (not a duplicate)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(_INSERT_TWEET_SQL, _tweet_row(tweet, session_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def save_tweets(self, tweets: List[Dict[str, Any]], session_id: str) -> int:
        """Batch-insert tweets in a single connection/transaction.

        Uses ``executemany`` + ``INSERT OR IGNORE`` so duplicates are silently
        skipped.  The number of *newly inserted* rows is determined by comparing
        the row-count before and after the bulk insert, which avoids opening a
        separate connection for every tweet (the previous N+1 pattern).

        Returns:
            Number of tweets that were actually inserted (i.e. not duplicates).
        """
        if not tweets:
            return 0

        rows = [_tweet_row(t, session_id) for t in tweets]
        conn = sqlite3.connect(self.db_path)
        try:
            # Snapshot total rows before insert so we can compute newly inserted.
            before = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
            conn.executemany(_INSERT_TWEET_SQL, rows)
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
            return after - before
        finally:
            conn.close()

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
        """Return tweet ids from the last 7 days."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT id FROM tweets WHERE created_at > datetime('now', '-7 days')"
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_existing_ids(self, ids: list) -> set[str]:
        """Return which of the given ids already exist in the DB (last 7 days only)."""
        if not ids:
            return set()
        conn = sqlite3.connect(self.db_path)
        try:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"SELECT id FROM tweets WHERE id IN ({placeholders}) AND created_at > datetime('now', '-7 days')",
                ids
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()


    def get_ai_classification(self, ids: list) -> dict:
        """Return {tweet_id: is_ai_related} for the given ids that already exist in the DB.

        Only tweets already classified (i.e. present in the DB) are returned.
        Tweets not found are absent from the result dict — callers should treat
        them as needing classification.

        Args:
            ids: Tweet ID strings to look up.

        Returns:
            Mapping of tweet_id -> is_ai_related (0 or 1) for known tweets.
        """
        if not ids:
            return {}
        conn = sqlite3.connect(self.db_path)
        try:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"SELECT id, is_ai_related FROM tweets WHERE id IN ({placeholders})",
                ids,
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
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

    def get_followed_accounts(self) -> set:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("SELECT username FROM followed_accounts")
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def save_followed_account(self, username: str, verified: bool = True) -> None:
        now = datetime.now(timezone.utc).isoformat()
        verified_at = now if verified else None
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO followed_accounts (username, followed_at, verified_at) VALUES (?, ?, ?)",
                (username.lstrip("@"), now, verified_at),
            )
            conn.commit()
        finally:
            conn.close()

    def get_tweets_with_embeddings(self) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT id, text, author, url, timestamp, embedding FROM tweets WHERE embedding IS NOT NULL"
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def save_embedding(self, tweet_id: str, embedding_json: str) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE tweets SET embedding = ? WHERE id = ?",
                (embedding_json, tweet_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_tweets_missing_embeddings(self, limit: int = 50) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, text FROM tweets WHERE embedding IS NULL AND is_ai_related = 1 LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_tweets_with_embeddings_recent(self, hours: int = 48) -> List[dict]:
        """Return tweets from last N hours that have an embedding."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE embedding IS NOT NULL "
                "AND created_at >= datetime('now', ? || ' hours') "
                "ORDER BY created_at DESC",
                (f"-{hours}",),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def mark_duplicate(self, tweet_id: str, duplicate_of: str) -> None:
        """Mark a tweet as a semantic duplicate of another tweet."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE tweets SET is_duplicate = 1, duplicate_of = ? WHERE id = ?",
                (duplicate_of, tweet_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_non_duplicate_ai_tweets(self) -> List[dict]:
        """Return AI-related tweets that are not duplicates and not yet sent."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE is_ai_related = 1 AND is_duplicate = 0 AND sent = 0 "
                "ORDER BY id",
            )
            return [dict(row) for row in cursor.fetchall()]
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
