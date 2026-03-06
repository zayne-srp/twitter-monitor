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


class TestClusterTopicsDeduplication:
    """Verify that cluster_topics is called at most once per pipeline run.

    Previously both generate_report() and send_as_card() each called
    cluster_topics() independently, doubling the OpenAI API spend per run.
    The fix: pass pre-computed clusters via the ``clustered`` keyword arg so
    the internal call is skipped.
    """

    def _make_tweet_dict(self, tweet_id: str, text: str, author: str = "user") -> dict:
        return {
            "id": tweet_id,
            "text": text,
            "author": author,
            "url": f"https://twitter.com/{author}/status/{tweet_id}",
            "timestamp": "2026-03-04T10:00:00Z",
            "likes": 10,
            "retweets": 5,
            "feed_type": "for_you",
        }

    def test_generate_report_uses_provided_clustered(self):
        """generate_report skips cluster_topics when clustered is provided."""
        rg = ReportGenerator()
        tweets = [self._make_tweet_dict(str(i), f"GPT tweet {i}", f"user{i}") for i in range(3)]
        precomputed = {"AI Models": tweets}

        with patch.object(rg, "cluster_topics") as mock_cluster:
            rg.generate_report(tweets, "s1", clustered=precomputed)
            mock_cluster.assert_not_called()

    def test_generate_report_calls_cluster_topics_when_none(self):
        """generate_report falls back to calling cluster_topics when clustered=None."""
        rg = ReportGenerator()
        tweets = [self._make_tweet_dict(str(i), f"GPT tweet {i}", f"user{i}") for i in range(3)]

        with patch.object(rg, "cluster_topics", return_value=None) as mock_cluster:
            rg.generate_report(tweets, "s1", clustered=None)
            mock_cluster.assert_called_once()

    @patch.dict("os.environ", {"FEISHU_WEBHOOK_URL": "https://hook.example.com"})
    @patch("src.reporter.report_generator.requests.post")
    def test_send_as_card_uses_provided_clustered(self, mock_post):
        """send_as_card skips cluster_topics when clustered is provided."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        rg = ReportGenerator()
        tweets = [self._make_tweet_dict(str(i), f"GPT tweet {i}", f"user{i}") for i in range(3)]
        precomputed = {"AI Models": tweets}

        with patch("src.reporter.feishu_card.build_card", return_value={"msg_type": "interactive", "card": {}}) as mock_build, \
             patch.object(rg, "cluster_topics") as mock_cluster:
            rg.send_as_card(tweets, "s1", "2026-03-07", clustered=precomputed)
            mock_cluster.assert_not_called()
            mock_build.assert_called_once()
            _, kwargs = mock_build.call_args
            assert kwargs.get("clustered") is precomputed

    @patch.dict("os.environ", {"FEISHU_WEBHOOK_URL": "https://hook.example.com"})
    @patch("src.reporter.report_generator.requests.post")
    def test_pipeline_calls_cluster_topics_exactly_once(self, mock_post):
        """Integration: when caller shares clusters, total API calls == 1."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        rg = ReportGenerator()
        tweets = [self._make_tweet_dict(str(i), f"GPT tweet {i}", f"user{i}") for i in range(3)]

        call_count = 0
        original_cluster = rg.cluster_topics.__func__

        def counting_cluster(self_inner, tw):
            nonlocal call_count
            call_count += 1
            return {"AI Models": tw}

        with patch.object(ReportGenerator, "cluster_topics", counting_cluster), \
             patch("src.reporter.feishu_card.build_card", return_value={"msg_type": "interactive", "card": {}}):

            # Simulate what run_send() now does: cluster once, share the result
            clustered = rg.cluster_topics(tweets[:20])
            rg.generate_report(tweets, "s1", clustered=clustered)
            rg.send_as_card(tweets, "s1", "2026-03-07", clustered=clustered)

        assert call_count == 1, f"cluster_topics called {call_count} times, expected 1"
