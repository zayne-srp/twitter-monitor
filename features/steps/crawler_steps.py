import json
import sys
import os

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.crawler.twitter_crawler import TwitterCrawler


@given("爬虫实例")
def step_crawler_instance(context):
    context.crawler = TwitterCrawler(cdp_port=18800)


@when('检查文本 "Hello…" 是否被截断')
def step_check_truncated(context):
    context.result = context.crawler._is_truncated("Hello\u2026")


@when('检查文本 "Hello world" 是否被截断')
def step_check_not_truncated(context):
    context.result = context.crawler._is_truncated("Hello world")


@then("返回 True")
def step_assert_true(context):
    assert context.result is True, f"Expected True, got {context.result}"


@then("返回 False")
def step_assert_false(context):
    assert context.result is False, f"Expected False, got {context.result}"


@when("解析双重编码的推文 JSON（外层 JSON 包裹字符串）")
def step_parse_double_encoded(context):
    inner = json.dumps([
        {
            "text": "Hello world",
            "author": "testuser",
            "time": "2025-01-01T00:00:00Z",
            "url": "https://x.com/testuser/status/123456",
        }
    ])
    raw = json.dumps(inner)
    context.parsed = context.crawler._parse_tweets_from_eval(raw, "for_you")


@then("成功返回推文列表")
def step_assert_tweet_list(context):
    assert len(context.parsed) == 1
    assert context.parsed[0]["id"] == "123456"
    assert context.parsed[0]["text"] == "Hello world"
    assert context.parsed[0]["feed_type"] == "for_you"
