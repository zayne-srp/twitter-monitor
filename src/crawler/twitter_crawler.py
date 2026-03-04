import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List

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

    def get_for_you_feed(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._get_feed("https://twitter.com/home", "for_you", limit)

    def get_following_feed(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._get_feed(
            "https://twitter.com/following", "following", limit,
        )

    def _get_feed(
        self, url: str, feed_type: str, limit: int,
    ) -> List[Dict[str, Any]]:
        try:
            self._run_browser_command("navigate", url)
            time.sleep(2)
            raw = self._run_browser_command("eval", EVAL_JS)
            tweets = self._parse_tweets_from_eval(raw, feed_type)
            logger.info(
                "Fetched %d tweets from %s feed", len(tweets), feed_type,
            )
            return tweets[:limit]
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
