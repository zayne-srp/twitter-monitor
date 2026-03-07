from __future__ import annotations
import json
import re
import logging
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Set

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
                import time as _time
                _time.sleep(1.5)
                js_check = 'document.querySelector(\'[data-testid*="unfollow"]\') ? "following" : (Array.from(document.querySelectorAll("button")).find(b => b.innerText && b.innerText.trim() === "Following") ? "following" : "not_following")'
                confirm_result = self._run_browser_command("eval", js_check)
                if "following" in confirm_result and "not_following" not in confirm_result:
                    logger.info("Successfully followed @%s (confirmed)", handle)
                    return True
                else:
                    logger.warning("Follow confirmation failed for @%s", handle)
                    return False
            else:
                logger.warning("Follow button not found for @%s", handle)
                return False
        except Exception as e:
            logger.error("Failed to follow @%s: %s", handle, e)
            return False

    @staticmethod
    def _extract_handle(tweet: dict) -> str:
        """Return the Twitter handle for a tweet, extracted from URL or author field."""
        url = tweet.get("url", "")
        m = re.search(r"(?:x|twitter)\.com/([^/]+)/status/", url)
        if m:
            return m.group(1)
        return tweet.get("author", "").strip().lstrip("@")

    def run(self, ai_tweets: List[dict], db) -> List[str]:
        """Evaluate authors and follow high-quality ones not yet followed.

        The already-followed accounts are fetched from the DB *before* calling
        OpenAI so that tweets from already-followed authors are excluded from
        the scoring payload.  This avoids paying for API tokens on authors we
        will unconditionally skip, and also keeps the prompt shorter (faster
        and cheaper).

        Returns:
            List of newly followed handles (without '@').
        """
        newly_followed: List[str] = []
        if not ai_tweets:
            logger.info("No AI tweets to evaluate for auto-follow")
            return newly_followed

        # ── Pre-fetch followed accounts before scoring ───────────────────
        # Fetching *before* evaluate_authors lets us exclude already-followed
        # authors from the OpenAI prompt entirely, saving tokens and latency.
        already_followed: Set[str] = db.get_followed_accounts()

        # Build author -> handle mapping from tweet URLs
        author_to_handle: Dict[str, str] = {}
        for tweet in ai_tweets:
            author = tweet.get("author", "").strip()
            if author:
                author_to_handle[author] = self._extract_handle(tweet)

        # Filter tweets to only those whose author is not yet followed
        new_author_tweets = [
            t for t in ai_tweets
            if author_to_handle.get(t.get("author", "").strip(), "") not in already_followed
        ]

        skipped_count = len(ai_tweets) - len(new_author_tweets)
        if skipped_count:
            logger.info(
                "Auto-follow: skipping %d tweets from %d already-followed author(s) "
                "before OpenAI scoring",
                skipped_count,
                len({author_to_handle.get(t.get("author", "").strip(), "") for t in ai_tweets} & already_followed),
            )

        if not new_author_tweets:
            logger.info("All AI tweet authors already followed; skipping OpenAI scoring")
            return newly_followed

        logger.info(
            "Evaluating %d AI tweets (%d unique new authors) for auto-follow",
            len(new_author_tweets),
            len({t.get("author", "") for t in new_author_tweets}),
        )
        scores = self.evaluate_authors(new_author_tweets)
        if not scores:
            logger.warning("No author scores returned")
            return newly_followed

        logger.info("Author scores: %s", scores)

        for author, score in scores.items():
            handle = author_to_handle.get(author, author)
            if score >= 7.0:
                # already_followed guard kept as a safety net in case the DB
                # was updated concurrently between our pre-fetch and now.
                if handle in already_followed:
                    logger.info("@%s already followed (score=%.1f)", handle, score)
                    continue
                logger.info("@%s score=%.1f >= 7, attempting follow", handle, score)
                success = self.follow_author(handle)
                if success:
                    db.save_followed_account(handle)
                    newly_followed.append(handle)
            else:
                logger.info("@%s score=%.1f < 7, skipping", handle, score)

        return newly_followed
