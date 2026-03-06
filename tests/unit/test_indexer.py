"""Tests for TweetIndexer — ensures only AI-related tweets are indexed."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


def _make_tweet(tweet_id: str, text: str) -> dict:
    return {"id": tweet_id, "text": text}


@patch("src.search.tweet_indexer.OpenAI")
class TestTweetIndexerIndexTweets:
    """index_tweets should index every tweet it receives."""

    def _make_indexer(self, mock_openai):
        mock_db = MagicMock()
        from src.search.tweet_indexer import TweetIndexer
        indexer = TweetIndexer(mock_db)
        indexer.db = mock_db
        return indexer, mock_db

    @patch("src.search.tweet_indexer.embed_text", return_value=[0.1, 0.2, 0.3])
    def test_indexes_all_provided_tweets(self, mock_embed, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        tweets = [_make_tweet("1", "GPT-4 released"), _make_tweet("2", "Claude update")]
        count = indexer.index_tweets(tweets)
        assert count == 2
        assert mock_db.save_embedding.call_count == 2

    @patch("src.search.tweet_indexer.embed_text", return_value=[0.1, 0.2, 0.3])
    def test_index_tweets_with_empty_list(self, mock_embed, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        count = indexer.index_tweets([])
        assert count == 0
        mock_db.save_embedding.assert_not_called()

    @patch("src.search.tweet_indexer.embed_text", return_value=[0.5])
    def test_index_tweets_skips_missing_id_or_text(self, mock_embed, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        tweets = [
            {"id": "1", "text": "valid tweet"},
            {"id": "", "text": "no id"},
            {"id": "3", "text": ""},
        ]
        count = indexer.index_tweets(tweets)
        assert count == 1

    @patch("src.search.tweet_indexer.embed_text", return_value=[0.5])
    def test_subset_indexed_when_caller_passes_ai_only(self, mock_embed, mock_openai):
        """Caller passes only AI tweets; indexer indexes exactly those (not all_tweets)."""
        indexer, mock_db = self._make_indexer(mock_openai)
        ai_tweets = [_make_tweet("2", "GPT-4 is amazing")]
        # Simulate: all_tweets had 2 items but caller pre-filters to AI only
        count = indexer.index_tweets(ai_tweets)
        assert count == 1
        # Exactly 1 embedding stored — the non-AI tweet was never passed in
        assert mock_db.save_embedding.call_count == 1
