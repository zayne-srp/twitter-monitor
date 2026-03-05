import json
import sys
import os
from unittest.mock import patch, MagicMock

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.crawler.twitter_crawler import TwitterCrawler


@given("全文模式已启用")
def step_full_text_mode_enabled(context):
    context.crawler = TwitterCrawler(cdp_port=18800, full_text_mode=True)


@given('一条推文文本为 "Hello world"（不含截断符）')
def step_normal_tweet(context):
    context.tweet_text = "Hello world"


@when("爬虫判断是否需要抓全文")
def step_check_if_need_full_text(context):
    context.is_truncated = context.crawler._is_truncated(context.tweet_text)


@then("不触发详情页请求")
def step_no_detail_request(context):
    assert context.is_truncated is False


@given('一条推文文本末尾含有 "…"')
def step_truncated_tweet(context):
    context.tweet_text = "This is a long tweet that got truncated\u2026"
    context.tweet_url = "https://x.com/user/status/999"


@when("爬虫处理该截断推文")
def step_process_truncated(context):
    full_text_response = json.dumps(json.dumps("This is the complete full text of the tweet"))
    with patch.object(context.crawler, "_run_browser_command", return_value=full_text_response) as mock_cmd:
        context.full_text = context.crawler._fetch_full_text(context.tweet_url)
        context.mock_cmd = mock_cmd


@then("导航到推文详情页并返回完整文本")
def step_navigated_and_got_full_text(context):
    assert context.full_text == "This is the complete full text of the tweet"
    calls = context.mock_cmd.call_args_list
    assert any("open" in str(c) for c in calls), "Should have called 'open' to navigate"


@given("一条被截断的推文")
def step_a_truncated_tweet(context):
    context.tweet_text = "Truncated text…"
    context.tweet_url = "https://x.com/user/status/888"


@when("导航到详情页失败（抛出异常）")
def step_detail_page_fails(context):
    with patch.object(context.crawler, "_run_browser_command", side_effect=RuntimeError("Connection failed")):
        context.full_text = context.crawler._fetch_full_text(context.tweet_url)


@then("降级返回空字符串，不中断爬取流程")
def step_fallback_empty_string(context):
    assert context.full_text == ""
