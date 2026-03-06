"""Feishu Interactive Card builder for Twitter AI Monitor reports.

Converts the structured tweet report into a Feishu card payload using
msg_type="interactive", which supports Markdown rendering, section blocks,
and avoids the 3800-char plain-text truncation limit.

Feishu card spec: https://open.feishu.cn/document/ukTMukTMukTM/uYzM3QjL2MzN04iN3cDN
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Max tweets per card to keep messages digestible
_MAX_TWEETS_PER_CARD = 20
# Max chars per tweet text (Feishu markdown line limit)
_MAX_TWEET_TEXT = 200


def _get(obj: Any, key: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _tweet_line(tweet: Any, extra: int = 0) -> str:
    """Format a single tweet as a Feishu markdown list item."""
    author = _get(tweet, "author", "unknown")
    text = _get(tweet, "text", "")[:_MAX_TWEET_TEXT]
    url = _get(tweet, "url", "")
    likes = _get(tweet, "likes", 0)
    retweets = _get(tweet, "retweets", 0)
    extra_str = f" （另有 {extra} 条）" if extra > 0 else ""
    # Feishu markdown: [display](url) for links
    link_part = f"[🔗]({url})" if url else ""
    return (
        f"**@{author}**: {text} {link_part} "
        f"| ❤ {likes} 🔁 {retweets}{extra_str}"
    )


def _markdown_element(content: str) -> Dict[str, Any]:
    return {"tag": "markdown", "content": content}


def _section(text: str) -> Dict[str, Any]:
    return {"tag": "section", "text": _markdown_element(text)}


def _divider() -> Dict[str, Any]:
    return {"tag": "hr"}


def build_card(
    tweets: List[Any],
    session_id: str,
    generated_at: str,
    clustered=None,  # Dict[str, List[Any]] | None
    followed=None,  # List[str] | None
) -> Dict[str, Any]:
    """Build a Feishu interactive card payload dict.

    Args:
        tweets: List of tweet dicts (already filtered to display set).
        session_id: Crawl session identifier shown in the header.
        generated_at: Human-readable timestamp string.
        clustered: Optional {topic: [tweets]} from AI clustering.
        followed: Optional list of newly followed account handles.

    Returns:
        A dict ready to POST as the Feishu webhook JSON body.
    """
    display_tweets = tweets[:_MAX_TWEETS_PER_CARD]

    # Aggregate by author: keep best tweet per author
    author_map: Dict[str, List[Any]] = defaultdict(list)
    for t in display_tweets:
        author_map[_get(t, "author", "")].append(t)

    aggregated: List[tuple[Any, int]] = []
    for author, author_tweets in author_map.items():
        best = max(author_tweets, key=lambda t: (
            _get(t, "likes", 0),
            _get(t, "timestamp", "") or "",
        ))
        aggregated.append((best, len(author_tweets) - 1))

    extra_map = {_get(t, "author", ""): e for t, e in aggregated}
    dedup_tweets = [t for t, _ in aggregated]

    # ── Header ──────────────────────────────────────────────────────────
    header = {
        "title": {
            "tag": "plain_text",
            "content": f"🤖 Twitter AI Monitor — {len(tweets)} 条 AI 推文",
        },
        "template": "blue",
    }

    # ── Body elements ────────────────────────────────────────────────────
    elements: List[Dict[str, Any]] = []

    # Meta info
    omitted = len(tweets) - _MAX_TWEETS_PER_CARD if len(tweets) > _MAX_TWEETS_PER_CARD else 0
    meta_parts = [f"**Session**: {session_id}", f"**生成时间**: {generated_at}"]
    if omitted > 0:
        meta_parts.append(f"（还有 {omitted} 条已省略）")
    elements.append(_section("\n".join(meta_parts)))
    elements.append(_divider())

    if clustered:
        for topic_name, topic_tweets in clustered.items():
            if not topic_tweets:
                continue
            elements.append(_section(f"**📌 {topic_name}** ({len(topic_tweets)})"))
            lines = []
            for t in topic_tweets:
                extra = extra_map.get(_get(t, "author", ""), 0)
                lines.append("- " + _tweet_line(t, extra))
            elements.append(_section("\n".join(lines)))
            elements.append(_divider())
    else:
        # Fallback: flat list grouped by simple category
        from src.reporter.report_generator import ReportGenerator, _CATEGORY_KEYWORDS
        rg = ReportGenerator()
        cat_map: Dict[str, List[Any]] = defaultdict(list)
        for t in dedup_tweets:
            cat_map[rg.categorize_tweet(t)].append(t)

        category_order = [
            "Models & Research",
            "Tools & Products",
            "Industry News",
            "Tutorials & Technical",
            "Opinion & Discussion",
        ]
        for cat in category_order:
            cat_tweets = cat_map.get(cat, [])
            if not cat_tweets:
                continue
            elements.append(_section(f"**📁 {cat}** ({len(cat_tweets)})"))
            lines = []
            for t in cat_tweets:
                extra = extra_map.get(_get(t, "author", ""), 0)
                lines.append("- " + _tweet_line(t, extra))
            elements.append(_section("\n".join(lines)))
            elements.append(_divider())

    # Followed accounts footer
    if followed:
        handles = ", ".join(f"@{h}" for h in followed)
        elements.append(_section(f"🤝 **本次新关注**: {handles}"))

    card = {
        "config": {"wide_screen_mode": True},
        "header": header,
        "elements": elements,
    }
    return {"msg_type": "interactive", "card": json.dumps(card)}


def build_empty_card(generated_at: str) -> Dict[str, Any]:
    """Card for when there are no AI tweets to report."""
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🤖 Twitter AI Monitor"},
            "template": "grey",
        },
        "elements": [
            _section(f"**{generated_at}**\n本次抓取未发现 AI 相关推文。"),
        ],
    }
    return {"msg_type": "interactive", "card": json.dumps(card)}
