import json
import sys
import os
import tempfile
from unittest.mock import patch

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.crawler.twitter_crawler import TwitterCrawler
from src.storage.db import TweetDatabase


def _make_thread_response(tweets):
    """Create a double-encoded JSON response for thread tweets."""
    return json.dumps(json.dumps(tweets))


@given("详情页返回单条推文")
def step_single_tweet_detail(context):
    context.crawler = TwitterCrawler(cdp_port=18800, full_text_mode=True)
    context.thread_data = [
        {
            "text": "Single tweet",
            "author": "user1",
            "time": "2025-01-01T00:00:00Z",
            "url": "https://x.com/user1/status/100",
        }
    ]


@given("详情页返回 3 条连续推文")
def step_three_tweets_detail(context):
    context.crawler = TwitterCrawler(cdp_port=18800, full_text_mode=True)
    context.thread_data = [
        {
            "text": f"Tweet {i}",
            "author": "user1",
            "time": "2025-01-01T00:00:00Z",
            "url": f"https://x.com/user1/status/{100 + i}",
        }
        for i in range(3)
    ]


@when("爬虫抓取 thread")
def step_fetch_thread(context):
    response = _make_thread_response(context.thread_data)
    with patch.object(context.crawler, "_run_browser_command", return_value=response):
        context.thread_result = context.crawler._fetch_thread_tweets(
            "https://x.com/user1/status/100", "for_you"
        )


@then("返回单条推文列表，无 thread_root_id 关联")
def step_single_tweet_result(context):
    assert len(context.thread_result) == 1
    assert context.thread_result[0]["thread_root_id"] == context.thread_result[0]["id"]


@then("返回 3 条推文，每条 thread_root_id 等于第一条的 id")
def step_three_tweets_with_root_id(context):
    assert len(context.thread_result) == 3
    root_id = context.thread_result[0]["id"]
    assert root_id != ""
    for tweet in context.thread_result:
        assert tweet["thread_root_id"] == root_id


@given("数据库已有某 thread 的前两条推文")
def step_db_has_two_thread_tweets(context):
    context.crawler = TwitterCrawler(cdp_port=18800, full_text_mode=True)
    db_path = tempfile.mktemp(suffix=".db")
    context.db = TweetDatabase(db_path=db_path)
    context.db_path = db_path
    session_id = context.db.create_session()
    context.session_id = session_id
    for i in range(2):
        context.db.save_tweet(
            {
                "id": f"t{i}",
                "text": f"Thread tweet {i}",
                "author": "user1",
                "url": f"https://x.com/user1/status/t{i}",
                "timestamp": "2025-01-01T00:00:00Z",
                "likes": 0,
                "retweets": 0,
                "feed_type": "thread",
                "thread_root_id": "t0",
            },
            session_id,
        )


@when("保存同一 thread 的 3 条推文")
def step_save_three_thread_tweets(context):
    context.save_results = []
    for i in range(3):
        result = context.db.save_tweet(
            {
                "id": f"t{i}",
                "text": f"Thread tweet {i}",
                "author": "user1",
                "url": f"https://x.com/user1/status/t{i}",
                "timestamp": "2025-01-01T00:00:00Z",
                "likes": 0,
                "retweets": 0,
                "feed_type": "thread",
                "thread_root_id": "t0",
            },
            context.session_id,
        )
        context.save_results.append(result)


@then("只新增第 3 条，已存在的跳过")
def step_only_third_added(context):
    assert context.save_results[0] is False  # t0 already existed
    assert context.save_results[1] is False  # t1 already existed
    assert context.save_results[2] is True   # t2 is new
    os.unlink(context.db_path)
