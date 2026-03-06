"""Tests for TweetDatabase WAL mode and connection reuse (context manager)."""
import sqlite3
import threading

import pytest

from src.storage.db import TweetDatabase


@pytest.fixture
def db(tmp_path):
    return TweetDatabase(str(tmp_path / "test.db"))


def _make_tweet(tweet_id="1", text="AI tweet about LLMs"):
    return {
        "id": tweet_id,
        "text": text,
        "author": "testuser",
        "url": f"https://twitter.com/testuser/status/{tweet_id}",
        "timestamp": "2026-03-07T10:00:00Z",
        "likes": 5,
        "retweets": 2,
        "feed_type": "for_you",
    }


class TestWALMode:
    def test_wal_journal_mode_enabled(self, db):
        """Database should use WAL journal mode for better concurrent performance."""
        with db.connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal", f"Expected WAL mode, got {mode!r}"

    def test_synchronous_normal(self, db):
        """PRAGMA synchronous should be NORMAL (1) for speed without data loss risk."""
        with db.connection() as conn:
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        # 1 = NORMAL
        assert sync == 1, f"Expected synchronous=NORMAL (1), got {sync}"


class TestConnectionReuse:
    def test_context_manager_reuses_connection(self, db):
        """Nested connection() calls should share the same connection object."""
        with db.connection() as outer:
            inner_conn_id = id(db._conn)
            with db.connection() as inner:
                assert inner is outer, "Nested connection() must yield same connection"
            # _conn still set while outer block is active
            assert db._conn is not None

        # After outer exits, connection should be released
        assert db._conn is None

    def test_connection_released_after_context(self, db):
        """_conn must be None after exiting connection() block."""
        with db.connection() as conn:
            assert db._conn is conn
        assert db._conn is None

    def test_multiple_operations_share_connection(self, db):
        """All DB operations inside a connection() block share one connection."""
        opened = []
        original_connect = sqlite3.connect

        def patched_connect(path, **kwargs):
            conn = original_connect(path, **kwargs)
            opened.append(conn)
            return conn

        import src.storage.db as db_module
        original = db_module.sqlite3.connect
        db_module.sqlite3.connect = patched_connect

        try:
            with db.connection():
                session_id = db.create_session()
                db.save_tweets([_make_tweet("1"), _make_tweet("2")], session_id)
                db.mark_ai_related(["1"])
                db.get_ai_classification(["1", "2"])
        finally:
            db_module.sqlite3.connect = original

        # Only ONE new connection should have been opened during the block
        # (the one created by our outer connection() call).
        assert len(opened) == 1, (
            f"Expected 1 connection inside context manager, got {len(opened)}"
        )

    def test_standalone_operations_open_own_connection(self, db):
        """Without an outer context manager, each method opens/closes its own connection."""
        opened = []
        original_connect = sqlite3.connect

        def patched_connect(path, **kwargs):
            conn = original_connect(path, **kwargs)
            opened.append(conn)
            return conn

        import src.storage.db as db_module
        db_module.sqlite3.connect = patched_connect
        try:
            session_id = db.create_session()
            db.save_tweets([_make_tweet("10"), _make_tweet("11")], session_id)
            db.mark_ai_related(["10"])
        finally:
            db_module.sqlite3.connect = original_connect

        assert len(opened) == 3, (
            f"Expected 3 separate connections for 3 standalone calls, got {len(opened)}"
        )


class TestFunctionalCorrectness:
    """Ensure refactored connection logic doesn't break existing behaviour."""

    def test_save_and_retrieve_tweets(self, db):
        session_id = db.create_session()
        tweets = [_make_tweet(str(i)) for i in range(5)]
        count = db.save_tweets(tweets, session_id)
        assert count == 5

        rows = db.get_tweets_by_session(session_id)
        assert len(rows) == 5

    def test_deduplication_still_works(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("dup"), session_id)
        result = db.save_tweet(_make_tweet("dup"), session_id)
        assert result is False

    def test_mark_ai_related_and_query(self, db):
        session_id = db.create_session()
        db.save_tweets([_make_tweet("ai1"), _make_tweet("ai2"), _make_tweet("nope")], session_id)
        db.mark_ai_related(["ai1", "ai2"])
        rows = db.get_non_duplicate_ai_tweets()
        ids = {r["id"] for r in rows}
        assert "ai1" in ids
        assert "ai2" in ids
        assert "nope" not in ids

    def test_mark_sent(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("s1"), session_id)
        db.mark_ai_related(["s1"])
        rows_before = db.get_non_duplicate_ai_tweets()
        assert any(r["id"] == "s1" for r in rows_before)

        db.mark_sent(["s1"])
        rows_after = db.get_non_duplicate_ai_tweets()
        assert not any(r["id"] == "s1" for r in rows_after)

    def test_batch_mark_duplicates(self, db):
        session_id = db.create_session()
        db.save_tweets([_make_tweet("orig"), _make_tweet("dup1"), _make_tweet("dup2")], session_id)
        db.mark_ai_related(["orig", "dup1", "dup2"])
        db.batch_mark_duplicates([("dup1", "orig"), ("dup2", "orig")])

        rows = db.get_non_duplicate_ai_tweets()
        ids = {r["id"] for r in rows}
        assert "orig" in ids
        assert "dup1" not in ids
        assert "dup2" not in ids

    def test_connection_reuse_within_block(self, db):
        """Operations inside a connection() block still produce correct results."""
        with db.connection():
            session_id = db.create_session()
            db.save_tweets([_make_tweet("r1"), _make_tweet("r2")], session_id)
            db.mark_ai_related(["r1"])
            rows = db.get_non_duplicate_ai_tweets()

        assert len(rows) == 1
        assert rows[0]["id"] == "r1"

    def test_get_ai_classification(self, db):
        session_id = db.create_session()
        db.save_tweets([_make_tweet("c1"), _make_tweet("c2")], session_id)
        db.mark_ai_related(["c1"])
        result = db.get_ai_classification(["c1", "c2", "unknown"])
        assert result["c1"] == 1
        assert result["c2"] == 0
        assert "unknown" not in result

    def test_save_embedding_and_retrieve(self, db):
        import json
        session_id = db.create_session()
        db.save_tweet(_make_tweet("emb1"), session_id)
        embedding = json.dumps([0.1, 0.2, 0.3])
        db.save_embedding("emb1", embedding)
        rows = db.get_tweets_with_embeddings()
        assert any(r["id"] == "emb1" for r in rows)
