import sqlite3

import pytest

from src.storage.db import TweetDatabase


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    return TweetDatabase(db_path)


def _make_tweet(tweet_id="1", text="AI test tweet"):
    return {
        "id": tweet_id,
        "text": text,
        "author": "testuser",
        "url": f"https://twitter.com/testuser/status/{tweet_id}",
        "timestamp": "2026-03-04T10:00:00Z",
        "likes": 5,
        "retweets": 2,
        "feed_type": "for_you",
    }


class TestDatabaseInit:
    def test_creates_tables(self, db):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "tweets" in tables
        assert "crawl_sessions" in tables


class TestSaveTweet:
    def test_save_single_tweet(self, db):
        session_id = db.create_session()
        result = db.save_tweet(_make_tweet("100"), session_id)
        assert result is True

    def test_duplicate_tweet_ignored(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("100"), session_id)
        result = db.save_tweet(_make_tweet("100"), session_id)
        assert result is False

    def test_save_different_tweets(self, db):
        session_id = db.create_session()
        assert db.save_tweet(_make_tweet("1"), session_id) is True
        assert db.save_tweet(_make_tweet("2"), session_id) is True


class TestSaveTweets:
    def test_batch_save(self, db):
        session_id = db.create_session()
        tweets = [_make_tweet(str(i)) for i in range(5)]
        count = db.save_tweets(tweets, session_id)
        assert count == 5

    def test_batch_save_with_duplicates(self, db):
        session_id = db.create_session()
        db.save_tweet(_make_tweet("1"), session_id)
        tweets = [_make_tweet("1"), _make_tweet("2"), _make_tweet("3")]
        count = db.save_tweets(tweets, session_id)
        assert count == 2

    def test_batch_save_empty_list(self, db):
        session_id = db.create_session()
        count = db.save_tweets([], session_id)
        assert count == 0


class TestGetTweetsBySession:
    def test_get_tweets(self, db):
        session_id = db.create_session()
        db.save_tweets(
            [_make_tweet("1", "AI tweet"), _make_tweet("2", "LLM tweet")],
            session_id,
        )
        tweets = db.get_tweets_by_session(session_id)
        assert len(tweets) == 2
        assert tweets[0]["id"] == "1"
        assert tweets[1]["id"] == "2"

    def test_get_tweets_empty_session(self, db):
        session_id = db.create_session()
        tweets = db.get_tweets_by_session(session_id)
        assert tweets == []


class TestCrawlSessions:
    def test_create_session(self, db):
        session_id = db.create_session()
        assert session_id is not None
        assert len(session_id) > 0

    def test_complete_session(self, db):
        session_id = db.create_session()
        db.complete_session(session_id, total_tweets=50, ai_tweets_count=15)
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute(
            "SELECT completed_at, total_tweets, ai_tweets_count "
            "FROM crawl_sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None  # completed_at set
        assert row[1] == 50
        assert row[2] == 15


class TestGetRecentTweets:
    def test_get_recent(self, db):
        session_id = db.create_session()
        db.save_tweets(
            [_make_tweet("1"), _make_tweet("2"), _make_tweet("3")],
            session_id,
        )
        recent = db.get_recent_tweets(hours=24)
        assert len(recent) == 3

    def test_get_recent_empty(self, db):
        recent = db.get_recent_tweets(hours=24)
        assert recent == []
