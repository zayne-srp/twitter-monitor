from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.crawler.twitter_crawler import TwitterCrawler
from src.filter.ai_filter import AIFilter
from src.reporter.report_generator import ReportGenerator
from src.storage.db import TweetDatabase

load_dotenv()

LOG_DIR = "logs"
REPORT_DIR = "reports"


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"crawler_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_crawl(limit: int) -> str:
    logger = logging.getLogger(__name__)

    cdp_port = int(os.getenv("CDP_PORT", "18800"))
    db_path = os.getenv("DB_PATH", "data/tweets.db")

    crawler = TwitterCrawler(cdp_port=cdp_port)
    ai_filter = AIFilter()
    db = TweetDatabase(db_path)

    logger.info("Starting crawl (limit=%d per feed)", limit)

    session_id = db.create_session()

    for_you_tweets = crawler.get_for_you_feed(limit=limit)
    following_tweets = crawler.get_following_feed(limit=limit)
    all_tweets = for_you_tweets + following_tweets

    logger.info("Crawled %d total tweets", len(all_tweets))

    saved_count = db.save_tweets(all_tweets, session_id)
    logger.info("Saved %d new tweets (deduped)", saved_count)

    ai_tweets = ai_filter.filter_tweets(all_tweets)
    logger.info("Filtered to %d AI-related tweets", len(ai_tweets))

    ai_ids = [t.id for t in ai_tweets]
    db.mark_ai_related(ai_ids)

    db.complete_session(
        session_id,
        total_tweets=len(all_tweets),
        ai_tweets_count=len(ai_tweets),
    )

    return session_id


def run_send(output_dir: str) -> str | None:
    logger = logging.getLogger(__name__)

    db_path = os.getenv("DB_PATH", "data/tweets.db")
    db = TweetDatabase(db_path)
    reporter = ReportGenerator()

    rows = db.get_unsent_ai_tweets()
    if not rows:
        logger.info("No unsent AI tweets to report")
        return None

    from src.crawler.twitter_crawler import Tweet

    tweets = [
        Tweet(
            id=r["id"], text=r["text"], author=r["author"],
            url=r["url"], timestamp=r["timestamp"],
            likes=r["likes"], retweets=r["retweets"],
            feed_type=r["feed_type"],
        )
        for r in rows
    ]

    report_content = reporter.generate_report(tweets, "send")
    filepath = reporter.save_report(report_content, output_dir)
    logger.info("Report saved: %s", filepath)

    sent_via_webhook = reporter.send_report(report_content)
    if sent_via_webhook:
        logger.info("Report sent via Feishu webhook")
    else:
        logger.info("Report printed to stdout (no webhook configured)")

    tweet_ids = [r["id"] for r in rows]
    db.mark_sent(tweet_ids)
    logger.info("Marked %d tweets as sent", len(tweet_ids))

    return filepath


def main() -> None:
    parser = argparse.ArgumentParser(description="Twitter AI Monitor")
    parser.add_argument(
        "--mode",
        choices=["crawl", "report", "all"],
        default="all",
        help="Operation mode (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max tweets per feed (default: 50)",
    )
    parser.add_argument(
        "--output-dir",
        default=REPORT_DIR,
        help=f"Report output directory (default: {REPORT_DIR})",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Twitter AI Monitor started (mode=%s)", args.mode)

    if args.mode in ("crawl", "all"):
        session_id = run_crawl(args.limit)
        logger.info("Crawl complete (session=%s)", session_id)

    if args.mode in ("report", "all"):
        filepath = run_send(args.output_dir)
        if filepath:
            logger.info("Done. Report at: %s", filepath)

    logger.info("Twitter AI Monitor finished")


if __name__ == "__main__":
    main()
