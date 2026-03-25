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
(function() {
  function parseCount(el) {
    if (!el) return 0;
    var text = el.innerText ? el.innerText.trim() : '';
    if (!text) return 0;
    if (text.endsWith('K')) return Math.round(parseFloat(text) * 1000);
    if (text.endsWith('M')) return Math.round(parseFloat(text) * 1000000);
    return parseInt(text.replace(/,/g, ''), 10) || 0;
  }
  var tweets = [];
  document.querySelectorAll('article[data-testid="tweet"]').forEach(function(article) {
    var textEl = article.querySelector('[data-testid="tweetText"]');
    var authorEl = article.querySelector('[data-testid="User-Name"] a span');
    var timeEl = article.querySelector('time');
    var linkEl = article.querySelector('a[href*="/status/"]');
    var likeEl = article.querySelector('[data-testid="like"] [data-testid="app-text-transition-container"]');
    var retweetEl = article.querySelector('[data-testid="retweet"] [data-testid="app-text-transition-container"]');
    tweets.push({
      text: textEl ? textEl.innerText : '',
      author: authorEl ? authorEl.innerText : '',
      time: timeEl ? timeEl.getAttribute('datetime') : '',
      url: linkEl ? 'https://x.com' + linkEl.getAttribute('href') : '',
      likes: parseCount(likeEl),
      retweets: parseCount(retweetEl)
    });
  });
  return JSON.stringify(tweets);
})()
"""

# THREAD_EVAL_JS is intentionally identical to EVAL_JS — kept as an alias so
# callers remain readable and the two can diverge independently if needed.
THREAD_EVAL_JS = EVAL_JS

SCROLL_JS = "window.scrollBy(0, window.innerHeight * 2); true"

# Browser commands that are safe to retry on transient failure.
# Destructive / side-effectful commands (e.g. "click") are NOT in this set.
_RETRYABLE_COMMANDS = frozenset({"navigate", "open", "eval", "screenshot", "tab"})

# Default retry policy for _run_browser_command
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt


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
                 full_text_concurrency: int = 3, full_text_max: int = 30,
                 max_retries: int = _DEFAULT_MAX_RETRIES,
                 retry_base_delay: float = _DEFAULT_RETRY_BASE_DELAY):
        self.cdp_port = cdp_port
        self.full_text_mode = full_text_mode
        self.full_text_concurrency = full_text_concurrency
        self.full_text_max = full_text_max
        self._full_text_count = 0
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self._managed_tab_count = 0

    def _run_browser_command(self, *args: str) -> str:
        """Execute an agent-browser CLI command and return its stdout.

        Transient failures (non-zero exit code or TimeoutExpired) are retried
        up to ``self.max_retries`` times with exponential back-off, but only
        for commands in ``_RETRYABLE_COMMANDS``.  Non-retryable commands (e.g.
        interactive clicks) are executed once and raise immediately on failure.

        Args:
            *args: Positional arguments forwarded to ``agent-browser``.

        Returns:
            stdout of the successful command invocation.

        Raises:
            RuntimeError: When the command fails after all retries are
                exhausted (or immediately for non-retryable commands).
        """
        cmd = ["agent-browser", "--cdp", str(self.cdp_port), *args]
        verb = args[0] if args else ""
        retryable = verb in _RETRYABLE_COMMANDS
        attempts = self.max_retries if retryable else 1

        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                last_error = exc
                err_msg = f"Browser command timed out: {' '.join(cmd)}"
                if attempt < attempts:
                    delay = self.retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s (attempt %d/%d), retrying in %.1fs",
                        err_msg, attempt, attempts, delay,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(err_msg) from exc

            if result.returncode != 0:
                err_msg = (
                    f"Browser command failed (exit {result.returncode}): "
                    f"{result.stderr}"
                )
                last_error = RuntimeError(err_msg)
                if attempt < attempts:
                    delay = self.retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s (attempt %d/%d), retrying in %.1fs",
                        err_msg, attempt, attempts, delay,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(err_msg)

            # Success
            return result.stdout

        # Should be unreachable, but satisfy the type checker.
        raise RuntimeError(f"Browser command failed after {attempts} attempts") from last_error

    # ── Tab management ────────────────────────────────────────────────
    def _open_managed_tab(self, url: str = "") -> None:
        """Open a new browser tab, optionally navigating to *url*."""
        if url:
            self._run_browser_command("tab", "new", url)
        else:
            self._run_browser_command("tab", "new")
        self._managed_tab_count += 1
        logger.debug("Opened managed tab (%d total), url=%s", self._managed_tab_count, url)

    def _close_managed_tab(self) -> None:
        """Close the current (managed) tab."""
        if self._managed_tab_count <= 0:
            return
        try:
            self._run_browser_command("tab", "close")
        except Exception as exc:
            logger.warning("Failed to close managed tab: %s", exc)
        self._managed_tab_count -= 1

    def close_all_managed_tabs(self) -> None:
        """Safety-net: close every tab this crawler opened."""
        while self._managed_tab_count > 0:
            try:
                self._run_browser_command("tab", "close")
            except Exception as exc:
                logger.warning("Failed to close managed tab: %s", exc)
            self._managed_tab_count -= 1
        logger.info("All managed tabs closed")

    def _is_truncated(self, text: str) -> bool:
        stripped = text.rstrip()
        return stripped.endswith("\u2026") or stripped.endswith("...")

    def _fetch_full_text(self, tweet_url: str) -> str:
        if self._full_text_count >= self.full_text_max:
            logger.info("Full-text max (%d) reached, skipping detail page for %s", self.full_text_max, tweet_url)
            return ""
        try:
            self._open_managed_tab(tweet_url)
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
        finally:
            self._close_managed_tab()

    def _fetch_thread_tweets(self, tweet_url: str, feed_type: str) -> List[Dict[str, Any]]:
        try:
            self._open_managed_tab(tweet_url)
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
        finally:
            self._close_managed_tab()

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
            self._open_managed_tab(url)
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

                    if last_crawl_start and tweet.get("timestamp") and feed_type == "following":
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
        finally:
            self._close_managed_tab()

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
                "likes": item.get("likes", 0),
                "retweets": item.get("retweets", 0),
                "feed_type": feed_type,
            })

        return tweets
