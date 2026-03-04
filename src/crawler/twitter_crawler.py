import json
import logging
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
    def __init__(self, cdp_port: int = 18800):
        self.cdp_port = cdp_port

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
