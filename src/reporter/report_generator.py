import json as _json
import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional

import requests
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CATEGORY_KEYWORDS = {
    "Models & Research": [
        "GPT", "Claude", "Gemini", "Llama", "Mistral", "DeepSeek", "Qwen",
        "Grok", "Sora", "model", "benchmark", "parameter", "training",
        "paper", "research", "arxiv",
    ],
    "Tools & Products": [
        "ChatGPT", "Midjourney", "DALL-E", "Stable Diffusion", "Copilot",
        "product", "launch", "app", "platform", "release", "API",
    ],
    "Industry News": [
        "funding", "acquisition", "billion", "million", "startup",
        "regulation", "policy", "lawsuit", "partnership", "valuation",
    ],
    "Tutorials & Technical": [
        "tutorial", "guide", "how to", "fine-tuning", "fine tuning",
        "RAG", "embedding", "vector", "prompt engineering", "code",
        "implementation", "architecture", "deploy",
    ],
}


def _get(obj, key, default=''):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


class ReportGenerator:
    def categorize_tweet(self, tweet: Dict[str, Any]) -> str:
        text_lower = (tweet.get("text", "") if isinstance(tweet, dict) else getattr(tweet, "text", "")).lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw.lower() in text_lower for kw in keywords):
                return category
        return "Opinion & Discussion"

    def cluster_topics(self, tweets) -> Optional[Dict[str, list]]:
        """Use OpenAI to cluster tweets into up to 5 topics.

        Returns {topic: [tweets]} or None on failure.

        Note: This method makes one OpenAI API call.  Call it *once* per
        pipeline run and pass the result to both :meth:`generate_report` and
        :meth:`send_as_card` to avoid redundant API calls.
        """
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=api_key)
        texts = [f"{i+1}. {_get(t,'author','')}: {_get(t,'text','')[:100]}" for i, t in enumerate(tweets)]
        prompt = f"""Cluster these {len(tweets)} tweets into at most 5 topic groups.
Return JSON: {{"topics": [{{"name": "Topic Name", "indices": [0,1,2]}}]}}
Use 0-based indices. Assign every tweet to exactly one topic.
Tweets:
""" + "\n".join(texts)
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=500,
            )
            content = response.choices[0].message.content.strip()
            if '```' in content:
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            data = _json.loads(content)
            result = {}
            for topic in data.get('topics', []):
                name = topic['name']
                indices = topic['indices']
                result[name] = [tweets[i] for i in indices if i < len(tweets)]
            return result if result else None
        except Exception as e:
            logger.warning("Topic clustering failed: %s", e)
            return None

    def generate_report(
        self,
        tweets: List[Dict[str, Any]],
        session_id: str,
        *,
        clustered: Optional[Dict[str, list]] = None,
    ) -> str:
        """Generate a Markdown report.

        Args:
            tweets: AI-related tweet rows to include in the report.
            session_id: Crawl session identifier shown in the header.
            clustered: Pre-computed topic clusters from :meth:`cluster_topics`.
                If provided, the method skips its own clustering API call.
                Pass ``None`` to let the method call OpenAI itself (legacy
                behaviour, triggers an extra API call).
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# Twitter AI Monitor Report",
            f"",
            f"**Session**: {session_id}",
            f"**Generated**: {now}",
            f"**Total AI Tweets**: {len(tweets)}",
            f"",
        ]

        if not tweets:
            lines.append("No AI-related tweets found in this session.")
            return "\n".join(lines)

        display_tweets = tweets[:20]
        omitted = len(tweets) - 20 if len(tweets) > 20 else 0

        # Aggregate by author: keep best tweet per author
        author_tweets_map = defaultdict(list)
        for tweet in display_tweets:
            author = _get(tweet, 'author', '')
            author_tweets_map[author].append(tweet)

        aggregated = []
        for author, author_tweet_list in author_tweets_map.items():
            best = max(author_tweet_list, key=lambda t: (
                _get(t, 'likes', 0),
                _get(t, 'timestamp', '') or ''
            ))
            extra = len(author_tweet_list) - 1
            aggregated.append((best, extra))
        display_tweets = [t for t, _ in aggregated]
        extra_map = {_get(t, 'author', ''): e for t, e in aggregated}

        # Use pre-computed clusters when available to avoid a redundant API call.
        if clustered is None:
            clustered = self.cluster_topics(display_tweets)

        if clustered:
            for topic_name, topic_tweets in clustered.items():
                lines.append(f"## {topic_name} ({len(topic_tweets)})")
                lines.append("")
                for tweet in topic_tweets:
                    author = _get(tweet, 'author', '')
                    extra = extra_map.get(author, 0)
                    extra_str = f" （另有 {extra} 条）" if extra > 0 else ""
                    lines.append(
                        f"- **@{author}**: {_get(tweet,'text')} "
                        f"[link]({_get(tweet,'url')}) "
                        f"| ❤ {_get(tweet,'likes',0)} 🔁 {_get(tweet,'retweets',0)}{extra_str}"
                    )
                lines.append("")
        else:
            categorized: dict[str, list[Dict[str, Any]]] = defaultdict(list)
            for tweet in display_tweets:
                category = self.categorize_tweet(tweet)
                categorized[category].append(tweet)

            category_order = [
                "Models & Research",
                "Tools & Products",
                "Industry News",
                "Tutorials & Technical",
                "Opinion & Discussion",
            ]

            for category in category_order:
                cat_tweets = categorized.get(category, [])
                if not cat_tweets:
                    continue
                lines.append(f"## {category} ({len(cat_tweets)})")
                lines.append("")
                for tweet in cat_tweets:
                    author = _get(tweet, 'author', '')
                    extra = extra_map.get(author, 0)
                    extra_str = f" （另有 {extra} 条）" if extra > 0 else ""
                    lines.append(
                        f"- **@{author}**: {_get(tweet,'text')} "
                        f"[link]({_get(tweet,'url')}) "
                        f"| ❤ {_get(tweet,'likes',0)} 🔁 {_get(tweet,'retweets',0)}{extra_str}"
                    )
                lines.append("")

        if omitted > 0:
            lines.append(f"（还有 {omitted} 条，已省略）")

        return "\n".join(lines)

    def send_report(self, content: str) -> bool:
        """Send report via Feishu webhook (plain text fallback) or print to stdout.

        Prefer :meth:`send_as_card` for rich Feishu card output.
        This method is kept as a fallback for non-card environments.

        Returns True if webhook sent.
        """
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
        MAX_CHARS = 3800
        if webhook_url and len(content) > MAX_CHARS:
            content = content[:MAX_CHARS] + "...（内容过长已截断）"
        if webhook_url:
            resp = requests.post(
                webhook_url,
                json={"msg_type": "text", "content": {"text": content}},
            )
            resp.raise_for_status()
            return True
        else:
            print(content)
            return False

    def send_as_card(
        self,
        tweets: List[Dict[str, Any]],
        session_id: str,
        generated_at: str,
        followed=None,  # List[str] | None
        *,
        clustered: Optional[Dict[str, list]] = None,
    ) -> bool:
        """Send report as a Feishu interactive card.

        Uses ``msg_type: "interactive"`` which renders Markdown, supports
        wide-screen layout, and removes the 3800-char plain-text limit.

        Falls back to :meth:`send_report` (plain text) if the webhook is not
        configured or the card POST fails.

        Args:
            tweets: Raw tweet rows to display.
            session_id: Crawl session identifier for the card header.
            generated_at: Human-readable timestamp shown in the card.
            followed: Newly followed account handles (shown in footer).
            clustered: Pre-computed topic clusters from :meth:`cluster_topics`.
                When provided the method skips its own clustering API call,
                halving the total number of OpenAI requests per pipeline run.

        Returns:
            True if the card was sent via webhook, False otherwise.
        """
        from src.reporter.feishu_card import build_card, build_empty_card

        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
        if not webhook_url:
            # No webhook — fall back to stdout plain text
            markdown = self.generate_report(tweets, session_id, clustered=clustered)
            print(markdown)
            return False

        try:
            if tweets:
                # Use pre-computed clusters when available to avoid a redundant
                # API call (the caller already invoked cluster_topics once).
                if clustered is None:
                    clustered = self.cluster_topics(tweets[:20])
                payload = build_card(
                    tweets,
                    session_id=session_id,
                    generated_at=generated_at,
                    clustered=clustered,
                    followed=followed,
                )
            else:
                payload = build_empty_card(generated_at)

            resp = requests.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("Report sent as Feishu interactive card (%d tweets)", len(tweets))
            return True
        except Exception as exc:
            logger.warning("Feishu card send failed, falling back to plain text: %s", exc)
            markdown = self.generate_report(tweets, session_id, clustered=clustered)
            return self.send_report(markdown)

    def save_report(self, content: str, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{timestamp}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            f.write(content)
        logger.info("Report saved to %s", filepath)
        return filepath
