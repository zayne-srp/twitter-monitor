import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.storage.db import TweetDatabase


def _setup_db_with_missing_embedding(context):
    db_path = tempfile.mktemp(suffix=".db")
    context.db = TweetDatabase(db_path=db_path)
    context.db_path = db_path
    session_id = context.db.create_session()
    tweet = {
        "id": "tweet_missing_emb",
        "text": "AI model training techniques",
        "author": "testuser",
        "url": "https://x.com/testuser/status/tweet_missing_emb",
        "timestamp": "2025-01-01T00:00:00Z",
        "likes": 0,
        "retweets": 0,
        "feed_type": "for_you",
    }
    context.db.save_tweet(tweet, session_id)
    context.db.mark_ai_related(["tweet_missing_emb"])


@given('数据库中有 is_ai_related=1 且 embedding 为 NULL 的推文')
def step_db_has_tweet_missing_embedding(context):
    _setup_db_with_missing_embedding(context)


@when('调用 index_missing')
def step_call_index_missing(context):
    from src.search.tweet_indexer import TweetIndexer

    mock_client = MagicMock()

    if getattr(context, 'api_always_fails', False):
        with patch("src.search.tweet_indexer.embed_text", side_effect=Exception("API error")):
            with patch("src.search.tweet_indexer.time.sleep"):
                indexer = TweetIndexer.__new__(TweetIndexer)
                indexer.db = context.db
                indexer.client = mock_client
                context.result_count = indexer.index_missing(context.db)
    else:
        fake_embedding = [0.1] * 10
        with patch("src.search.tweet_indexer.embed_text", return_value=fake_embedding):
            indexer = TweetIndexer.__new__(TweetIndexer)
            indexer.db = context.db
            indexer.client = mock_client
            context.result_count = indexer.index_missing(context.db)


@then('该推文的 embedding 被生成并保存')
def step_embedding_saved(context):
    assert context.result_count == 1
    rows = context.db.get_tweets_with_embeddings()
    assert any(r["id"] == "tweet_missing_emb" for r in rows)
    os.unlink(context.db_path)


@given('embedding API 始终失败')
def step_api_always_fails(context):
    context.api_always_fails = True


@then('重试 2 次后跳过，不抛出异常')
def step_retried_and_skipped(context):
    assert context.result_count == 0
    os.unlink(context.db_path)
