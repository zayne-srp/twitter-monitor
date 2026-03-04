import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.crawler.twitter_crawler import TwitterCrawler


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
        assert result == '{"result": "ok"}'

    @patch("subprocess.run")
    def test_returns_raw_stdout(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="plain text output",
            stderr="",
            returncode=0,
        )
        crawler = TwitterCrawler()
        result = crawler._run_browser_command("snapshot")
        assert result == "plain text output"

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
    def _make_eval_result(self, count=3, start_id=100):
        tweets = []
        for i in range(count):
            tweets.append({
                "text": f"AI tweet number {i} about GPT",
                "author": f"user_{i}",
                "time": f"2026-03-04T{10 + i:02d}:00:00Z",
                "url": f"https://x.com/user_{i}/status/{start_id + i}",
            })
        return json.dumps(tweets)

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_for_you_feed(self, mock_cmd, mock_sleep):
        """With limit=3 and 3 tweets, stops after first eval (limit reached)."""
        eval_result = self._make_eval_result(3)
        mock_cmd.side_effect = [
            "ok",           # navigate
            "5",            # login check: tweet count
            eval_result,    # eval (3 tweets → limit reached)
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=3)
        assert len(tweets) == 3
        assert all(t["feed_type"] == "for_you" for t in tweets)
        assert tweets[0]["id"] == "100"
        assert tweets[0]["author"] == "user_0"

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_following_feed(self, mock_cmd, mock_sleep):
        """With limit=2 and 2 tweets, stops after first eval (limit reached)."""
        eval_result = self._make_eval_result(2)
        mock_cmd.side_effect = [
            "ok",           # navigate
            "5",            # login check: tweet count
            eval_result,    # eval (2 tweets → limit reached)
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_following_feed(limit=2)
        assert len(tweets) == 2
        assert all(t["feed_type"] == "following" for t in tweets)

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_feed_empty(self, mock_cmd, mock_sleep):
        """Empty eval results trigger no_new_content stop after 3 consecutive rounds."""
        mock_cmd.side_effect = [
            "ok",       # navigate
            "5",        # login check: tweet count
            "[]",       # eval round 1 (no new → consecutive=1)
            "true",     # scroll
            "[]",       # eval round 2 (no new → consecutive=2)
            "true",     # scroll
            "[]",       # eval round 3 (no new → consecutive=3 → stop)
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

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_feed_respects_limit(self, mock_cmd, mock_sleep):
        """5 tweets returned but limit=2 → returns only 2."""
        eval_result = self._make_eval_result(5)
        mock_cmd.side_effect = ["ok", "5", eval_result]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=2)
        assert len(tweets) == 2

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_scroll_pagination_multiple_pages(self, mock_cmd, mock_sleep):
        """Fetches across multiple scroll pages until limit is reached."""
        page1 = self._make_eval_result(2, start_id=100)
        page2 = self._make_eval_result(2, start_id=200)
        mock_cmd.side_effect = [
            "ok",       # navigate
            "5",        # login check: tweet count
            page1,      # eval page 1 (2 tweets, limit=4 not reached)
            "true",     # scroll
            page2,      # eval page 2 (2 more tweets, total=4 → limit reached)
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=4)
        assert len(tweets) == 4
        assert tweets[0]["id"] == "100"
        assert tweets[2]["id"] == "200"

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_max_tweets_stop(self, mock_cmd, mock_sleep):
        """Stops when max_tweets is reached."""
        eval_result = self._make_eval_result(5)
        mock_cmd.side_effect = ["ok", "5", eval_result]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50, max_tweets=3)
        assert len(tweets) == 3

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_duplicate_window_stop(self, mock_cmd, mock_sleep):
        """Stops when sliding window detects 8/10 duplicates."""
        # Create a mock db with existing IDs
        mock_db = MagicMock()
        mock_db.get_all_tweet_ids.return_value = {str(i) for i in range(100, 120)}
        mock_db.get_last_crawl_start.return_value = None

        # All 10 tweets have IDs in the existing set → window fills with 10 dups
        tweets_data = []
        for i in range(10):
            tweets_data.append({
                "text": f"Tweet {i}",
                "author": f"user_{i}",
                "time": "2026-03-04T10:00:00Z",
                "url": f"https://x.com/user_{i}/status/{100 + i}",
            })
        eval_result = json.dumps(tweets_data)
        mock_cmd.side_effect = ["ok", "5", eval_result]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50, db=mock_db)
        # Should stop at 10 tweets due to duplicate_window (10/10 >= 8)
        assert len(tweets) == 10

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_timestamp_early_stop(self, mock_cmd, mock_sleep):
        """Stops when tweet timestamp is older than last crawl start."""
        mock_db = MagicMock()
        mock_db.get_all_tweet_ids.return_value = set()
        mock_db.get_last_crawl_start.return_value = "2026-03-04T12:00:00Z"

        tweets_data = [
            {
                "text": "New tweet",
                "author": "user_a",
                "time": "2026-03-04T13:00:00Z",
                "url": "https://x.com/user_a/status/200",
            },
            {
                "text": "Old tweet",
                "author": "user_b",
                "time": "2026-03-04T11:00:00Z",  # Before last_crawl_start
                "url": "https://x.com/user_b/status/201",
            },
        ]
        eval_result = json.dumps(tweets_data)
        mock_cmd.side_effect = ["ok", "5", eval_result]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50, db=mock_db)
        # Stops at tweet 2 due to timestamp, both tweets are collected
        assert len(tweets) == 2


class TestParseTweetsFromEval:
    def test_parse_valid_eval_result(self):
        data = [
            {
                "text": "Hello AI world",
                "author": "alice",
                "time": "2026-03-04T10:00:00Z",
                "url": "https://x.com/alice/status/111",
            },
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert len(tweets) == 1
        assert tweets[0]["id"] == "111"
        assert tweets[0]["text"] == "Hello AI world"
        assert tweets[0]["author"] == "alice"
        assert tweets[0]["feed_type"] == "for_you"
        assert tweets[0]["likes"] == 0
        assert tweets[0]["retweets"] == 0

    def test_parse_double_encoded_json(self):
        data = [
            {
                "text": "Double encoded tweet",
                "author": "bob",
                "time": "2026-03-04T10:00:00Z",
                "url": "https://x.com/bob/status/222",
            },
        ]
        # Double-encode: JSON string within a JSON string
        double_encoded = json.dumps(json.dumps(data))
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(double_encoded, "following")
        assert len(tweets) == 1
        assert tweets[0]["id"] == "222"

    def test_parse_skips_empty_url(self):
        data = [
            {"text": "No URL tweet", "author": "a", "time": "", "url": ""},
            {"text": "Valid", "author": "b", "time": "", "url": "https://x.com/b/status/333"},
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert len(tweets) == 1
        assert tweets[0]["id"] == "333"

    def test_parse_skips_empty_text(self):
        data = [
            {"text": "", "author": "a", "time": "", "url": "https://x.com/a/status/444"},
            {"text": "Has text", "author": "b", "time": "", "url": "https://x.com/b/status/555"},
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert len(tweets) == 1
        assert tweets[0]["id"] == "555"

    def test_parse_empty_array(self):
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval("[]", "for_you")
        assert tweets == []

    def test_parse_extracts_id_from_url(self):
        data = [
            {
                "text": "Test",
                "author": "user",
                "time": "",
                "url": "https://x.com/user/status/987654321",
            },
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert tweets[0]["id"] == "987654321"
