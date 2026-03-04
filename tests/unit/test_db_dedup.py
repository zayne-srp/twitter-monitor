import sqlite3

import pytest

from src.crawler.twitter_crawler import Tweet
from src.storage.db import TweetDatabase


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    return TweetDatabase(db_path)


def _make_tweet(tweet_id: str = "1", text: str = "test tweet") -> Tweet:
    return Tweet(
        id=tweet_id,
        text=text,
        author="testuser",
        url=f"https://twitter.com/testuser/status/{tweet_id}",
        timestamp="2026-03-04T10:00:00Z",
        likes=5,
        retweets=2,
        feed_type="for_you",
    )


class TestMigrationColumns:
    """New columns should exist after init."""

    def test_tweets_table_has_is_ai_related_column(self, db):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute("PRAGMA table_info(tweets)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "is_ai_related" in columns

    def test_tweets_table_has_sent_column(self, db):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute("PRAGMA table_info(tweets)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "sent" in columns

    def test_tweets_table_has_sent_at_column(self, db):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute("PRAGMA table_info(tweets)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "sent_at" in columns

    def test_new_columns_default_values(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tweets WHERE id = '1'").fetchone()
        conn.close()
        assert row["is_ai_related"] == 0
        assert row["sent"] == 0
        assert row["sent_at"] is None

    def test_migration_on_existing_db(self, tmp_path):
        """Simulate an existing DB without new columns, then re-init."""
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE tweets ("
            "id TEXT PRIMARY KEY, text TEXT, author TEXT, url TEXT, "
            "timestamp TEXT, likes INTEGER, retweets INTEGER, "
            "feed_type TEXT, crawl_session_id TEXT, created_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE crawl_sessions ("
            "id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, "
            "total_tweets INTEGER, ai_tweets_count INTEGER)"
        )
        conn.execute(
            "INSERT INTO tweets VALUES "
            "('old1', 'text', 'user', 'url', 'ts', 0, 0, 'for_you', 's1', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        # Re-init should add columns without losing data
        db = TweetDatabase(db_path)
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tweets WHERE id = 'old1'").fetchone()
        conn.close()
        assert row["is_ai_related"] == 0
        assert row["sent"] == 0
        assert row["sent_at"] is None


class TestMarkAiRelated:
    def test_mark_single_tweet(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        count = db.mark_ai_related(["1"])
        assert count == 1

    def test_mark_multiple_tweets(self, db):
        session_id = db.create_session()
        for i in range(5):
            db.save_tweet(_make_tweet(str(i)), session_id)
        count = db.mark_ai_related(["0", "2", "4"])
        assert count == 3

    def test_mark_nonexistent_tweet(self, db):
        count = db.mark_ai_related(["nonexistent"])
        assert count == 0

    def test_mark_empty_list(self, db):
        count = db.mark_ai_related([])
        assert count == 0

    def test_mark_sets_column_value(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        db.mark_ai_related(["1"])
        conn = sqlite3.connect(db.db_path)
        row = conn.execute(
            "SELECT is_ai_related FROM tweets WHERE id = '1'"
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_mark_idempotent(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        db.mark_ai_related(["1"])
        count = db.mark_ai_related(["1"])
        # Still returns 1 because UPDATE matches the row
        assert count == 1


class TestGetUnsentAiTweets:
    def test_returns_only_ai_unsent(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1", "AI tweet"), session_id)
        db.save_tweet(_make_tweet("2", "not AI"), session_id)
        db.save_tweet(_make_tweet("3", "another AI"), session_id)
        db.mark_ai_related(["1", "3"])

        unsent = db.get_unsent_ai_tweets()
        ids = {t["id"] for t in unsent}
        assert ids == {"1", "3"}

    def test_excludes_sent_tweets(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        db.save_tweet(_make_tweet("2"), session_id)
        db.mark_ai_related(["1", "2"])
        db.mark_sent(["1"])

        unsent = db.get_unsent_ai_tweets()
        assert len(unsent) == 1
        assert unsent[0]["id"] == "2"

    def test_empty_when_no_ai_tweets(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        unsent = db.get_unsent_ai_tweets()
        assert unsent == []

    def test_empty_when_all_sent(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        db.mark_ai_related(["1"])
        db.mark_sent(["1"])
        unsent = db.get_unsent_ai_tweets()
        assert unsent == []

    def test_returns_dict_with_expected_keys(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1", "AI tweet text"), session_id)
        db.mark_ai_related(["1"])
        unsent = db.get_unsent_ai_tweets()
        assert len(unsent) == 1
        row = unsent[0]
        assert row["id"] == "1"
        assert row["text"] == "AI tweet text"
        assert row["author"] == "testuser"
        assert row["feed_type"] == "for_you"


class TestMarkSent:
    def test_mark_single_sent(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        db.mark_ai_related(["1"])
        count = db.mark_sent(["1"])
        assert count == 1

    def test_mark_multiple_sent(self, db):
        session_id = db.create_session()
        for i in range(3):
            db.save_tweet(_make_tweet(str(i)), session_id)
        db.mark_ai_related(["0", "1", "2"])
        count = db.mark_sent(["0", "1", "2"])
        assert count == 3

    def test_mark_sent_sets_sent_at(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        db.mark_sent(["1"])
        conn = sqlite3.connect(db.db_path)
        row = conn.execute(
            "SELECT sent, sent_at FROM tweets WHERE id = '1'"
        ).fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1] is not None  # sent_at should be set

    def test_mark_empty_list(self, db):
        count = db.mark_sent([])
        assert count == 0

    def test_mark_nonexistent_tweet(self, db):
        count = db.mark_sent(["nonexistent"])
        assert count == 0
