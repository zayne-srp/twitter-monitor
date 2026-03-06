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


class TestGetAllTweetIds:
    def test_returns_all_ids(self, db):
        session_id = db.create_session()
        db.save_tweets(
            [_make_tweet("10"), _make_tweet("20"), _make_tweet("30")],
            session_id,
        )
        ids = db.get_all_tweet_ids()
        assert ids == {"10", "20", "30"}

    def test_returns_empty_set(self, db):
        ids = db.get_all_tweet_ids()
        assert ids == set()


class TestGetExistingIds:
    def test_returns_matching_ids(self, db):
        session_id = db.create_session()
        db.save_tweets([_make_tweet("10"), _make_tweet("20")], session_id)
        existing = db.get_existing_ids(["10", "20", "99"])
        assert existing == {"10", "20"}

    def test_returns_empty_for_no_match(self, db):
        session_id = db.create_session()
        db.save_tweets([_make_tweet("10")], session_id)
        existing = db.get_existing_ids(["99", "100"])
        assert existing == set()

    def test_returns_empty_for_empty_input(self, db):
        existing = db.get_existing_ids([])
        assert existing == set()


class TestGetLastCrawlStart:
    def test_returns_earliest_timestamp_from_last_session(self, db):
        session_id = db.create_session()
        db.save_tweets(
            [
                {**_make_tweet("1"), "timestamp": "2026-03-04T10:00:00Z"},
                {**_make_tweet("2"), "timestamp": "2026-03-04T08:00:00Z"},
                {**_make_tweet("3"), "timestamp": "2026-03-04T12:00:00Z"},
            ],
            session_id,
        )
        db.complete_session(session_id, total_tweets=3, ai_tweets_count=0)
        result = db.get_last_crawl_start()
        assert result == "2026-03-04T08:00:00Z"

    def test_returns_none_when_no_sessions(self, db):
        result = db.get_last_crawl_start()
        assert result is None

    def test_ignores_incomplete_sessions(self, db):
        # Create a session but don't complete it
        session_id = db.create_session()
        db.save_tweets([_make_tweet("1")], session_id)
        result = db.get_last_crawl_start()
        assert result is None

    def test_returns_from_latest_completed_session(self, db):
        # First session (completed)
        s1 = db.create_session()
        db.save_tweets(
            [{**_make_tweet("1"), "timestamp": "2026-03-03T08:00:00Z"}], s1,
        )
        db.complete_session(s1, total_tweets=1, ai_tweets_count=0)

        # Second session (completed, more recent)
        s2 = db.create_session()
        db.save_tweets(
            [{**_make_tweet("2"), "timestamp": "2026-03-04T09:00:00Z"}], s2,
        )
        db.complete_session(s2, total_tweets=1, ai_tweets_count=0)

        result = db.get_last_crawl_start()
        assert result == "2026-03-04T09:00:00Z"


class TestSaveTweetsBatchBehavior:
    """Tests specific to the batch-insert implementation of save_tweets."""

    def test_large_batch_correctness(self, db):
        """All tweets in a large batch should be persisted exactly once."""
        session_id = db.create_session()
        tweets = [_make_tweet(str(i)) for i in range(100)]
        count = db.save_tweets(tweets, session_id)
        assert count == 100
        stored = db.get_tweets_by_session(session_id)
        assert len(stored) == 100

    def test_batch_with_all_duplicates(self, db):
        """Batch of entirely duplicate tweets should return 0."""
        session_id = db.create_session()
        tweets = [_make_tweet(str(i)) for i in range(5)]
        db.save_tweets(tweets, session_id)
        count = db.save_tweets(tweets, session_id)
        assert count == 0

    def test_batch_preserves_tweet_fields(self, db):
        """Fields should be stored verbatim by the batch insert."""
        session_id = db.create_session()
        tweet = {
            "id": "batch_field_test",
            "text": "Field preservation test",
            "author": "field_author",
            "url": "https://twitter.com/field_author/status/batch_field_test",
            "timestamp": "2026-03-07T00:00:00Z",
            "likes": 42,
            "retweets": 7,
            "feed_type": "following",
            "thread_root_id": "root_123",
        }
        db.save_tweets([tweet], session_id)
        stored = db.get_tweets_by_session(session_id)
        assert len(stored) == 1
        row = stored[0]
        assert row["id"] == "batch_field_test"
        assert row["text"] == "Field preservation test"
        assert row["author"] == "field_author"
        assert row["likes"] == 42
        assert row["retweets"] == 7
        assert row["feed_type"] == "following"
        assert row["thread_root_id"] == "root_123"

    def test_batch_mixed_new_and_duplicate(self, db):
        """Partial overlap: only truly new tweets are counted."""
        session_id = db.create_session()
        # Pre-insert tweets 0-4
        db.save_tweets([_make_tweet(str(i)) for i in range(5)], session_id)
        # Batch that overlaps 3-4 (dup) + 5-9 (new)
        mixed = [_make_tweet(str(i)) for i in range(3, 10)]
        count = db.save_tweets(mixed, session_id)
        assert count == 5  # only 5-9 are new
