import os

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


class TestSaveReport:
    def test_save_creates_file(self, tmp_path):
        rg = ReportGenerator()
        content = "# Test Report\nSome content"
        filepath = rg.save_report(content, str(tmp_path))
        assert os.path.exists(filepath)
        assert filepath.endswith(".md")
        with open(filepath) as f:
            assert f.read() == content
