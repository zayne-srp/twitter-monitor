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
    def _make_eval_result(self, count=3):
        tweets = []
        for i in range(count):
            tweets.append({
                "text": f"AI tweet number {i} about GPT",
                "author": f"user_{i}",
                "time": f"2026-03-04T{10 + i:02d}:00:00Z",
                "url": f"https://x.com/user_{i}/status/{100 + i}",
            })
        return json.dumps(tweets)

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_for_you_feed(self, mock_cmd, mock_sleep):
        eval_result = self._make_eval_result(3)
        mock_cmd.side_effect = [
            "ok",           # navigate
            eval_result,    # eval
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=50)
        assert len(tweets) == 3
        assert all(t["feed_type"] == "for_you" for t in tweets)
        assert tweets[0]["id"] == "100"
        assert tweets[0]["author"] == "user_0"

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_following_feed(self, mock_cmd, mock_sleep):
        eval_result = self._make_eval_result(2)
        mock_cmd.side_effect = [
            "ok",           # navigate
            eval_result,    # eval
        ]
        crawler = TwitterCrawler()
        tweets = crawler.get_following_feed(limit=50)
        assert len(tweets) == 2
        assert all(t["feed_type"] == "following" for t in tweets)

    @patch("time.sleep")
    @patch.object(TwitterCrawler, "_run_browser_command")
    def test_get_feed_empty(self, mock_cmd, mock_sleep):
        mock_cmd.side_effect = [
            "ok",       # navigate
            "[]",       # eval returns empty array
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
        eval_result = self._make_eval_result(5)
        mock_cmd.side_effect = ["ok", eval_result]
        crawler = TwitterCrawler()
        tweets = crawler.get_for_you_feed(limit=2)
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
