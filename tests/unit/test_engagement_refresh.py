"""Tests for engagement refresh on re-crawl (update_engagements / save_tweets)."""
import tempfile
import os
import pytest

from src.storage.db import TweetDatabase


def _make_tweet(tweet_id: str, likes: int, retweets: int, feed_type: str = "for_you") -> dict:
    return {
        "id": tweet_id,
        "text": f"Tweet {tweet_id}",
        "author": "testuser",
        "url": f"https://x.com/testuser/status/{tweet_id}",
        "timestamp": "2026-03-07T00:00:00Z",
        "likes": likes,
        "retweets": retweets,
        "feed_type": feed_type,
        "thread_root_id": None,
    }


@pytest.fixture
def db(tmp_path):
    db_file = str(tmp_path / "test.db")
    return TweetDatabase(db_file)


class TestUpdateEngagements:
    def test_update_increases_likes(self, db):
        session = db.create_session()
        tweet = _make_tweet("1", likes=10, retweets=2)
        db.save_tweets([tweet], session)

        # Re-crawl with higher engagement
        updated = _make_tweet("1", likes=500, retweets=50)
        db.update_engagements([updated])

        with db._auto_conn() as conn:
            row = conn.execute("SELECT likes, retweets FROM tweets WHERE id = '1'").fetchone()
        assert row[0] == 500
        assert row[1] == 50

    def test_update_does_not_decrease_engagement(self, db):
        """If the new value is lower (e.g. API inconsistency), keep the higher stored value."""
        session = db.create_session()
        tweet = _make_tweet("2", likes=1000, retweets=100)
        db.save_tweets([tweet], session)

        lower = _make_tweet("2", likes=5, retweets=3)
        db.update_engagements([lower])

        with db._auto_conn() as conn:
            row = conn.execute("SELECT likes, retweets FROM tweets WHERE id = '2'").fetchone()
        assert row[0] == 1000
        assert row[1] == 100

    def test_update_engagements_returns_row_count(self, db):
        session = db.create_session()
        tweets = [_make_tweet(str(i), likes=i, retweets=0) for i in range(1, 4)]
        db.save_tweets(tweets, session)

        updated = [_make_tweet(str(i), likes=i * 10, retweets=i) for i in range(1, 4)]
        count = db.update_engagements(updated)
        assert count == 3

    def test_update_engagements_empty_list(self, db):
        count = db.update_engagements([])
        assert count == 0

    def test_update_engagements_nonexistent_id_is_ignored(self, db):
        """Updating a non-existent tweet ID should not raise, just do nothing."""
        count = db.update_engagements([_make_tweet("nonexistent", 999, 99)])
        # rowcount may be 0 or 1 depending on SQLite version; should not raise
        assert count >= 0


class TestSavetweetsRefreshesEngagement:
    def test_save_tweets_refreshes_engagement_for_duplicates(self, db):
        session1 = db.create_session()
        tweet = _make_tweet("100", likes=10, retweets=1)
        inserted = db.save_tweets([tweet], session1)
        assert inserted == 1

        session2 = db.create_session()
        tweet_updated = _make_tweet("100", likes=9999, retweets=500)
        inserted2 = db.save_tweets([tweet_updated], session2)
        # Duplicate — should not count as new insert
        assert inserted2 == 0

        with db._auto_conn() as conn:
            row = conn.execute("SELECT likes, retweets FROM tweets WHERE id = '100'").fetchone()
        # Engagement should be updated to the higher values
        assert row[0] == 9999
        assert row[1] == 500

    def test_save_tweets_new_tweet_returns_correct_count(self, db):
        session = db.create_session()
        tweets = [_make_tweet(str(i), likes=i, retweets=0) for i in range(5)]
        count = db.save_tweets(tweets, session)
        assert count == 5

    def test_save_tweets_mixed_new_and_existing(self, db):
        session1 = db.create_session()
        existing = _make_tweet("old", likes=1, retweets=0)
        db.save_tweets([existing], session1)

        session2 = db.create_session()
        new = _make_tweet("new", likes=5, retweets=2)
        existing_updated = _make_tweet("old", likes=999, retweets=77)
        count = db.save_tweets([new, existing_updated], session2)
        # Only 1 new insert
        assert count == 1

        with db._auto_conn() as conn:
            row = conn.execute("SELECT likes, retweets FROM tweets WHERE id = 'old'").fetchone()
        assert row[0] == 999
        assert row[1] == 77
