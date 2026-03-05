import json
import logging
import random
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.storage.db import TweetDatabase

logger = logging.getLogger(__name__)

EVAL_JS = """
const tweets = [];
document.querySelectorAll('article[data-testid="tweet"]').forEach(article => {
  const textEl = article.querySelector('[data-testid="tweetText"]');
  const authorEl = article.querySelector('[data-testid="User-Name"] a span');
  const timeEl = article.querySelector('time');
  const linkEl = article.querySelector('a[href*="/status/"]');
  tweets.push({
    text: textEl ? textEl.innerText : '',
    author: authorEl ? authorEl.innerText : '',
    time: timeEl ? timeEl.getAttribute('datetime') : '',
    url: linkEl ? 'https://x.com' + linkEl.getAttribute('href') : ''
  });
});
JSON.stringify(tweets)
"""

THREAD_EVAL_JS = """
const tweets = [];
document.querySelectorAll('article[data-testid="tweet"]').forEach(article => {
  const textEl = article.querySelector('[data-testid="tweetText"]');
  const authorEl = article.querySelector('[data-testid="User-Name"] a span');
  const timeEl = article.querySelector('time');
  const linkEl = article.querySelector('a[href*="/status/"]');
  tweets.push({
    text: textEl ? textEl.innerText : '',
    author: authorEl ? authorEl.innerText : '',
    time: timeEl ? timeEl.getAttribute('datetime') : '',
    url: linkEl ? 'https://x.com' + linkEl.getAttribute('href') : ''
  });
});
JSON.stringify(tweets)
"""

SCROLL_JS = "window.scrollBy(0, window.innerHeight * 2); true"


@dataclass(frozen=True)
class Tweet:
    """Backwards-compatible Tweet dataclass."""
    id: str
    text: str
    author: str
    url: str
    timestamp: str
    likes: int
    retweets: int
    feed_type: str

class TwitterCrawler:
    def __init__(self, cdp_port: int = 18800, full_text_mode: bool = True,
                 full_text_concurrency: int = 3, full_text_max: int = 30):
        self.cdp_port = cdp_port
        self.full_text_mode = full_text_mode
        self.full_text_concurrency = full_text_concurrency
        self.full_text_max = full_text_max
        self._full_text_count = 0

    def _run_browser_command(self, *args: str) -> str:
        cmd = ["agent-browser", "--cdp", str(self.cdp_port), *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Browser command timed out: {' '.join(cmd)}") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"Browser command failed (exit {result.returncode}): {result.stderr}"
            )

        return result.stdout

    def _is_truncated(self, text: str) -> bool:
        stripped = text.rstrip()
        return stripped.endswith("\u2026") or stripped.endswith("...")

    def _fetch_full_text(self, tweet_url: str) -> str:
        if self._full_text_count >= self.full_text_max:
            logger.info("Full-text max (%d) reached, skipping detail page for %s", self.full_text_max, tweet_url)
            return ""
        try:
            self._run_browser_command("open", tweet_url)
            time.sleep(2)
            js = """
const art = document.querySelector('article[data-testid="tweet"]');
const el = art ? art.querySelector('[data-testid="tweetText"]') : null;
JSON.stringify(el ? el.innerText : '')
"""
            raw = self._run_browser_command("eval", js)
            data = json.loads(raw)
            if isinstance(data, str):
                data = json.loads(data)
            result = data if isinstance(data, str) else ""
            if result:
                self._full_text_count += 1
                time.sleep(random.uniform(1.5, 3.0))
            return result
        except Exception as e:
            logger.warning("Failed to fetch full text for %s: %s", tweet_url, e)
            return ""

    def _fetch_thread_tweets(self, tweet_url: str, feed_type: str) -> List[Dict[str, Any]]:
        try:
            self._run_browser_command("open", tweet_url)
            time.sleep(2)
            raw = self._run_browser_command("eval", THREAD_EVAL_JS)
            thread_items = self._parse_tweets_from_eval(raw, "thread")
            if not thread_items:
                return []
            root_id = thread_items[0]["id"]
            for item in thread_items:
                item["thread_root_id"] = root_id
            return thread_items
        except Exception as e:
            logger.warning("Failed to fetch thread for %s: %s", tweet_url, e)
            return []

    def get_for_you_feed(
        self, limit: int = 50, max_tweets: int = 500, db: Optional["TweetDatabase"] = None,
    ) -> List[Dict[str, Any]]:
        return self._get_feed("https://twitter.com/home", "for_you", limit, max_tweets=max_tweets, db=db)

    def get_following_feed(
        self, limit: int = 50, max_tweets: int = 500, db: Optional["TweetDatabase"] = None,
    ) -> List[Dict[str, Any]]:
        return self._get_feed("https://twitter.com/following", "following", limit, max_tweets=max_tweets, db=db)

    def _get_feed(
        self,
        url: str,
        feed_type: str,
        limit: int,
        max_tweets: int = 500,
        db: Optional["TweetDatabase"] = None,
    ) -> List[Dict[str, Any]]:
        try:
            self._run_browser_command("navigate", url)
            time.sleep(2)

            # Login state detection
            login_check_deadline = time.time() + 5
            while True:
                eval_result = self._run_browser_command("eval", "JSON.stringify(document.querySelectorAll('article[data-testid=\"tweet\"]').length)")
                tweet_count = int(json.loads(eval_result.strip()))

                if tweet_count > 0:
                    break

                current_url = self._run_browser_command("eval", "JSON.stringify(window.location.href)")
                current_url = json.loads(current_url.strip())

                if "/login" in current_url or "i/flow/login" in current_url:
                    raise RuntimeError("Twitter session expired, please re-login")

                if time.time() >= login_check_deadline:
                    break

                time.sleep(0.5)

            existing_ids: set[str] = db.get_all_tweet_ids() if db else set()
            last_crawl_start: Optional[str] = db.get_last_crawl_start() if db else None

            all_tweets: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            window: deque[int] = deque(maxlen=10)
            consecutive_no_new = 0
            stop_reason: Optional[str] = None

            while True:
                raw = self._run_browser_command("eval", EVAL_JS)
                page_tweets = self._parse_tweets_from_eval(raw, feed_type)

                new_this_round = 0
                for tweet in page_tweets:
                    tweet_id = tweet["id"]
                    if not tweet_id or tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)
                    new_this_round += 1

                    is_dup = tweet_id in existing_ids
                    window.append(1 if is_dup else 0)
                    all_tweets.append(tweet)

                    if self.full_text_mode and self._is_truncated(tweet["text"]):
                        thread = self._fetch_thread_tweets(tweet["url"], feed_type)
                        if thread:
                            tweet["text"] = thread[0]["text"]
                            for t in thread[1:]:
                                if t["id"] and t["id"] not in seen_ids:
                                    seen_ids.add(t["id"])
                                    all_tweets.append(t)

                    if len(all_tweets) >= max_tweets:
                        stop_reason = "max_tweets"
                        break

                    if last_crawl_start and tweet.get("timestamp"):
                        if tweet["timestamp"] < last_crawl_start:
                            stop_reason = "timestamp"
                            break

                    if len(window) == 10 and sum(window) >= 8:
                        stop_reason = "duplicate_window"
                        break

                if stop_reason:
                    break

                if new_this_round == 0:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
                        stop_reason = "no_new_content"
                        break
                else:
                    consecutive_no_new = 0

                if len(all_tweets) >= limit:
                    stop_reason = "limit"
                    break

                self._run_browser_command("eval", SCROLL_JS)
                time.sleep(1.5)

            logger.info(
                "Fetched %d tweets from %s feed (stop_reason=%s)",
                len(all_tweets), feed_type, stop_reason,
            )
            logger.info("Full-text fetches this session: %d", self._full_text_count)
            return all_tweets[:limit]

        except RuntimeError:
            logger.error("Failed to fetch %s feed", feed_type)
            return []

    def _parse_tweets_from_eval(
        self, raw: str, feed_type: str,
    ) -> List[Dict[str, Any]]:
        data = json.loads(raw)
        # Handle double-encoding: if json.loads returns a string, decode again
        if isinstance(data, str):
            data = json.loads(data)

        tweets: List[Dict[str, Any]] = []
        for item in data:
            url = item.get("url", "")
            text = item.get("text", "")
            if not url or not text:
                continue

            tweet_id = ""
            if "/status/" in url:
                tweet_id = url.split("/status/")[-1].split("/")[0]

            tweets.append({
                "id": tweet_id,
                "text": text,
                "author": item.get("author", ""),
                "url": url,
                "timestamp": item.get("time", ""),
                "likes": 0,
                "retweets": 0,
                "feed_type": feed_type,
            })

        return tweets
