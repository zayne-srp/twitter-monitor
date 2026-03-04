"""
End-to-end tests for Twitter AI Monitor.

These tests require:
- A running Chrome/Chromium browser with CDP enabled on port 18800
- agent-browser CLI installed and accessible
- A valid Twitter account configured in .env
- Network access to twitter.com

Run with: python -m pytest tests/e2e/ -v -m e2e
"""

import os

import pytest

from src.crawler.twitter_crawler import TwitterCrawler
from src.filter.ai_filter import AIFilter
from src.reporter.report_generator import ReportGenerator
from src.storage.db import TweetDatabase

# Mark all tests in this module as e2e (skip in CI by default)
pytestmark = pytest.mark.e2e


@pytest.fixture
def twitter_credentials():
    username = os.getenv("TWITTER_USERNAME")
    password = os.getenv("TWITTER_PASSWORD")
    if not username or not password:
        pytest.skip("TWITTER_USERNAME and TWITTER_PASSWORD not set")
    return username, password


@pytest.fixture
def crawler():
    cdp_port = int(os.getenv("CDP_PORT", "18800"))
    return TwitterCrawler(cdp_port=cdp_port)


@pytest.fixture
def db(tmp_path):
    return TweetDatabase(str(tmp_path / "e2e_test.db"))


class TestFullPipeline:
    """Tests the complete crawl -> filter -> store -> report pipeline."""

    def test_login(self, crawler, twitter_credentials):
        username, password = twitter_credentials
        result = crawler.login(username, password)
        assert result is True, "Login should succeed with valid credentials"

    def test_crawl_for_you_feed(self, crawler, twitter_credentials):
        username, password = twitter_credentials
        crawler.login(username, password)

        tweets = crawler.get_for_you_feed(limit=10)
        assert len(tweets) > 0, "For You feed should return tweets"
        assert all(t.feed_type == "for_you" for t in tweets)
        assert all(t.id for t in tweets), "All tweets should have IDs"

    def test_crawl_following_feed(self, crawler, twitter_credentials):
        username, password = twitter_credentials
        crawler.login(username, password)

        tweets = crawler.get_following_feed(limit=10)
        assert len(tweets) > 0, "Following feed should return tweets"
        assert all(t.feed_type == "following" for t in tweets)

    def test_filter_crawled_tweets(self, crawler, twitter_credentials):
        username, password = twitter_credentials
        crawler.login(username, password)

        tweets = crawler.get_for_you_feed(limit=20)
        ai_filter = AIFilter()
        filtered = ai_filter.filter_tweets(tweets)

        # We can't guarantee AI tweets exist, but the filter should work
        assert len(filtered) <= len(tweets)
        assert all(ai_filter.is_ai_related(t) for t in filtered)

    def test_store_and_dedup(self, crawler, twitter_credentials, db):
        username, password = twitter_credentials
        crawler.login(username, password)

        tweets = crawler.get_for_you_feed(limit=5)
        if not tweets:
            pytest.skip("No tweets returned from feed")

        session_id = db.create_session()
        first_save = db.save_tweets(tweets, session_id)
        second_save = db.save_tweets(tweets, session_id)

        assert first_save == len(tweets), "First save should insert all tweets"
        assert second_save == 0, "Second save should insert zero (all dupes)"

    def test_generate_report(self, crawler, twitter_credentials, db, tmp_path):
        username, password = twitter_credentials
        crawler.login(username, password)

        tweets = crawler.get_for_you_feed(limit=10)
        ai_filter = AIFilter()
        filtered = ai_filter.filter_tweets(tweets)

        session_id = db.create_session()
        db.save_tweets(filtered, session_id)

        reporter = ReportGenerator()
        report = reporter.generate_report(filtered, session_id)
        filepath = reporter.save_report(report, str(tmp_path))

        assert os.path.exists(filepath)
        assert "Twitter AI Monitor Report" in report
        db.complete_session(session_id, len(tweets), len(filtered))


class TestErrorRecovery:
    """Tests error handling in real-world scenarios."""

    def test_invalid_credentials(self, crawler):
        result = crawler.login("invalid_user_xyz_123", "wrong_password")
        # May return True or False depending on Twitter's response
        # The important thing is it doesn't crash
        assert isinstance(result, bool)

    def test_crawler_without_browser(self):
        """Test behavior when no browser is running on CDP port."""
        crawler = TwitterCrawler(cdp_port=19999)  # Unused port
        tweets = crawler.get_for_you_feed(limit=5)
        assert tweets == [], "Should return empty list when browser unavailable"
