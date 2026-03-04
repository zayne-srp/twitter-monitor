import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import List

import requests

from typing import Any, Dict

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

    def generate_report(self, tweets: List[Dict[str, Any]], session_id: str) -> str:
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

        categorized: dict[str, list[Dict[str, Any]]] = defaultdict(list)
        for tweet in tweets:
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
                lines.append(
                    f"- **@{_get(tweet,'author')}**: {_get(tweet,'text')} "
                    f"[link]({_get(tweet,'url')}) "
                    f"| ❤ {_get(tweet,'likes',0)} 🔁 {_get(tweet,'retweets',0)}"
                )
            lines.append("")

        return "\n".join(lines)

    def send_report(self, content: str) -> bool:
        """Send report via Feishu webhook or print to stdout. Returns True if webhook sent."""
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL")
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

    def save_report(self, content: str, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{timestamp}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            f.write(content)
        logger.info("Report saved to %s", filepath)
        return filepath
