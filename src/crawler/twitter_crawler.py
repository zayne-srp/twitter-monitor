import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tweet:
    id: str
    text: str
    author: str
    url: str
    timestamp: str
    likes: int
    retweets: int
    feed_type: str  # "for_you" or "following"


class TwitterCrawler:
    def __init__(self, cdp_port: int = 18800):
        self.cdp_port = cdp_port

    def _run_browser_command(self, *args: str) -> dict:
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

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw_output": result.stdout}

    def get_for_you_feed(self, limit: int = 50) -> List[Tweet]:
        return self._get_feed("https://twitter.com/home", "for_you", limit)

    def get_following_feed(self, limit: int = 50) -> List[Tweet]:
        return self._get_feed(
            "https://twitter.com/following", "following", limit,
        )

    def _get_feed(self, url: str, feed_type: str, limit: int) -> List[Tweet]:
        try:
            self._run_browser_command("navigate", url)
            time.sleep(2)
            snapshot = self._run_browser_command("snapshot", "-i", "--json")
            tweets = self._parse_tweets_from_snapshot(snapshot, feed_type)
            logger.info(
                "Fetched %d tweets from %s feed", len(tweets), feed_type,
            )
            return tweets[:limit]
        except RuntimeError:
            logger.error("Failed to fetch %s feed", feed_type)
            return []

    def _parse_tweets_from_snapshot(
        self, snapshot: dict, feed_type: str,
    ) -> List[Tweet]:
        raw_tweets = snapshot.get("tweets", [])
        parsed: List[Tweet] = []

        for raw in raw_tweets:
            tweet_id = raw.get("id")
            if not tweet_id:
                logger.warning("Skipping tweet without ID: %s", raw)
                continue

            tweet = Tweet(
                id=str(tweet_id),
                text=raw.get("text", ""),
                author=raw.get("author", "unknown"),
                url=raw.get("url", f"https://twitter.com/i/status/{tweet_id}"),
                timestamp=raw.get("timestamp", ""),
                likes=int(raw.get("likes", 0)),
                retweets=int(raw.get("retweets", 0)),
                feed_type=feed_type,
            )
            parsed.append(tweet)

        return parsed
