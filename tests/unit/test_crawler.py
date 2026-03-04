import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.crawler.twitter_crawler import Tweet, TwitterCrawler


class TestTweetDataclass:
    def test_tweet_creation(self):
        tweet = Tweet(
            id="123456",
            text="Testing AI models",
            author="testuser",
            url="https://twitter.com/testuser/status/123456",
            timestamp="2026-03-04T10:00:00Z",
            likes=42,
            retweets=10,
            feed_type="for_you",
        )
        assert tweet.id == "123456"
        assert tweet.text == "Testing AI models"
        assert tweet.author == "testuser"
        assert tweet.feed_type == "for_you"

    def test_tweet_is_frozen(self):
        tweet = Tweet(
            id="1", text="t", author="a", url="u",
            timestamp="ts", likes=0, retweets=0, feed_type="for_you",
        )
        with pytest.raises(AttributeError):
            tweet.text = "modified"


class TestTwitterCrawlerInit:
    def test_default_port(self):
        crawler = TwitterCrawler()
        assert crawler.cdp_port == 18800

    def test_custom_port(self):
        crawler = TwitterCrawler(cdp_port=9222)
        assert crawler.cdp_port == 9222


class TestRunBrowserCommand:
    @patch("subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"result": "ok"}',
            stderr="",
            returncode=0,
        )
        crawler = TwitterCrawler()
        result = crawler._run_browser_command("navigate", "https://twitter.com")
        mock_run.assert_called_once_with(
            ["agent-browser", "--cdp", "18800", "navigate", "https://twitter.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result == {"result": "ok"}

    @patch("subprocess.run")
    def test_non_json_output(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="plain text output",
            stderr="",
            returncode=0,
        )
        crawler = TwitterCrawler()
        result = crawler._run_browser_command("snapshot")
        assert result == {"raw_output": "plain text output"}

    @patch("subprocess.run")
    def test_command_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="agent-browser", timeout=30)
        crawler = TwitterCrawler()
        with pytest.raises(RuntimeError, match="Browser command timed out"):
            crawler._run_browser_command("navigate", "https://twitter.com")

    @patch("subprocess.run")
    def test_command_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Error: connection refused",
            returncode=1,
        )
        crawler = TwitterCrawler()
        with pytest.raises(RuntimeError, match="Browser command failed"):
            crawler._run_browser_command("navigate", "https://twitter.com")


class TestGetFeeds:
    def _make_snapshot_with_tweets(self, count=3, feed_type="for_you"):
        tweets = []
        for i in range(count):
            tweets.append({
                "type": "tweet",
                "id": f"tweet_{i}",
                "text": f"AI tweet number {i} about GPT",
                "author": f"user_{i}",
                "url": f"https://twitter.com/user_{i}/status/tweet_{i}",
                "timestamp": f"2026-03-04T{10+i:02d}:00:00Z",
                "likes": i * 10,
                "retweets": i * 5,
            })
        return {"tweets": tweets}

    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_for_you_feed(self, mock_cmd):
        snapshot = self._make_snapshot_with_tweets(3, "for_you")
        mock_cmd.side_effect = [
            {"result": "ok"},   # navigate
            snapshot,           # snapshot
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50)
        assert len(tweets) == 3
        assert all(t.feed_type == "for_you" for t in tweets)

    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_following_feed(self, mock_cmd):
        snapshot = self._make_snapshot_with_tweets(2, "following")
        mock_cmd.side_effect = [
            {"result": "ok"},   # navigate
            snapshot,           # snapshot
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_following_feed(limit=50)
        assert len(tweets) == 2
        assert all(t.feed_type == "following" for t in tweets)

    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_feed_empty(self, mock_cmd):
        mock_cmd.side_effect = [
            {"result": "ok"},    # navigate
            {"tweets": []},      # empty snapshot
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50)
        assert tweets == []

    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_feed_navigation_error(self, mock_cmd):
        mock_cmd.side_effect = RuntimeError("Browser command failed")
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50)
        assert tweets == []


class TestParseTweets:
    def test_parse_valid_tweets(self):
        snapshot = {
            "tweets": [
                {
                    "id": "111",
                    "text": "Hello AI world",
                    "author": "alice",
                    "url": "https://twitter.com/alice/status/111",
                    "timestamp": "2026-03-04T10:00:00Z",
                    "likes": 5,
                    "retweets": 2,
                },
            ]
        }
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_snapshot(snapshot, "for_you")
        assert len(tweets) == 1
        assert tweets[0].id == "111"
        assert tweets[0].feed_type == "for_you"

    def test_parse_missing_fields_uses_defaults(self):
        snapshot = {
            "tweets": [
                {
                    "id": "222",
                    "text": "Partial tweet",
                },
            ]
        }
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_snapshot(snapshot, "following")
        assert len(tweets) == 1
        assert tweets[0].author == "unknown"
        assert tweets[0].likes == 0

    def test_parse_empty_snapshot(self):
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_snapshot({}, "for_you")
        assert tweets == []

    def test_parse_skips_tweets_without_id(self):
        snapshot = {
            "tweets": [
                {"text": "No ID tweet"},
                {"id": "valid", "text": "Valid tweet"},
            ]
        }
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_snapshot(snapshot, "for_you")
        assert len(tweets) == 1
        assert tweets[0].id == "valid"
