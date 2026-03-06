"""Tests for vectorised cosine similarity utilities.

Covers ``cosine_similarities_matrix`` in semantic_search and ensures
SemanticSearch.search() and SemanticDeduplicator.deduplicate() produce
the same results as the pure-Python implementation.
"""
from __future__ import annotations

import json
import math
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(v):
    """Return L2-normalised copy of v (list of floats)."""
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def _cosine_py(a, b):
    """Pure-Python cosine similarity reference implementation."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


# ---------------------------------------------------------------------------
# cosine_similarities_matrix
# ---------------------------------------------------------------------------

class TestCosineSimMatrix:
    def test_identical_vectors_score_one(self):
        from src.search.semantic_search import cosine_similarities_matrix
        v = [1.0, 0.0, 0.0]
        scores = cosine_similarities_matrix(v, [v])
        assert abs(scores[0] - 1.0) < 1e-5

    def test_orthogonal_vectors_score_zero(self):
        from src.search.semantic_search import cosine_similarities_matrix
        q = [1.0, 0.0]
        c = [[0.0, 1.0]]
        scores = cosine_similarities_matrix(q, c)
        assert abs(scores[0]) < 1e-5

    def test_opposite_vectors_score_minus_one(self):
        from src.search.semantic_search import cosine_similarities_matrix
        q = [1.0, 0.0]
        c = [[-1.0, 0.0]]
        scores = cosine_similarities_matrix(q, c)
        assert abs(scores[0] + 1.0) < 1e-5

    def test_matches_pure_python_for_random_vectors(self):
        """Matrix result must agree with the scalar fallback to 5 decimal places."""
        from src.search.semantic_search import cosine_similarities_matrix
        import random
        rng = random.Random(42)
        dim = 32
        query = [rng.gauss(0, 1) for _ in range(dim)]
        corpus = [[rng.gauss(0, 1) for _ in range(dim)] for _ in range(20)]

        matrix_scores = cosine_similarities_matrix(query, corpus)
        py_scores = [_cosine_py(query, v) for v in corpus]

        for ms, ps in zip(matrix_scores, py_scores):
            assert abs(ms - ps) < 1e-4, f"Mismatch: matrix={ms:.6f} py={ps:.6f}"

    def test_empty_corpus_returns_empty(self):
        from src.search.semantic_search import cosine_similarities_matrix
        scores = cosine_similarities_matrix([1.0, 0.0], [])
        assert scores == []

    def test_zero_query_vector_returns_zero_scores(self):
        from src.search.semantic_search import cosine_similarities_matrix
        scores = cosine_similarities_matrix([0.0, 0.0], [[1.0, 0.0], [0.0, 1.0]])
        assert all(s == pytest.approx(0.0, abs=1e-5) for s in scores)

    def test_output_length_matches_corpus(self):
        from src.search.semantic_search import cosine_similarities_matrix
        import random
        rng = random.Random(7)
        query = [rng.random() for _ in range(8)]
        corpus = [[rng.random() for _ in range(8)] for _ in range(13)]
        scores = cosine_similarities_matrix(query, corpus)
        assert len(scores) == 13

    def test_unit_vectors_dot_equals_cosine(self):
        """For unit vectors, dot product == cosine similarity."""
        from src.search.semantic_search import cosine_similarities_matrix
        q = _unit([3.0, 4.0])
        c = [_unit([1.0, 0.0]), _unit([0.0, 1.0]), _unit([1.0, 1.0])]
        scores = cosine_similarities_matrix(q, c)
        py_scores = [_cosine_py(q, v) for v in c]
        for ms, ps in zip(scores, py_scores):
            assert abs(ms - ps) < 1e-5


# ---------------------------------------------------------------------------
# SemanticDeduplicator uses vectorised path
# ---------------------------------------------------------------------------

class TestSemanticDeduplicatorVectorised:
    def _make_tweet(self, tweet_id, embedding):
        return {"id": tweet_id, "embedding": json.dumps(embedding)}

    def test_duplicate_detected(self):
        from src.search.semantic_dedup import SemanticDeduplicator
        dedup = SemanticDeduplicator(similarity_threshold=0.9)
        v = _unit([1.0, 0.0, 0.0])
        new = [self._make_tweet("new1", v)]
        existing = [self._make_tweet("old1", v)]
        result = dedup.deduplicate(new, existing)
        assert result == [("new1", "old1")]

    def test_non_duplicate_not_flagged(self):
        from src.search.semantic_dedup import SemanticDeduplicator
        dedup = SemanticDeduplicator(similarity_threshold=0.9)
        new = [self._make_tweet("new1", _unit([1.0, 0.0, 0.0]))]
        existing = [self._make_tweet("old1", _unit([0.0, 1.0, 0.0]))]
        result = dedup.deduplicate(new, existing)
        assert result == []

    def test_self_comparison_skipped(self):
        """A tweet should not be flagged as duplicate of itself."""
        from src.search.semantic_dedup import SemanticDeduplicator
        dedup = SemanticDeduplicator(similarity_threshold=0.5)
        v = _unit([1.0, 0.0])
        tweet = self._make_tweet("t1", v)
        result = dedup.deduplicate([tweet], [tweet])
        assert result == []

    def test_empty_new_tweets(self):
        from src.search.semantic_dedup import SemanticDeduplicator
        dedup = SemanticDeduplicator()
        existing = [self._make_tweet("old1", [0.1, 0.9])]
        assert dedup.deduplicate([], existing) == []

    def test_empty_existing_tweets(self):
        from src.search.semantic_dedup import SemanticDeduplicator
        dedup = SemanticDeduplicator()
        new = [self._make_tweet("new1", [0.1, 0.9])]
        assert dedup.deduplicate(new, []) == []

    def test_threshold_env_override(self, monkeypatch):
        monkeypatch.setenv("SEMANTIC_DEDUP_THRESHOLD", "0.5")
        from importlib import reload
        import src.search.semantic_dedup as mod
        reload(mod)
        dedup = mod.SemanticDeduplicator()
        assert dedup.threshold == 0.5

    def test_results_agree_with_pure_python(self):
        """Vectorised dedup must agree with scalar cosine_similarity."""
        import random
        from src.search.semantic_dedup import SemanticDeduplicator
        rng = random.Random(99)
        dim = 16
        threshold = 0.85

        def make(tid):
            v = _unit([rng.gauss(0, 1) for _ in range(dim)])
            return {"id": tid, "embedding": json.dumps(v)}

        new_tweets = [make(f"n{i}") for i in range(5)]
        existing_tweets = [make(f"e{i}") for i in range(10)]

        dedup = SemanticDeduplicator(similarity_threshold=threshold)
        vectorised = set(dedup.deduplicate(new_tweets, existing_tweets))

        # Pure-Python reference
        from src.search.semantic_search import cosine_similarity
        py_dups = set()
        for nt in new_tweets:
            new_emb = json.loads(nt["embedding"])
            for et in existing_tweets:
                if et["id"] == nt["id"]:
                    continue
                existing_emb = json.loads(et["embedding"])
                if cosine_similarity(new_emb, existing_emb) >= threshold:
                    py_dups.add((nt["id"], et["id"]))
                    break

        assert vectorised == py_dups


# ---------------------------------------------------------------------------
# SemanticSearch.search() uses vectorised path
# ---------------------------------------------------------------------------

class TestSemanticSearchVectorised:
    def _make_db(self, tweets_with_embeddings):
        db = MagicMock()
        db.get_tweets_with_embeddings.return_value = tweets_with_embeddings
        return db

    def _make_db_tweet(self, tweet_id, text, embedding):
        return {
            "id": tweet_id,
            "text": text,
            "author": "user",
            "url": f"https://x.com/user/status/{tweet_id}",
            "embedding": json.dumps(embedding),
        }

    @patch("src.search.semantic_search.OpenAI")
    def test_returns_top_k_by_similarity(self, mock_openai_cls):
        from src.search.semantic_search import SemanticSearch
        q_emb = _unit([1.0, 0.0])
        close = _unit([0.95, 0.05])   # high similarity
        far = _unit([0.0, 1.0])       # low similarity

        db = self._make_db([
            self._make_db_tweet("a", "close tweet", close),
            self._make_db_tweet("b", "far tweet", far),
        ])

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=q_emb)]
        )

        searcher = SemanticSearch(db)
        results = searcher.search("query", top_k=1)

        assert results[0]["id"] == "a"
        assert "similarity_score" in results[0]

    @patch("src.search.semantic_search.OpenAI")
    def test_empty_db_returns_empty(self, mock_openai_cls):
        from src.search.semantic_search import SemanticSearch
        db = self._make_db([])

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[1.0, 0.0])]
        )

        searcher = SemanticSearch(db)
        assert searcher.search("any") == []
