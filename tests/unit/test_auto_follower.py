"""Unit tests for AutoFollower — focusing on pre-fetch optimisation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.follower.auto_follower import AutoFollower


def _make_tweet(author: str, handle: str, text: str = "AI stuff") -> dict:
    return {
        "author": author,
        "text": text,
        "url": f"https://x.com/{handle}/status/123456",
    }


class FakeDB:
    def __init__(self, followed: set | None = None):
        self._followed = set(followed or [])
        self.saved: list[str] = []

    def get_followed_accounts(self) -> set:
        return set(self._followed)

    def save_followed_account(self, handle: str, verified: bool = False) -> None:
        self.saved.append(handle)


# ---------------------------------------------------------------------------
# _extract_handle
# ---------------------------------------------------------------------------

class TestExtractHandle:
    def test_extracts_from_x_url(self):
        tweet = {"url": "https://x.com/elonmusk/status/999", "author": "Elon"}
        assert AutoFollower._extract_handle(tweet) == "elonmusk"

    def test_extracts_from_twitter_url(self):
        tweet = {"url": "https://twitter.com/openai/status/1", "author": "OpenAI"}
        assert AutoFollower._extract_handle(tweet) == "openai"

    def test_falls_back_to_author(self):
        tweet = {"url": "https://example.com/foo", "author": "@zayne"}
        assert AutoFollower._extract_handle(tweet) == "zayne"

    def test_empty_url_uses_author(self):
        tweet = {"url": "", "author": "alice"}
        assert AutoFollower._extract_handle(tweet) == "alice"


# ---------------------------------------------------------------------------
# run() pre-filter behaviour
# ---------------------------------------------------------------------------

class TestRunPrefetchOptimisation:
    def _make_follower(self) -> AutoFollower:
        follower = AutoFollower.__new__(AutoFollower)
        follower.cdp_port = 18800
        # We'll mock evaluate_authors / follow_author per test
        return follower

    def test_already_followed_authors_excluded_from_scoring(self):
        """evaluate_authors must NOT be called with tweets from followed authors."""
        follower = self._make_follower()

        tweets = [
            _make_tweet("Alice", "alice", "GPT-5 is amazing"),
            _make_tweet("Bob", "bob", "New Claude model"),  # already followed
        ]
        db = FakeDB(followed={"bob"})

        captured_tweets: list = []

        def fake_evaluate(t):
            captured_tweets.extend(t)
            return {"alice": 8.0}

        follower.evaluate_authors = fake_evaluate  # type: ignore[assignment]
        follower.follow_author = MagicMock(return_value=True)

        follower.run(tweets, db)

        # Only Alice's tweet should reach evaluate_authors
        authors_scored = {tw["author"] for tw in captured_tweets}
        assert "Bob" not in authors_scored
        assert "Alice" in authors_scored

    def test_all_followed_skips_openai_entirely(self):
        """When every author is already followed, evaluate_authors is never called."""
        follower = self._make_follower()

        tweets = [
            _make_tweet("Alice", "alice"),
            _make_tweet("Bob", "bob"),
        ]
        db = FakeDB(followed={"alice", "bob"})

        follower.evaluate_authors = MagicMock(return_value={})

        result = follower.run(tweets, db)

        follower.evaluate_authors.assert_not_called()
        assert result == []

    def test_no_tweets_returns_empty(self):
        follower = self._make_follower()
        db = FakeDB()
        follower.evaluate_authors = MagicMock(return_value={})
        assert follower.run([], db) == []
        follower.evaluate_authors.assert_not_called()

    def test_high_score_new_author_gets_followed(self):
        follower = self._make_follower()

        tweets = [_make_tweet("Charlie", "charlie", "LLM research breakthrough")]
        db = FakeDB()

        follower.evaluate_authors = MagicMock(return_value={"charlie": 9.0})
        follower.follow_author = MagicMock(return_value=True)

        result = follower.run(tweets, db)

        follower.follow_author.assert_called_once_with("charlie")
        assert result == ["charlie"]
        assert "charlie" in db.saved

    def test_low_score_author_not_followed(self):
        follower = self._make_follower()

        tweets = [_make_tweet("Dave", "dave", "Boring content")]
        db = FakeDB()

        follower.evaluate_authors = MagicMock(return_value={"dave": 3.5})
        follower.follow_author = MagicMock(return_value=True)

        result = follower.run(tweets, db)

        follower.follow_author.assert_not_called()
        assert result == []

    def test_follow_failure_not_saved(self):
        follower = self._make_follower()

        tweets = [_make_tweet("Eve", "eve", "Great AI content")]
        db = FakeDB()

        follower.evaluate_authors = MagicMock(return_value={"eve": 8.5})
        follower.follow_author = MagicMock(return_value=False)

        result = follower.run(tweets, db)

        assert result == []
        assert "eve" not in db.saved

    def test_mixed_followed_and_new_only_scores_new(self):
        """With 3 authors, 1 followed → only 2 scored, 1 gets followed."""
        follower = self._make_follower()

        tweets = [
            _make_tweet("Alice", "alice", "Tweet 1"),   # already followed
            _make_tweet("Bob", "bob", "Tweet 2"),       # new, score 8
            _make_tweet("Carol", "carol", "Tweet 3"),   # new, score 4
        ]
        db = FakeDB(followed={"alice"})

        scored_authors: list[str] = []

        def fake_evaluate(t):
            scored_authors.extend(tw["author"] for tw in t)
            return {"bob": 8.0, "carol": 4.0}

        follower.evaluate_authors = fake_evaluate  # type: ignore[assignment]
        follower.follow_author = MagicMock(return_value=True)

        result = follower.run(tweets, db)

        assert "Alice" not in scored_authors
        assert "Bob" in scored_authors
        assert "Carol" in scored_authors
        assert result == ["bob"]
