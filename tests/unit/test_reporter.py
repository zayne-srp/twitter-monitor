import os
from unittest.mock import patch, MagicMock

import pytest

from src.crawler.twitter_crawler import Tweet
from src.reporter.report_generator import ReportGenerator


def _make_tweet(tweet_id: str, text: str, author: str = "user") -> Tweet:
    return Tweet(
        id=tweet_id,
        text=text,
        author=author,
        url=f"https://twitter.com/{author}/status/{tweet_id}",
        timestamp="2026-03-04T10:00:00Z",
        likes=10,
        retweets=5,
        feed_type="for_you",
    )


class TestCategorizeTweet:
    def test_models_category(self):
        rg = ReportGenerator()
        tweet = _make_tweet("1", "GPT-5 is coming soon with new capabilities")
        assert rg.categorize_tweet(tweet) == "Models & Research"

    def test_tools_category(self):
        rg = ReportGenerator()
        tweet = _make_tweet("1", "Try Midjourney v6 for better images")
        assert rg.categorize_tweet(tweet) == "Tools & Products"

    def test_technical_category(self):
        rg = ReportGenerator()
        tweet = _make_tweet("1", "Here's a fine-tuning tutorial for beginners")
        assert rg.categorize_tweet(tweet) == "Tutorials & Technical"

    def test_default_category(self):
        rg = ReportGenerator()
        tweet = _make_tweet("1", "AI will change the world soon")
        assert rg.categorize_tweet(tweet) == "Opinion & Discussion"


class TestGenerateReport:
    def test_generates_markdown(self):
        rg = ReportGenerator()
        tweets = [
            _make_tweet("1", "GPT-5 released today", "openai"),
            _make_tweet("2", "New RAG tutorial for beginners", "techguy"),
            _make_tweet("3", "AI will transform education", "thinker"),
        ]
        report = rg.generate_report(tweets, "session-123")
        assert "# Twitter AI Monitor Report" in report
        assert "session-123" in report
        assert "GPT-5 released today" in report

    def test_empty_tweets(self):
        rg = ReportGenerator()
        report = rg.generate_report([], "session-empty")
        assert "No AI-related tweets" in report


class TestReportLengthLimits:
    def test_report_limits_to_20_tweets(self):
        rg = ReportGenerator()
        tweets = [
            _make_tweet(str(i), f"GPT model tweet {i}", f"user{i}")
            for i in range(25)
        ]
        report = rg.generate_report(tweets, "session-limit")
        assert "**Total AI Tweets**: 25" in report
        assert "（还有 5 条，已省略）" in report
        # Only 20 tweets should appear in the body
        assert f"GPT model tweet 19" in report
        assert f"GPT model tweet 20" not in report

    def test_report_no_omission_under_20(self):
        rg = ReportGenerator()
        tweets = [
            _make_tweet(str(i), f"GPT model tweet {i}", f"user{i}")
            for i in range(15)
        ]
        report = rg.generate_report(tweets, "session-ok")
        assert "已省略" not in report


class TestSendReportTruncation:
    @patch.dict("os.environ", {"FEISHU_WEBHOOK_URL": "https://hook.example.com"})
    @patch("src.reporter.report_generator.requests.post")
    def test_truncates_long_content(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        rg = ReportGenerator()
        long_content = "x" * 5000
        rg.send_report(long_content)

        sent_text = mock_post.call_args[1]["json"]["content"]["text"]
        assert len(sent_text) <= 3800 + len("...（内容过长已截断）")
        assert sent_text.endswith("...（内容过长已截断）")

    @patch.dict("os.environ", {"FEISHU_WEBHOOK_URL": "https://hook.example.com"})
    @patch("src.reporter.report_generator.requests.post")
    def test_does_not_truncate_short_content(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        rg = ReportGenerator()
        short_content = "x" * 100
        rg.send_report(short_content)

        sent_text = mock_post.call_args[1]["json"]["content"]["text"]
        assert sent_text == short_content


class TestSaveReport:
    def test_save_creates_file(self, tmp_path):
        rg = ReportGenerator()
        content = "# Test Report\nSome content"
        filepath = rg.save_report(content, str(tmp_path))
        assert os.path.exists(filepath)
        assert filepath.endswith(".md")
        with open(filepath) as f:
            assert f.read() == content
