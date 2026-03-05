from __future__ import annotations
import json
import re
import logging
import subprocess
from datetime import datetime, timezone
from typing import Dict, List

from openai import OpenAI

logger = logging.getLogger(__name__)


class AutoFollower:
    def __init__(self, cdp_port: int = 18800):
        self.cdp_port = cdp_port
        self.client = OpenAI()

    def evaluate_authors(self, tweets: List[dict]) -> Dict[str, float]:
        """Score authors 1-10 using OpenAI. Returns {author_handle: score}."""
        if not tweets:
            return {}

        # Group tweets by author
        author_tweets: Dict[str, List[str]] = {}
        for tweet in tweets:
            author = tweet.get("author", "").strip()
            text = tweet.get("text", "").strip()
            if author and text:
                author_tweets.setdefault(author, []).append(text)

        if not author_tweets:
            return {}

        # Build prompt
        authors_text = "\n\n".join(
            f"Author: @{author}\nTweets:\n" + "\n".join(f"- {t}" for t in texts[:5])
            for author, texts in author_tweets.items()
        )

        prompt = f"""You are evaluating Twitter authors for follow-worthiness based on their AI-related tweets.

Score each author from 1-10 where:
- 1-3: Low quality (spam, ads, pure reposts, no original insight)
- 4-6: Average (some value but not exceptional)
- 7-10: High quality (original insights, technical depth, unique perspectives on AI)

Authors and their tweets:
{authors_text}

Respond with ONLY a JSON object like: {{"@author1": 8.5, "@author2": 3.0}}
Include the @ prefix in keys."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            content = response.choices[0].message.content.strip()
            # Strip markdown code blocks if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            scores = json.loads(content)
            # Normalize keys to remove @
            return {k.lstrip("@"): float(v) for k, v in scores.items()}
        except Exception as e:
            logger.error("Failed to evaluate authors: %s", e)
            return {}

    def _run_browser_command(self, *args: str) -> str:
        cmd = ["agent-browser", "--cdp", str(self.cdp_port), *args]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Browser command timed out: {' '.join(cmd)}")
        if result.returncode != 0:
            raise RuntimeError(f"Browser command failed: {result.stderr}")
        return result.stdout

    def follow_author(self, author_handle: str) -> bool:
        """Navigate to author's profile and click Follow. Returns True on success."""
        handle = author_handle.lstrip("@")
        url = f"https://twitter.com/{handle}"
        logger.info("Attempting to follow @%s", handle)
        try:
            self._run_browser_command("open", url)
            import time; time.sleep(3)

            # Click the Follow button via JS evaluation
            js = """
(function() {
    const buttons = Array.from(document.querySelectorAll('[data-testid="placementTracking"] button, [data-testid*="follow"] button'));
    const followBtn = buttons.find(b => b.innerText && b.innerText.trim() === 'Follow');
    if (followBtn) { followBtn.click(); return 'clicked'; }
    // Try broader search
    const allBtns = Array.from(document.querySelectorAll('button[role="button"]'));
    const fb = allBtns.find(b => b.innerText && b.innerText.trim() === 'Follow');
    if (fb) { fb.click(); return 'clicked'; }
    return 'not_found';
})()
"""
            result = self._run_browser_command("eval", js)
            if "clicked" in result:
                logger.info("Successfully followed @%s", handle)
                return True
            else:
                logger.warning("Follow button not found for @%s", handle)
                return False
        except Exception as e:
            logger.error("Failed to follow @%s: %s", handle, e)
            return False

    def run(self, ai_tweets: List[dict], db) -> None:
        """Evaluate authors and follow high-quality ones not yet followed."""
        if not ai_tweets:
            logger.info("No AI tweets to evaluate for auto-follow")
            return

        logger.info("Evaluating %d AI tweets for auto-follow", len(ai_tweets))
        scores = self.evaluate_authors(ai_tweets)
        if not scores:
            logger.warning("No author scores returned")
            return

        logger.info("Author scores: %s", scores)
        already_followed = db.get_followed_accounts()

        # Build author -> handle mapping from tweet URLs
        author_to_handle: Dict[str, str] = {}
        for tweet in ai_tweets:
            author = tweet.get("author", "").strip()
            url = tweet.get("url", "")
            m = re.search(r"x\.com/([^/]+)/status/", url) or re.search(r"twitter\.com/([^/]+)/status/", url)
            if m and author:
                author_to_handle[author] = m.group(1)

        for author, score in scores.items():
            handle = author_to_handle.get(author, author)
            if score >= 7.0:
                if handle in already_followed:
                    logger.info("@%s already followed (score=%.1f)", handle, score)
                    continue
                logger.info("@%s score=%.1f >= 7, attempting follow", handle, score)
                success = self.follow_author(handle)
                if success:
                    db.save_followed_account(handle)
            else:
                logger.info("@%s score=%.1f < 7, skipping", handle, score)
