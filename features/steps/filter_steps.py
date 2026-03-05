import os
import sys

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.filter.ai_filter import AIFilter


@given('一组推文包含纯转发推文 "RT @ someuser some content"')
def step_tweets_with_retweet(context):
    context.ai_filter = AIFilter.__new__(AIFilter)
    context.tweets = [
        {"text": "RT @someuser some content", "id": "1"},
        {"text": "This is a normal AI tweet about GPT models", "id": "2"},
    ]


@when('执行 pre_filter')
def step_exec_pre_filter(context):
    context.result = context.ai_filter.pre_filter(context.tweets)


@then('该转发推文被移除')
def step_retweet_removed(context):
    texts = [t["text"] for t in context.result]
    assert not any(t.startswith("RT @") for t in texts)
    assert len(context.result) == 1


@given('一条推文含有短链接但正文超过 20 字 "这是一篇关于AI的深度文章，讲述了大模型的训练原理，值得一读 https://bit.ly/xyz"')
def step_tweet_with_short_link_and_content(context):
    context.ai_filter = AIFilter.__new__(AIFilter)
    context.tweets = [
        {"text": "这是一篇关于AI的深度文章，讲述了大模型的训练原理，值得一读 https://bit.ly/xyz", "id": "1"},
    ]


@then('该推文被保留')
def step_tweet_kept(context):
    assert len(context.result) == 1


@given('一条推文文本为空或少于 10 字 "hi"')
def step_tweet_short_text(context):
    context.ai_filter = AIFilter.__new__(AIFilter)
    context.tweets = [
        {"text": "hi", "id": "1"},
    ]


@then('该推文被移除')
def step_tweet_removed(context):
    assert len(context.result) == 0
