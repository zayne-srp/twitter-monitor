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


class TestDatabaseIndexes:
    """Verify that the expected performance indexes are created on init."""

    def test_indexes_created_on_new_db(self, db):
        """All four performance indexes should exist after init."""
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tweets'"
        )
        index_names = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "idx_tweets_report" in index_names
        assert "idx_tweets_embedding" in index_names
        assert "idx_tweets_created_at" in index_names
        assert "idx_tweets_session" in index_names

    def test_indexes_idempotent_on_existing_db(self, db):
        """Re-initialising the DB should not raise even when indexes already exist."""
        # Trigger _init_db a second time via a new TweetDatabase pointing to
        # the same file — should not raise any SQLite errors.
        db2 = TweetDatabase(db.db_path)
        conn = sqlite3.connect(db2.db_path)
        cursor = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='index' AND tbl_name='tweets'"
        )
        count = cursor.fetchone()[0]
        conn.close()
        assert count >= 4  # at minimum our 4 indexes

    def test_report_index_accelerates_query(self, db):
        """EXPLAIN QUERY PLAN should use idx_tweets_report for the report query."""
        conn = sqlite3.connect(db.db_path)
        rows = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM tweets "
            "WHERE is_ai_related = 1 AND is_duplicate = 0 AND sent = 0"
        ).fetchall()
        conn.close()
        plan = " ".join(str(r) for r in rows).lower()
        # SQLite should mention the index in the query plan
        assert "idx_tweets_report" in plan

    # ── get_ai_classification ─────────────────────────────────────────────

    def test_get_ai_classification_empty_ids(self, db):
        """Empty id list returns empty dict immediately."""
        assert db.get_ai_classification([]) == {}

    def test_get_ai_classification_unknown_ids(self, db):
        """IDs not in the DB are absent from the result (not classified yet)."""
        result = db.get_ai_classification(["nonexistent-id-1", "nonexistent-id-2"])
        assert result == {}

    def test_get_ai_classification_returns_correct_flags(self, db):
        """Returns the stored is_ai_related value for each known tweet."""
        session_id = db.create_session()
        ai_tweet = {
            "id": "tweet-ai-1", "text": "AI research", "author": "alice",
            "url": "https://x.com/alice/status/1", "timestamp": "2024-01-01T00:00:00Z",
            "likes": 10, "retweets": 2, "feed_type": "for_you",
        }
        non_ai_tweet = {
            "id": "tweet-noai-1", "text": "Good morning world", "author": "bob",
            "url": "https://x.com/bob/status/2", "timestamp": "2024-01-01T00:01:00Z",
            "likes": 1, "retweets": 0, "feed_type": "for_you",
        }
        db.save_tweets([ai_tweet, non_ai_tweet], session_id)
        db.mark_ai_related(["tweet-ai-1"])

        result = db.get_ai_classification(["tweet-ai-1", "tweet-noai-1", "unknown-id"])

        # Both known tweets are returned; unknown ID is absent
        assert "unknown-id" not in result
        assert result["tweet-ai-1"] == 1
        assert result["tweet-noai-1"] == 0

    def test_get_ai_classification_partial_known(self, db):
        """Only IDs present in the DB appear in the result."""
        session_id = db.create_session()
        tweet = {
            "id": "tweet-known", "text": "hello", "author": "user",
            "url": "https://x.com/user/status/99", "timestamp": "2024-01-01T00:00:00Z",
            "likes": 0, "retweets": 0, "feed_type": "for_you",
        }
        db.save_tweets([tweet], session_id)

        result = db.get_ai_classification(["tweet-known", "tweet-unknown"])
        assert "tweet-known" in result
        assert "tweet-unknown" not in result


class TestBatchMarkDuplicates:
    """Tests for the batch_mark_duplicates method."""

    def _make_tweet(self, tweet_id: str, text: str = "some text") -> dict:
        return {
            "id": tweet_id,
            "text": text,
            "author": "user",
            "url": f"https://x.com/user/status/{tweet_id}",
            "timestamp": "2024-01-01T00:00:00Z",
            "likes": 0,
            "retweets": 0,
            "feed_type": "for_you",
        }

    def test_batch_mark_duplicates_empty(self, db):
        """Empty pairs list returns 0 and is a no-op."""
        assert db.batch_mark_duplicates([]) == 0

    def test_batch_mark_duplicates_single(self, db):
        """Single pair marks exactly one tweet as duplicate."""
        session_id = db.create_session()
        db.save_tweets([self._make_tweet("orig"), self._make_tweet("dup1")], session_id)
        count = db.batch_mark_duplicates([("dup1", "orig")])
        assert count == 1
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        row = conn.execute(
            "SELECT is_duplicate, duplicate_of FROM tweets WHERE id = 'dup1'"
        ).fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1] == "orig"

    def test_batch_mark_duplicates_multiple(self, db):
        """Multiple pairs are all applied in one transaction."""
        session_id = db.create_session()
        tweets = [self._make_tweet(tid) for tid in ["orig", "dup1", "dup2", "dup3"]]
        db.save_tweets(tweets, session_id)
        pairs = [("dup1", "orig"), ("dup2", "orig"), ("dup3", "orig")]
        count = db.batch_mark_duplicates(pairs)
        assert count == 3
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        rows = conn.execute(
            "SELECT id, is_duplicate FROM tweets WHERE id IN ('dup1','dup2','dup3')"
        ).fetchall()
        conn.close()
        assert all(r[1] == 1 for r in rows)

    def test_mark_duplicate_single_delegates_to_batch(self, db):
        """mark_duplicate (legacy) still works via batch_mark_duplicates."""
        session_id = db.create_session()
        db.save_tweets([self._make_tweet("a"), self._make_tweet("b")], session_id)
        db.mark_duplicate("b", "a")
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        row = conn.execute(
            "SELECT is_duplicate, duplicate_of FROM tweets WHERE id = 'b'"
        ).fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1] == "a"


class TestEngagementRanking:
    """get_non_duplicate_ai_tweets must return rows sorted by engagement score."""

    def _make_ai_tweet(self, tweet_id, likes=0, retweets=0, timestamp="2026-03-04T10:00:00Z"):
        return {
            "id": tweet_id,
            "text": "AI tweet content",
            "author": "user",
            "url": f"https://twitter.com/user/status/{tweet_id}",
            "timestamp": timestamp,
            "likes": likes,
            "retweets": retweets,
            "feed_type": "for_you",
        }

    def test_high_engagement_first(self, db):
        """Tweet with most retweets+likes should appear first."""
        session_id = db.create_session()
        tweets = [
            self._make_ai_tweet("low", likes=1, retweets=0),   # score=1
            self._make_ai_tweet("mid", likes=10, retweets=0),  # score=10
            self._make_ai_tweet("high", likes=5, retweets=10), # score=35
        ]
        db.save_tweets(tweets, session_id)
        db.mark_ai_related(["low", "mid", "high"])

        rows = db.get_non_duplicate_ai_tweets()
        ids = [r["id"] for r in rows]
        assert ids[0] == "high", f"expected 'high' first, got {ids}"
        assert ids[1] == "mid"
        assert ids[2] == "low"

    def test_retweet_weight_higher_than_like(self, db):
        """1 retweet (weight 3) beats 2 likes (weight 2)."""
        session_id = db.create_session()
        tweets = [
            self._make_ai_tweet("likes_tweet", likes=2, retweets=0),  # score=2
            self._make_ai_tweet("rt_tweet", likes=0, retweets=1),     # score=3
        ]
        db.save_tweets(tweets, session_id)
        db.mark_ai_related(["likes_tweet", "rt_tweet"])

        rows = db.get_non_duplicate_ai_tweets()
        assert rows[0]["id"] == "rt_tweet"

    def test_tie_broken_by_timestamp(self, db):
        """Equal engagement scores are broken by timestamp descending (newest first)."""
        session_id = db.create_session()
        tweets = [
            self._make_ai_tweet("older", likes=5, retweets=0, timestamp="2026-03-04T08:00:00Z"),
            self._make_ai_tweet("newer", likes=5, retweets=0, timestamp="2026-03-04T12:00:00Z"),
        ]
        db.save_tweets(tweets, session_id)
        db.mark_ai_related(["older", "newer"])

        rows = db.get_non_duplicate_ai_tweets()
        assert rows[0]["id"] == "newer"

    def test_duplicates_and_sent_excluded(self, db):
        """Duplicate or already-sent tweets must not appear."""
        session_id = db.create_session()
        tweets = [
            self._make_ai_tweet("dup", likes=1000, retweets=500),
            self._make_ai_tweet("sent", likes=999, retweets=499),
            self._make_ai_tweet("visible", likes=1, retweets=0),
        ]
        db.save_tweets(tweets, session_id)
        db.mark_ai_related(["dup", "sent", "visible"])
        db.batch_mark_duplicates([("dup", "visible")])
        db.mark_sent(["sent"])

        rows = db.get_non_duplicate_ai_tweets()
        ids = [r["id"] for r in rows]
        assert "dup" not in ids
        assert "sent" not in ids
        assert "visible" in ids

    def test_engagement_score_field_present(self, db):
        """Returned rows include the computed engagement_score field."""
        session_id = db.create_session()
        db.save_tweets([self._make_ai_tweet("t1", likes=4, retweets=2)], session_id)
        db.mark_ai_related(["t1"])

        rows = db.get_non_duplicate_ai_tweets()
        assert len(rows) == 1
        # score = retweets*3 + likes = 6 + 4 = 10
        assert rows[0]["engagement_score"] == 10
