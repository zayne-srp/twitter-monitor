import os
import sys
import sqlite3
import tempfile

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.storage.db import TweetDatabase


def _make_tweet(tweet_id="tweet001", feed_type="for_you", thread_root_id=None):
    tweet = {
        "id": tweet_id,
        "text": "Test tweet text",
        "author": "testuser",
        "url": f"https://x.com/testuser/status/{tweet_id}",
        "timestamp": "2025-01-01T00:00:00Z",
        "likes": 0,
        "retweets": 0,
        "feed_type": feed_type,
    }
    if thread_root_id is not None:
        tweet["thread_root_id"] = thread_root_id
    return tweet


@given("一个空数据库")
def step_empty_db(context):
    db_path = tempfile.mktemp(suffix=".db")
    context.db = TweetDatabase(db_path=db_path)
    context.db_path = db_path
    context.session_id = context.db.create_session()


@when("保存一条普通推文")
def step_save_normal_tweet(context):
    context.tweet = _make_tweet()
    context.save_result = context.db.save_tweet(context.tweet, context.session_id)


@then("数据库中存在该推文，thread_root_id 为空")
def step_tweet_exists_no_thread_root(context):
    assert context.save_result is True
    conn = sqlite3.connect(context.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM tweets WHERE id = ?", (context.tweet["id"],)).fetchone()
        assert row is not None
        assert row["thread_root_id"] is None
    finally:
        conn.close()
        os.unlink(context.db_path)


@when('保存一条 feed_type 为 thread 的推文，thread_root_id 为 "root123"')
def step_save_thread_tweet(context):
    context.tweet = _make_tweet(feed_type="thread", thread_root_id="root123")
    context.save_result = context.db.save_tweet(context.tweet, context.session_id)


@then('数据库中该推文的 thread_root_id 为 "root123"')
def step_thread_root_id_correct(context):
    assert context.save_result is True
    conn = sqlite3.connect(context.db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM tweets WHERE id = ?", (context.tweet["id"],)).fetchone()
        assert row is not None
        assert row["thread_root_id"] == "root123"
    finally:
        conn.close()
        os.unlink(context.db_path)


@given('数据库已有 id 为 "tweet001" 的推文')
def step_db_has_tweet(context):
    db_path = tempfile.mktemp(suffix=".db")
    context.db = TweetDatabase(db_path=db_path)
    context.db_path = db_path
    context.session_id = context.db.create_session()
    context.db.save_tweet(_make_tweet(), context.session_id)


@when("再次保存相同 id 的推文")
def step_save_duplicate(context):
    context.save_result = context.db.save_tweet(_make_tweet(), context.session_id)


@then("save_tweet 返回 False，数据库中只有一条")
def step_duplicate_rejected(context):
    assert context.save_result is False
    conn = sqlite3.connect(context.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM tweets WHERE id = 'tweet001'").fetchone()[0]
        assert count == 1
    finally:
        conn.close()
        os.unlink(context.db_path)
