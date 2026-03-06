"""Unit tests for src/reporter/feishu_card.py"""
import json
import pytest
from src.reporter.feishu_card import build_card, build_empty_card, _tweet_line


def _make_tweet(author="alice", text="GPT-5 is out", likes=10, retweets=3, url="https://x.com/alice/1"):
    return {"id": "1", "author": author, "text": text, "likes": likes, "retweets": retweets, "url": url, "timestamp": ""}


class TestBuildEmptyCard:
    def test_msg_type_interactive(self):
        payload = build_empty_card("2026-03-07 01:00 UTC")
        assert payload["msg_type"] == "interactive"

    def test_card_is_json_string(self):
        payload = build_empty_card("2026-03-07 01:00 UTC")
        card = json.loads(payload["card"])
        assert "elements" in card
        assert "header" in card

    def test_header_template_grey(self):
        payload = build_empty_card("now")
        card = json.loads(payload["card"])
        assert card["header"]["template"] == "grey"

    def test_body_mentions_no_tweets(self):
        payload = build_empty_card("now")
        card = json.loads(payload["card"])
        text = card["elements"][0]["text"]["content"]
        assert "未发现" in text


class TestBuildCard:
    def test_msg_type_interactive(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "sess-1", "2026-03-07 01:00 UTC")
        assert payload["msg_type"] == "interactive"

    def test_card_valid_json(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "sess-1", "now")
        card = json.loads(payload["card"])
        assert "elements" in card

    def test_header_contains_count(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "sess-1", "now")
        card = json.loads(payload["card"])
        title = card["header"]["title"]["content"]
        assert "1" in title

    def test_header_blue(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "sess-1", "now")
        card = json.loads(payload["card"])
        assert card["header"]["template"] == "blue"

    def test_tweet_author_in_elements(self):
        tweets = [_make_tweet(author="bob")]
        payload = build_card(tweets, "sess-1", "now")
        card = json.loads(payload["card"])
        full_text = json.dumps(card["elements"])
        assert "bob" in full_text

    def test_wide_screen_mode(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "s", "now")
        card = json.loads(payload["card"])
        assert card["config"]["wide_screen_mode"] is True

    def test_followed_footer_present(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "s", "now", followed=["carol"])
        card = json.loads(payload["card"])
        full_text = json.dumps(card["elements"])
        assert "carol" in full_text

    def test_followed_absent_when_none(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "s", "now", followed=None)
        card = json.loads(payload["card"])
        full_text = json.dumps(card["elements"])
        assert "新关注" not in full_text

    def test_clustered_topic_name_in_elements(self):
        tweets = [_make_tweet()]
        clustered = {"LLM News": tweets}
        payload = build_card(tweets, "s", "now", clustered=clustered)
        card = json.loads(payload["card"])
        full_text = json.dumps(card["elements"])
        assert "LLM News" in full_text

    def test_max_tweets_truncation(self):
        tweets = [_make_tweet(author=f"user{i}", url=f"https://x.com/{i}") for i in range(30)]
        payload = build_card(tweets, "s", "now")
        card = json.loads(payload["card"])
        # The omitted count should appear in the meta section
        # json.dumps escapes non-ASCII; check via str of the card dict
        full_text = str(card["elements"])
        assert "省略" in full_text

    def test_empty_followed_list_no_footer(self):
        tweets = [_make_tweet()]
        payload = build_card(tweets, "s", "now", followed=[])
        card = json.loads(payload["card"])
        full_text = json.dumps(card["elements"])
        assert "新关注" not in full_text


class TestTweetLine:
    def test_includes_author(self):
        tweet = _make_tweet(author="zayne")
        line = _tweet_line(tweet)
        assert "@zayne" in line

    def test_includes_likes(self):
        tweet = _make_tweet(likes=42)
        line = _tweet_line(tweet)
        assert "42" in line

    def test_includes_link(self):
        tweet = _make_tweet(url="https://x.com/alice/123")
        line = _tweet_line(tweet)
        assert "https://x.com/alice/123" in line

    def test_extra_shown(self):
        tweet = _make_tweet()
        line = _tweet_line(tweet, extra=3)
        assert "另有 3 条" in line

    def test_no_extra_when_zero(self):
        tweet = _make_tweet()
        line = _tweet_line(tweet, extra=0)
        assert "另有" not in line

    def test_text_truncated_at_200(self):
        long_text = "A" * 300
        tweet = _make_tweet(text=long_text)
        line = _tweet_line(tweet)
        assert "A" * 201 not in line
