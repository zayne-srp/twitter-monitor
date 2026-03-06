"""Tests for engagement metric extraction (likes/retweets) in TwitterCrawler."""
import json
from unittest.mock import patch, MagicMock

import pytest

from src.crawler.twitter_crawler import TwitterCrawler, EVAL_JS, THREAD_EVAL_JS


class TestEngagementExtraction:
    """Verify that likes and retweets are correctly parsed from eval results."""

    def test_parse_likes_and_retweets(self):
        """Parse numeric likes and retweets from eval data."""
        data = [
            {
                "text": "Great AI model released today",
                "author": "ml_researcher",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/ml_researcher/status/1001",
                "likes": 1234,
                "retweets": 567,
            }
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert len(tweets) == 1
        assert tweets[0]["likes"] == 1234
        assert tweets[0]["retweets"] == 567

    def test_parse_zero_engagement(self):
        """Tweets with no engagement data should default to 0."""
        data = [
            {
                "text": "New AI paper out",
                "author": "researcher",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/researcher/status/1002",
            }
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert tweets[0]["likes"] == 0
        assert tweets[0]["retweets"] == 0

    def test_parse_explicit_zero_engagement(self):
        """Tweets with explicit zero engagement values are handled correctly."""
        data = [
            {
                "text": "Unpopular AI take",
                "author": "contrarian",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/contrarian/status/1003",
                "likes": 0,
                "retweets": 0,
            }
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert tweets[0]["likes"] == 0
        assert tweets[0]["retweets"] == 0

    def test_parse_high_engagement(self):
        """Large engagement numbers are passed through correctly."""
        data = [
            {
                "text": "Viral AI announcement",
                "author": "ai_lab",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/ai_lab/status/1004",
                "likes": 50000,
                "retweets": 12000,
            }
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "for_you")
        assert tweets[0]["likes"] == 50000
        assert tweets[0]["retweets"] == 12000

    def test_parse_multiple_tweets_engagement(self):
        """Engagement data for multiple tweets is preserved independently."""
        data = [
            {
                "text": "Tweet A",
                "author": "userA",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/userA/status/2001",
                "likes": 100,
                "retweets": 20,
            },
            {
                "text": "Tweet B",
                "author": "userB",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/userB/status/2002",
                "likes": 999,
                "retweets": 333,
            },
            {
                "text": "Tweet C no engagement",
                "author": "userC",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/userC/status/2003",
            },
        ]
        crawler = TwitterCrawler()
        tweets = crawler._parse_tweets_from_eval(json.dumps(data), "following")
        assert len(tweets) == 3
        assert tweets[0]["likes"] == 100
        assert tweets[0]["retweets"] == 20
        assert tweets[1]["likes"] == 999
        assert tweets[1]["retweets"] == 333
        assert tweets[2]["likes"] == 0
        assert tweets[2]["retweets"] == 0

    def test_engagement_preserved_in_feed_collection(self):
        """Engagement metrics flow end-to-end through get_for_you_feed."""
        data = [
            {
                "text": "GPT-5 released with groundbreaking capabilities",
                "author": "openai",
                "time": "2026-03-07T04:00:00Z",
                "url": "https://x.com/openai/status/9999",
                "likes": 25000,
                "retweets": 8000,
            }
        ]
        eval_result = json.dumps(data)

        with patch("time.sleep"), \
             patch.object(TwitterCrawler, "_run_browser_command") as mock_cmd:
            mock_cmd.side_effect = [
                "ok",         # navigate
                "1",          # login check: tweet count > 0 → break
                eval_result,  # feed eval (1 tweet, limit=1 → stop_reason="limit")
            ]
            crawler = TwitterCrawler()
            tweets = crawler.get_for_you_feed(limit=1)

        assert len(tweets) == 1
        assert tweets[0]["likes"] == 25000
        assert tweets[0]["retweets"] == 8000

    def test_eval_js_contains_engagement_selectors(self):
        """EVAL_JS must include data-testid selectors for like and retweet counts."""
        assert 'data-testid="like"' in EVAL_JS
        assert 'data-testid="retweet"' in EVAL_JS
        assert "parseCount" in EVAL_JS

    def test_thread_eval_js_contains_engagement_selectors(self):
        """THREAD_EVAL_JS must also include engagement selectors."""
        assert 'data-testid="like"' in THREAD_EVAL_JS
        assert 'data-testid="retweet"' in THREAD_EVAL_JS
        assert "parseCount" in THREAD_EVAL_JS

    def test_eval_js_handles_k_suffix(self):
        """EVAL_JS parseCount logic handles '12K' → 12000."""
        # Verify the JS source contains K/M handling logic
        assert ".endsWith('K')" in EVAL_JS or "endsWith('K')" in EVAL_JS
        assert ".endsWith('M')" in EVAL_JS or "endsWith('M')" in EVAL_JS
