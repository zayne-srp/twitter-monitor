import json
import os
import sys
import tempfile

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.storage.db import TweetDatabase
from src.search.semantic_dedup import SemanticDeduplicator


def _make_tweet(tweet_id, text="Test tweet", author="user1", embedding=None,
                feed_type="for_you", is_ai_related=0):
    return {
        "id": tweet_id,
        "text": text,
        "author": author,
        "url": f"https://x.com/{author}/status/{tweet_id}",
        "timestamp": "2025-01-01T00:00:00Z",
        "likes": 10,
        "retweets": 2,
        "feed_type": feed_type,
        "embedding": json.dumps(embedding) if embedding is not None else None,
        "is_ai_related": is_ai_related,
    }


def _setup_db(context):
    db_path = tempfile.mktemp(suffix=".db")
    context.db = TweetDatabase(db_path=db_path)
    context.db_path = db_path
    context.session_id = context.db.create_session()


def _cleanup_db(context):
    if hasattr(context, "db_path") and os.path.exists(context.db_path):
        os.unlink(context.db_path)


# --- Scenario 1 & 2: similar / dissimilar embeddings ---

@given("数据库中有一条推文，embedding 为 [0.1, 0.2, 0.3]")
def step_existing_tweet_with_embedding(context):
    _setup_db(context)
    tweet = _make_tweet("existing001", embedding=[0.1, 0.2, 0.3])
    context.db.save_tweet(tweet, context.session_id)
    context.db.save_embedding("existing001", json.dumps([0.1, 0.2, 0.3]))


@given("新爬取到一条推文，embedding 与已有推文余弦相似度为 0.95")
def step_new_tweet_high_similarity(context):
    # [0.101, 0.201, 0.301] has >0.999 cosine similarity with [0.1, 0.2, 0.3]
    context.new_embedding = [0.101, 0.201, 0.301]
    new_session = context.db.create_session()
    tweet = _make_tweet("new001", embedding=context.new_embedding)
    context.db.save_tweet(tweet, new_session)
    context.db.save_embedding("new001", json.dumps(context.new_embedding))
    context.new_session_id = new_session


@given("新爬取到一条推文，embedding 与已有推文余弦相似度为 0.80")
def step_new_tweet_low_similarity(context):
    # [0.9, 0.1, 0.1] has ~0.59 cosine similarity with [0.1, 0.2, 0.3] — well below threshold
    context.new_embedding = [0.9, 0.1, 0.1]
    new_session = context.db.create_session()
    tweet = _make_tweet("new001", embedding=context.new_embedding)
    context.db.save_tweet(tweet, new_session)
    context.db.save_embedding("new001", json.dumps(context.new_embedding))
    context.new_session_id = new_session


@when("执行语义去重")
def step_run_dedup(context):
    deduplicator = SemanticDeduplicator(similarity_threshold=0.90)
    if hasattr(context, "new_session_id"):
        new_tweets = context.db.get_tweets_by_session(context.new_session_id)
    elif hasattr(context, "no_emb_session_id"):
        new_tweets = context.db.get_tweets_by_session(context.no_emb_session_id)
    else:
        new_tweets = []
    existing_tweets = context.db.get_tweets_with_embeddings_recent(hours=48)
    context.dedup_ids = deduplicator.deduplicate(new_tweets, existing_tweets)
    for tweet_id, dup_of in context.dedup_ids:
        context.db.mark_duplicate(tweet_id, dup_of)


@then("新推文被标记为 is_duplicate=1")
def step_new_tweet_marked_duplicate(context):
    import sqlite3
    conn = sqlite3.connect(context.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT is_duplicate, duplicate_of FROM tweets WHERE id = 'new001'").fetchone()
        assert row["is_duplicate"] == 1, f"Expected is_duplicate=1, got {row['is_duplicate']}"
        assert row["duplicate_of"] == "existing001"
    finally:
        conn.close()
        _cleanup_db(context)


@then("新推文 is_duplicate 仍为 0")
def step_new_tweet_not_duplicate(context):
    import sqlite3
    conn = sqlite3.connect(context.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT is_duplicate, duplicate_of FROM tweets WHERE id = 'new001'").fetchone()
        assert row["is_duplicate"] == 0, f"Expected is_duplicate=0, got {row['is_duplicate']}"
        assert row["duplicate_of"] is None
    finally:
        conn.close()
        _cleanup_db(context)


# --- Scenario 3: no embedding ---

@given("一条没有 embedding 的新推文")
def step_no_embedding_tweet(context):
    _setup_db(context)
    tweet = _make_tweet("no_emb001")
    new_session = context.db.create_session()
    context.db.save_tweet(tweet, new_session)
    context.no_emb_session_id = new_session


@then("该推文不被标记为重复")
def step_no_embedding_not_marked(context):
    assert len(context.dedup_ids) == 0
    import sqlite3
    conn = sqlite3.connect(context.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT is_duplicate FROM tweets WHERE id = 'no_emb001'").fetchone()
        assert row["is_duplicate"] == 0
    finally:
        conn.close()
        _cleanup_db(context)


# --- Scenario 4: report excludes duplicates ---

@given("数据库中有3条 AI 相关推文，其中1条被标记为语义重复")
def step_three_tweets_one_duplicate(context):
    _setup_db(context)
    for i in range(1, 4):
        tweet = _make_tweet(f"ai{i:03d}", text=f"AI tweet {i}", is_ai_related=1)
        context.db.save_tweet(tweet, context.session_id)
    context.db.mark_ai_related([f"ai{i:03d}" for i in range(1, 4)])
    context.db.mark_duplicate("ai003", "ai001")


@when("查询非重复推文生成报告")
def step_query_non_dup_for_report(context):
    context.non_dup_tweets = context.db.get_non_duplicate_ai_tweets()


@then("报告只包含2条推文")
def step_report_has_two(context):
    assert len(context.non_dup_tweets) == 2, (
        f"Expected 2 tweets, got {len(context.non_dup_tweets)}"
    )
    ids = {t["id"] for t in context.non_dup_tweets}
    assert "ai003" not in ids, "Duplicate tweet ai003 should not be in results"
    _cleanup_db(context)
