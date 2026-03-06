import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

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
    """SQLite-backed tweet storage.

    Connections are opened lazily and reused across calls within the same
    logical operation via the :meth:`connection` context manager.  When no
    outer context manager is active, each public method transparently creates
    and closes its own connection (backward-compatible behaviour).

    WAL journal mode is enabled on first connect so that readers and writers
    do not block each other — important when the indexer and crawler run in
    the same process.
    """

    def __init__(self, db_path: str = "data/tweets.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that reuses an open connection when possible.

        If a connection is already open (e.g. the caller is inside an outer
        ``with db.connection()`` block) the same connection is yielded and
        *not* closed on exit — the outermost context manager owns the
        lifecycle.

        Usage::

            with db.connection() as conn:
                conn.execute("SELECT ...")
                db.some_method()   # also uses the same connection
        """
        if self._conn is not None:
            # Re-entrant: yield the existing connection without closing it.
            yield self._conn
            return

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._conn = conn
        try:
            yield conn
        finally:
            self._conn = None
            conn.close()

    @contextmanager
    def _auto_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Internal helper: yields the active connection or opens a temporary one."""
        if self._conn is not None:
            yield self._conn
        else:
            with self.connection() as conn:
                yield conn

    # ------------------------------------------------------------------ #
    # Initialisation
    # ------------------------------------------------------------------ #

    def _init_db(self) -> None:
        with self.connection() as conn:
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

    # ------------------------------------------------------------------ #
    # Write operations
    # ------------------------------------------------------------------ #

    def save_tweet(self, tweet: Dict[str, Any], session_id: str) -> bool:
        """Insert a single tweet. Returns True if the tweet was new (not a duplicate)."""
        with self._auto_conn() as conn:
            cursor = conn.execute(_INSERT_TWEET_SQL, _tweet_row(tweet, session_id))
            conn.commit()
            return cursor.rowcount > 0

    def save_tweets(self, tweets: List[Dict[str, Any]], session_id: str) -> int:
        """Batch-insert tweets; also refresh engagement for already-stored tweets.

        Uses ``executemany`` + ``INSERT OR IGNORE`` for new tweets, then
        :meth:`update_engagements` to refresh likes/retweets on duplicates so
        that engagement counts never go stale across crawl runs.

        Returns:
            Number of tweets that were actually inserted (i.e. not duplicates).
        """
        if not tweets:
            return 0

        rows = [_tweet_row(t, session_id) for t in tweets]
        pairs = [
            (_get(t, "likes", 0), _get(t, "retweets", 0), _get(t, "id"))
            for t in tweets
            if _get(t, "id")
        ]
        with self._auto_conn() as conn:
            before = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
            conn.executemany(_INSERT_TWEET_SQL, rows)
            # Refresh engagement (likes / retweets) for tweets that were already
            # in the DB (i.e. INSERT OR IGNORE silently skipped them).
            # MAX() ensures we only ever increase engagement counts, never decrease.
            if pairs:
                conn.executemany(
                    "UPDATE tweets "
                    "SET likes = MAX(likes, ?), retweets = MAX(retweets, ?) "
                    "WHERE id = ?",
                    pairs,
                )
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]

        return after - before

    def update_engagements(self, tweets: List[Dict[str, Any]]) -> int:
        """Update likes and retweets for existing tweets.

        Only updates rows whose engagement counts have actually increased,
        so the DB always holds the peak observed engagement for each tweet.

        Args:
            tweets: List of tweet dicts/dataclasses with ``id``, ``likes``,
                and ``retweets`` fields.  Tweets with no ``id`` are skipped.

        Returns:
            Number of rows updated (those where at least one counter grew).
        """
        if not tweets:
            return 0

        pairs = [
            (_get(t, "likes", 0), _get(t, "retweets", 0), _get(t, "id"))
            for t in tweets
            if _get(t, "id")
        ]
        if not pairs:
            return 0

        with self._auto_conn() as conn:
            cursor = conn.executemany(
                "UPDATE tweets "
                "SET likes = MAX(likes, ?), retweets = MAX(retweets, ?) "
                "WHERE id = ?",
                pairs,
            )
            conn.commit()
            return cursor.rowcount

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._auto_conn() as conn:
            conn.execute(
                "INSERT INTO crawl_sessions (id, started_at) VALUES (?, ?)",
                (session_id, now),
            )
            conn.commit()
            return session_id

    def complete_session(
        self, session_id: str, total_tweets: int, ai_tweets_count: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._auto_conn() as conn:
            conn.execute(
                "UPDATE crawl_sessions "
                "SET completed_at = ?, total_tweets = ?, ai_tweets_count = ? "
                "WHERE id = ?",
                (now, total_tweets, ai_tweets_count, session_id),
            )
            conn.commit()

    def mark_ai_related(self, tweet_ids: List[str]) -> int:
        """Mark tweets as AI-related. Returns count updated."""
        if not tweet_ids:
            return 0
        with self._auto_conn() as conn:
            placeholders = ",".join("?" for _ in tweet_ids)
            cursor = conn.execute(
                f"UPDATE tweets SET is_ai_related = 1 "
                f"WHERE id IN ({placeholders})",
                tweet_ids,
            )
            conn.commit()
            return cursor.rowcount

    def save_followed_account(self, username: str, verified: bool = True) -> None:
        now = datetime.now(timezone.utc).isoformat()
        verified_at = now if verified else None
        with self._auto_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO followed_accounts (username, followed_at, verified_at) VALUES (?, ?, ?)",
                (username.lstrip("@"), now, verified_at),
            )
            conn.commit()

    def save_embedding(self, tweet_id: str, embedding_json: str) -> None:
        with self._auto_conn() as conn:
            conn.execute(
                "UPDATE tweets SET embedding = ? WHERE id = ?",
                (embedding_json, tweet_id),
            )
            conn.commit()

    def mark_duplicate(self, tweet_id: str, duplicate_of: str) -> None:
        """Mark a tweet as a semantic duplicate of another tweet."""
        self.batch_mark_duplicates([(tweet_id, duplicate_of)])

    def batch_mark_duplicates(self, pairs: List[tuple]) -> int:
        """Mark multiple tweets as semantic duplicates in a single transaction.

        Args:
            pairs: Iterable of (tweet_id, duplicate_of) tuples.

        Returns:
            Number of rows updated.
        """
        pairs = list(pairs)
        if not pairs:
            return 0
        with self._auto_conn() as conn:
            cursor = conn.executemany(
                "UPDATE tweets SET is_duplicate = 1, duplicate_of = ? WHERE id = ?",
                [(dup_of, tid) for tid, dup_of in pairs],
            )
            conn.commit()
            return cursor.rowcount

    def mark_sent(self, tweet_ids: List[str]) -> int:
        """Mark tweets as sent (sent=1, sent_at=now()). Returns count updated."""
        if not tweet_ids:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        with self._auto_conn() as conn:
            placeholders = ",".join("?" for _ in tweet_ids)
            cursor = conn.execute(
                f"UPDATE tweets SET sent = 1, sent_at = ? "
                f"WHERE id IN ({placeholders})",
                [now, *tweet_ids],
            )
            conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------ #
    # Read operations
    # ------------------------------------------------------------------ #

    def get_tweets_by_session(self, session_id: str) -> List[dict]:
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tweets WHERE crawl_session_id = ? ORDER BY id",
                (session_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_tweets(self, hours: int = 24) -> List[dict]:
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE created_at >= datetime('now', ? || ' hours') "
                "ORDER BY created_at DESC",
                (f"-{hours}",),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_unsent_ai_tweets(self) -> List[dict]:
        """Return tweets where is_ai_related=1 AND sent=0."""
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE is_ai_related = 1 AND sent = 0 "
                "ORDER BY id",
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all_tweet_ids(self) -> set:
        """Return tweet ids from the last 7 days."""
        with self._auto_conn() as conn:
            cursor = conn.execute(
                "SELECT id FROM tweets WHERE created_at > datetime('now', '-7 days')"
            )
            return {row[0] for row in cursor.fetchall()}

    def get_existing_ids(self, ids: list) -> set:
        """Return which of the given ids already exist in the DB (last 7 days only)."""
        if not ids:
            return set()
        with self._auto_conn() as conn:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"SELECT id FROM tweets WHERE id IN ({placeholders}) AND created_at > datetime('now', '-7 days')",
                ids,
            )
            return {row[0] for row in cursor.fetchall()}

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
        with self._auto_conn() as conn:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"SELECT id, is_ai_related FROM tweets WHERE id IN ({placeholders})",
                ids,
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_last_crawl_start(self) -> Optional[str]:
        """Return the earliest tweet timestamp from the most recent completed crawl session."""
        with self._auto_conn() as conn:
            cursor = conn.execute(
                "SELECT MIN(t.timestamp) FROM tweets t "
                "JOIN crawl_sessions s ON t.crawl_session_id = s.id "
                "WHERE s.id = (SELECT id FROM crawl_sessions "
                "WHERE completed_at IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1)"
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_followed_accounts(self) -> set:
        with self._auto_conn() as conn:
            cursor = conn.execute("SELECT username FROM followed_accounts")
            return {row[0] for row in cursor.fetchall()}

    def get_tweets_with_embeddings(self) -> List[dict]:
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT id, text, author, url, timestamp, embedding FROM tweets WHERE embedding IS NOT NULL"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_tweets_missing_embeddings(self, limit: int = 50) -> List[Dict]:
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, text FROM tweets WHERE embedding IS NULL AND is_ai_related = 1 LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_tweets_with_embeddings_recent(self, hours: int = 48) -> List[dict]:
        """Return tweets from last N hours that have an embedding."""
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tweets "
                "WHERE embedding IS NOT NULL "
                "AND created_at >= datetime('now', ? || ' hours') "
                "ORDER BY created_at DESC",
                (f"-{hours}",),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_non_duplicate_ai_tweets(self) -> List[dict]:
        """Return AI-related tweets that are not duplicates and not yet sent.

        Rows are ordered by a composite engagement score so the most viral /
        impactful tweets appear first in the daily report:

            score = retweets * 3 + likes

        Ties are broken by timestamp descending (newest first), then by
        id for a fully deterministic result.
        """
        with self._auto_conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT *, (COALESCE(retweets, 0) * 3 + COALESCE(likes, 0)) AS engagement_score "
                "FROM tweets "
                "WHERE is_ai_related = 1 AND is_duplicate = 0 AND sent = 0 "
                "ORDER BY engagement_score DESC, timestamp DESC, id",
            )
            return [dict(row) for row in cursor.fetchall()]
