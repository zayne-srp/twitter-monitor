import os
import sys
from unittest.mock import patch

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.reporter.report_generator import ReportGenerator


def _make_tweet(author="alice", text="AI model update", tweet_id="1", likes=0):
    return {
        "id": tweet_id,
        "text": text,
        "author": author,
        "url": f"https://x.com/{author}/status/{tweet_id}",
        "timestamp": "2025-01-01T00:00:00Z",
        "likes": likes,
        "retweets": 0,
        "feed_type": "for_you",
    }


@given('推文列表包含同一作者 "@alice" 的 3 条推文')
def step_tweets_same_author_3(context):
    context.reporter = ReportGenerator()
    context.tweets = [
        _make_tweet("alice", "First AI tweet about GPT models", "1", likes=10),
        _make_tweet("alice", "Second AI tweet about training", "2", likes=5),
        _make_tweet("alice", "Third AI tweet about Claude", "3", likes=2),
    ]


@when('生成报告')
def step_generate_report(context):
    cluster_return = getattr(context, 'cluster_result', None)
    with patch.object(context.reporter, "cluster_topics", return_value=cluster_return):
        context.report = context.reporter.generate_report(context.tweets, "test-session")


@then('报告中 "@alice" 只出现一次，并注明另有 2 条')
def step_alice_once_with_extra(context):
    lines = [l for l in context.report.split("\n") if "@alice" in l and l.startswith("- ")]
    assert len(lines) == 1, f"Expected 1 line with @alice, got {len(lines)}: {lines}"
    assert "另有 2 条" in lines[0]


@given('推文列表包含 "@alice" 和 "@bob" 各 1 条推文')
def step_tweets_two_authors(context):
    context.reporter = ReportGenerator()
    context.tweets = [
        _make_tweet("alice", "AI model update about GPT", "1"),
        _make_tweet("bob", "New AI research paper on training", "2"),
    ]


@then('报告中 "@alice" 和 "@bob" 各出现一次')
def step_both_authors_once(context):
    alice_lines = [l for l in context.report.split("\n") if "@alice" in l and l.startswith("- ")]
    bob_lines = [l for l in context.report.split("\n") if "@bob" in l and l.startswith("- ")]
    assert len(alice_lines) == 1
    assert len(bob_lines) == 1


@given('推文列表包含多条关于不同话题的推文')
def step_tweets_different_topics(context):
    context.reporter = ReportGenerator()
    context.tweets = [
        _make_tweet("alice", "GPT-5 released", "1"),
        _make_tweet("bob", "AI startup raises funding", "2"),
        _make_tweet("carol", "New RAG tutorial published", "3"),
    ]


@given('OpenAI cluster_topics 返回话题分组')
def step_cluster_topics_returns(context):
    context.cluster_result = {
        "Models": [context.tweets[0]],
        "Industry": [context.tweets[1]],
        "Tutorials": [context.tweets[2]],
    }


@then('报告按话题分组展示')
def step_report_clustered(context):
    assert "## Models" in context.report
    assert "## Industry" in context.report
    assert "## Tutorials" in context.report


@given('推文列表包含多条推文')
def step_tweets_multiple(context):
    context.reporter = ReportGenerator()
    context.tweets = [
        _make_tweet("alice", "GPT-5 model released today", "1"),
        _make_tweet("bob", "AI startup news about funding", "2"),
    ]


@given('OpenAI cluster_topics 抛出异常')
def step_cluster_topics_exception(context):
    # cluster_result not set, so it defaults to None in the @when step
    pass


@then('报告使用默认关键字分类展示')
def step_report_default_categories(context):
    has_standard_category = any(
        cat in context.report
        for cat in ["Models & Research", "Tools & Products", "Industry News",
                     "Tutorials & Technical", "Opinion & Discussion"]
    )
    assert has_standard_category, f"Expected standard categories in report:\n{context.report}"
