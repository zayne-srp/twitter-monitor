"""Unit tests for the optimised AI-filter path in run_crawl.

We test the core logic: tweets already classified in the DB are not
re-sent to the AI filter; only new (unknown) tweets are classified.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tweet(tid: str, text: str = "AI news") -> dict:
    return {
        "id": tid,
        "text": text,
        "author": "user",
        "url": f"https://x.com/user/status/{tid}",
        "timestamp": "2024-01-01T00:00:00Z",
        "likes": 5,
        "retweets": 1,
        "feed_type": "for_you",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunCrawlFilterOptimisation:
    """Validate that run_crawl skips re-classifying already-known tweets."""

    def _make_mock_db(self, known_classification: dict):
        db = MagicMock()
        db.create_session.return_value = "session-123"
        db.save_tweets.return_value = len(known_classification)
        db.get_ai_classification.return_value = known_classification
        db.mark_ai_related.return_value = None
        db.complete_session.return_value = None
        return db

    def _make_mock_crawler(self, tweets_for_you, tweets_following):
        crawler = MagicMock()
        crawler.get_for_you_feed.return_value = tweets_for_you
        crawler.get_following_feed.return_value = tweets_following
        return crawler

    def _make_mock_filter(self, ai_results):
        """filter_tweets returns ai_results (simulates OpenAI response)."""
        ai_filter = MagicMock()
        ai_filter.filter_tweets.return_value = ai_results
        return ai_filter

    def test_new_tweets_are_classified(self):
        """Tweets not in DB must be passed to filter_tweets."""
        new_tweet = _make_tweet("new-1")
        known_classification = {}  # nothing known yet

        with (
            patch("src.main.TwitterCrawler", return_value=self._make_mock_crawler([new_tweet], [])),
            patch("src.main.AIFilter", return_value=self._make_mock_filter([new_tweet])),
            patch("src.main.TweetDatabase", return_value=self._make_mock_db(known_classification)),
        ):
            from src.main import run_crawl
            session_id, _ = run_crawl(10)

        # filter_tweets should have been called with the new tweet
        from src.main import AIFilter as AF
        # We verify via the mock returned by the patch
        # (patch replaces the class, so the instance is captured inside run_crawl)

    def test_already_classified_tweets_skipped(self):
        """Tweets already in DB must NOT be passed to filter_tweets."""
        old_tweet = _make_tweet("old-1")
        # DB already knows about old-1 and it IS ai-related
        known_classification = {"old-1": 1}

        filter_mock = self._make_mock_filter([])  # should be called with empty list

        with (
            patch("src.main.TwitterCrawler", return_value=self._make_mock_crawler([old_tweet], [])),
            patch("src.main.AIFilter", return_value=filter_mock),
            patch("src.main.TweetDatabase", return_value=self._make_mock_db(known_classification)),
        ):
            from src.main import run_crawl
            run_crawl(10)

        # filter_tweets should have been called with an empty list (no new tweets)
        call_args = filter_mock.filter_tweets.call_args
        assert call_args is not None
        called_with = call_args[0][0]
        assert called_with == [], (
            f"Expected empty list but got {called_with!r}; "
            "already-classified tweets should not be re-filtered"
        )

    def test_known_ai_tweets_included_in_result(self):
        """Tweets already flagged is_ai_related=1 in DB must end up in ai_tweets."""
        old_ai_tweet = _make_tweet("old-ai-1")
        known_classification = {"old-ai-1": 1}  # already AI-related

        filter_mock = self._make_mock_filter([])  # no new tweets to classify

        db_mock = self._make_mock_db(known_classification)
        db_mock.mark_ai_related = MagicMock()

        with (
            patch("src.main.TwitterCrawler", return_value=self._make_mock_crawler([old_ai_tweet], [])),
            patch("src.main.AIFilter", return_value=filter_mock),
            patch("src.main.TweetDatabase", return_value=db_mock),
        ):
            from src.main import run_crawl
            run_crawl(10)

        # mark_ai_related should have been called including old-ai-1
        db_mock.mark_ai_related.assert_called_once()
        ids_marked = db_mock.mark_ai_related.call_args[0][0]
        assert "old-ai-1" in ids_marked

    def test_mixed_new_and_known_tweets(self):
        """Only new tweets go to filter; known AI tweets still appear in ai_tweets."""
        new_tweet = _make_tweet("new-1")
        old_ai_tweet = _make_tweet("old-ai-1")
        old_nonai_tweet = _make_tweet("old-nonai-1", text="good morning")

        known_classification = {"old-ai-1": 1, "old-nonai-1": 0}
        filter_mock = self._make_mock_filter([new_tweet])  # new tweet is AI-related

        db_mock = self._make_mock_db(known_classification)
        db_mock.mark_ai_related = MagicMock()

        all_tweets = [new_tweet, old_ai_tweet, old_nonai_tweet]
        with (
            patch("src.main.TwitterCrawler", return_value=self._make_mock_crawler(all_tweets, [])),
            patch("src.main.AIFilter", return_value=filter_mock),
            patch("src.main.TweetDatabase", return_value=db_mock),
        ):
            from src.main import run_crawl
            run_crawl(10)

        # filter_tweets called only with the new (unknown) tweet
        called_with = filter_mock.filter_tweets.call_args[0][0]
        assert len(called_with) == 1
        assert called_with[0]["id"] == "new-1"

        # mark_ai_related called with new-1 + old-ai-1 (but NOT old-nonai-1)
        ids_marked = db_mock.mark_ai_related.call_args[0][0]
        assert "new-1" in ids_marked
        assert "old-ai-1" in ids_marked
        assert "old-nonai-1" not in ids_marked
