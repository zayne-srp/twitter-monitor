import json
from unittest.mock import patch, MagicMock

import pytest

from src.filter.ai_filter import AIFilter


def _make_tweet(text, tweet_id="1"):
    return {
        "id": tweet_id,
        "text": text,
        "author": "testuser",
        "url": f"https://x.com/testuser/status/{tweet_id}",
        "timestamp": "2026-03-04T10:00:00Z",
        "likes": 0,
        "retweets": 0,
        "feed_type": "for_you",
    }


class TestKeywordFallback:
    """Tests for keyword-based filtering when OPENAI_API_KEY is not set."""

    @patch.dict("os.environ", {}, clear=True)
    def test_init_without_api_key(self):
        f = AIFilter()
        assert f.use_openai is False

    @patch.dict("os.environ", {}, clear=True)
    def test_exact_keyword_match(self):
        f = AIFilter()
        assert f.is_ai_related(_make_tweet("Check out this new AI model")) is True

    @patch.dict("os.environ", {}, clear=True)
    def test_case_insensitive(self):
        f = AIFilter()
        assert f.is_ai_related(_make_tweet("gpt-4 is amazing")) is True
        assert f.is_ai_related(_make_tweet("CHATGPT rocks")) is True

    @patch.dict("os.environ", {}, clear=True)
    def test_company_names(self):
        f = AIFilter()
        assert f.is_ai_related(_make_tweet("OpenAI announces new features")) is True
        assert f.is_ai_related(_make_tweet("Anthropic raises funding")) is True

    @patch.dict("os.environ", {}, clear=True)
    def test_technical_terms(self):
        f = AIFilter()
        assert f.is_ai_related(_make_tweet("fine-tuning tips for beginners")) is True
        assert f.is_ai_related(_make_tweet("RAG pipeline architecture")) is True

    @patch.dict("os.environ", {}, clear=True)
    def test_not_ai_related(self):
        f = AIFilter()
        assert f.is_ai_related(_make_tweet("Beautiful sunset today")) is False
        assert f.is_ai_related(_make_tweet("Just had lunch")) is False

    @patch.dict("os.environ", {}, clear=True)
    def test_empty_text(self):
        f = AIFilter()
        assert f.is_ai_related(_make_tweet("")) is False

    @patch.dict("os.environ", {}, clear=True)
    def test_filter_mixed_tweets(self):
        f = AIFilter()
        tweets = [
            _make_tweet("New GPT model released", "1"),
            _make_tweet("Nice weather today", "2"),
            _make_tweet("Claude 4 is incredible", "3"),
            _make_tweet("Going to the store", "4"),
        ]
        filtered = f.filter_tweets(tweets)
        assert len(filtered) == 2
        assert filtered[0]["id"] == "1"
        assert filtered[1]["id"] == "3"

    @patch.dict("os.environ", {}, clear=True)
    def test_filter_empty_list(self):
        f = AIFilter()
        assert f.filter_tweets([]) == []


class TestOpenAIFilter:
    """Tests for OpenAI-based filtering."""

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("src.filter.ai_filter.OpenAI")
    def test_init_with_api_key(self, mock_openai_cls):
        f = AIFilter()
        assert f.use_openai is True
        mock_openai_cls.assert_called_once_with(api_key="test-key")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("src.filter.ai_filter.OpenAI")
    def test_classify_batch(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[true, false, true]"
        mock_client.chat.completions.create.return_value = mock_response

        f = AIFilter()
        tweets = [
            _make_tweet("New GPT model", "1"),
            _make_tweet("Nice weather", "2"),
            _make_tweet("LLM benchmark results", "3"),
        ]
        result = f.filter_tweets(tweets)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "3"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("src.filter.ai_filter.OpenAI")
    def test_batch_processing_over_20(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # First batch: 20 tweets, all true
        resp1 = MagicMock()
        resp1.choices = [MagicMock()]
        resp1.choices[0].message.content = json.dumps([True] * 20)

        # Second batch: 5 tweets, first 3 true
        resp2 = MagicMock()
        resp2.choices = [MagicMock()]
        resp2.choices[0].message.content = json.dumps([True, True, True, False, False])

        mock_client.chat.completions.create.side_effect = [resp1, resp2]

        f = AIFilter()
        tweets = [_make_tweet(f"Tweet {i}", str(i)) for i in range(25)]
        result = f.filter_tweets(tweets)
        assert len(result) == 23  # 20 + 3
        assert mock_client.chat.completions.create.call_count == 2

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("src.filter.ai_filter.OpenAI")
    def test_fallback_on_api_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        f = AIFilter()
        tweets = [
            _make_tweet("New GPT model released", "1"),
            _make_tweet("Nice weather today", "2"),
        ]
        result = f.filter_tweets(tweets)
        # Falls back to keyword matching: "GPT" matches
        assert len(result) == 1
        assert result[0]["id"] == "1"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("src.filter.ai_filter.OpenAI")
    def test_response_with_extra_text(self, mock_openai_cls):
        """Test that JSON array is extracted even with surrounding text."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Here are the results: [true, false]"
        mock_client.chat.completions.create.return_value = mock_response

        f = AIFilter()
        tweets = [
            _make_tweet("AI stuff", "1"),
            _make_tweet("Not AI", "2"),
        ]
        result = f.filter_tweets(tweets)
        assert len(result) == 1
        assert result[0]["id"] == "1"
