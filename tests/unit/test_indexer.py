"""Tests for TweetIndexer — batch embedding API calls."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch
import pytest


def _make_tweet(tweet_id: str, text: str) -> dict:
    return {"id": tweet_id, "text": text}


# ---------------------------------------------------------------------------
# index_tweets — batch path
# ---------------------------------------------------------------------------

@patch("src.search.tweet_indexer.OpenAI")
class TestTweetIndexerBatchPath:
    """index_tweets should use embed_texts_batch for efficiency."""

    def _make_indexer(self, mock_openai):
        mock_db = MagicMock()
        from src.search.tweet_indexer import TweetIndexer
        return TweetIndexer(mock_db), mock_db

    @patch(
        "src.search.tweet_indexer.embed_texts_batch",
        return_value=[[0.1, 0.2], [0.3, 0.4]],
    )
    def test_indexes_all_tweets_via_batch(self, mock_batch, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        tweets = [_make_tweet("1", "GPT-4 released"), _make_tweet("2", "Claude update")]
        count = indexer.index_tweets(tweets)
        assert count == 2
        mock_batch.assert_called_once()
        assert mock_db.save_embedding.call_count == 2

    @patch("src.search.tweet_indexer.embed_texts_batch", return_value=[])
    def test_index_tweets_empty_list(self, mock_batch, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        count = indexer.index_tweets([])
        assert count == 0
        mock_batch.assert_not_called()
        mock_db.save_embedding.assert_not_called()

    @patch(
        "src.search.tweet_indexer.embed_texts_batch",
        return_value=[[0.5]],
    )
    def test_skips_tweets_missing_id_or_text(self, mock_batch, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        tweets = [
            {"id": "1", "text": "valid tweet"},
            {"id": "", "text": "no id"},
            {"id": "3", "text": ""},
        ]
        count = indexer.index_tweets(tweets)
        assert count == 1
        # Only 1 valid tweet passed to batch
        args, _ = mock_batch.call_args
        assert args[0] == ["valid tweet"]

    @patch(
        "src.search.tweet_indexer.embed_texts_batch",
        return_value=[[0.1]],
    )
    def test_caller_controls_which_tweets_are_indexed(self, mock_batch, mock_openai):
        """Caller pre-filters to AI tweets; indexer indexes exactly those."""
        indexer, mock_db = self._make_indexer(mock_openai)
        ai_tweets = [_make_tweet("2", "GPT-4 is amazing")]
        count = indexer.index_tweets(ai_tweets)
        assert count == 1
        assert mock_db.save_embedding.call_count == 1

    @patch("src.search.tweet_indexer.embed_texts_batch", side_effect=Exception("API error"))
    @patch("src.search.tweet_indexer.embed_text", return_value=[0.9])
    def test_falls_back_to_per_tweet_on_batch_failure(self, mock_single, mock_batch, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        tweets = [_make_tweet("1", "GPT news"), _make_tweet("2", "LLM update")]
        count = indexer.index_tweets(tweets)
        assert count == 2
        assert mock_single.call_count == 2
        assert mock_db.save_embedding.call_count == 2


# ---------------------------------------------------------------------------
# index_missing — batch path
# ---------------------------------------------------------------------------

@patch("src.search.tweet_indexer.OpenAI")
class TestTweetIndexerIndexMissing:
    def _make_indexer(self, mock_openai):
        mock_db = MagicMock()
        from src.search.tweet_indexer import TweetIndexer
        indexer = TweetIndexer(mock_db)
        return indexer, mock_db

    @patch(
        "src.search.tweet_indexer.embed_texts_batch",
        return_value=[[0.1, 0.2], [0.3, 0.4]],
    )
    def test_index_missing_uses_batch(self, mock_batch, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        mock_db.get_tweets_missing_embeddings.return_value = [
            {"id": "a", "text": "missing one"},
            {"id": "b", "text": "missing two"},
        ]
        count = indexer.index_missing(mock_db)
        assert count == 2
        mock_batch.assert_called_once()
        assert mock_db.save_embedding.call_count == 2

    @patch("src.search.tweet_indexer.embed_texts_batch", return_value=[])
    def test_index_missing_no_rows(self, mock_batch, mock_openai):
        indexer, mock_db = self._make_indexer(mock_openai)
        mock_db.get_tweets_missing_embeddings.return_value = []
        count = indexer.index_missing(mock_db)
        assert count == 0
        mock_batch.assert_not_called()


# ---------------------------------------------------------------------------
# embed_texts_batch unit tests
# ---------------------------------------------------------------------------

class TestEmbedTextsBatch:
    """Tests for the new embed_texts_batch helper in semantic_search."""

    def _make_mock_response(self, embeddings):
        """Build a mock OpenAI embeddings response."""
        items = []
        for i, emb in enumerate(embeddings):
            item = MagicMock()
            item.embedding = emb
            item.index = i
            items.append(item)
        resp = MagicMock()
        resp.data = items
        return resp

    def test_returns_embeddings_in_order(self):
        from src.search.semantic_search import embed_texts_batch
        client = MagicMock()
        client.embeddings.create.return_value = self._make_mock_response(
            [[0.1, 0.2], [0.3, 0.4]]
        )
        result = embed_texts_batch(["hello", "world"], client=client)
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_empty_input_returns_empty(self):
        from src.search.semantic_search import embed_texts_batch
        client = MagicMock()
        result = embed_texts_batch([], client=client)
        assert result == []
        client.embeddings.create.assert_not_called()

    def test_batches_large_input(self):
        from src.search.semantic_search import embed_texts_batch
        client = MagicMock()
        # 3 texts, batch_size=2 → 2 API calls
        def side_effect(model, input):
            return self._make_mock_response([[float(i)] for i in range(len(input))])
        client.embeddings.create.side_effect = lambda **kwargs: side_effect(
            kwargs["model"], kwargs["input"]
        )
        result = embed_texts_batch(["a", "b", "c"], client=client, batch_size=2)
        assert client.embeddings.create.call_count == 2
        assert len(result) == 3

    def test_truncates_long_text(self):
        from src.search.semantic_search import embed_texts_batch
        client = MagicMock()
        client.embeddings.create.return_value = self._make_mock_response([[0.5]])
        long_text = "x" * 10000
        embed_texts_batch([long_text], client=client)
        sent = client.embeddings.create.call_args[1]["input"]
        assert all(len(t) <= 8000 for t in sent)
