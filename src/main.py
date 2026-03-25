from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
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

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=10,
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            file_handler,
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_crawl(limit: int) -> tuple[str, list[str]]:
    logger = logging.getLogger(__name__)

    cdp_port = int(os.getenv("CDP_PORT", "18800"))
    db_path = os.getenv("DB_PATH", "data/tweets.db")

    crawler = TwitterCrawler(cdp_port=cdp_port)
    ai_filter = AIFilter()
    db = TweetDatabase(db_path)

    logger.info("Starting crawl (limit=%d per feed)", limit)

    session_id = db.create_session()

    try:
        for_you_tweets = crawler.get_for_you_feed(limit=limit, max_tweets=limit, db=db)
        following_tweets = crawler.get_following_feed(limit=limit, max_tweets=limit, db=db)
    finally:
        crawler.close_all_managed_tabs()
    all_tweets = for_you_tweets + following_tweets

    logger.info("Crawled %d total tweets", len(all_tweets))

    # ── Optimised AI filtering ──────────────────────────────────────────
    # Look up which crawled tweets already have a classification stored in
    # the DB so we don't make redundant OpenAI API calls for them.
    # NOTE: This must happen BEFORE save_tweets, which sets is_ai_related=0
    # on all new rows and would cause every tweet to appear "already known".
    all_ids = [t["id"] for t in all_tweets if t.get("id")]
    known_classification = db.get_ai_classification(all_ids)

    saved_count = db.save_tweets(all_tweets, session_id)
    logger.info("Saved %d new tweets (deduped)", saved_count)

    new_tweets = [t for t in all_tweets if t.get("id") and t["id"] not in known_classification]
    already_ai_ids = {tid for tid, val in known_classification.items() if val}

    freshly_ai = ai_filter.filter_tweets(new_tweets)
    freshly_ai_ids = {t["id"] for t in freshly_ai}

    # Combine: freshly classified + already-known AI tweets still in this crawl
    ai_tweet_id_set = freshly_ai_ids | already_ai_ids
    ai_tweets = [t for t in all_tweets if t.get("id") in ai_tweet_id_set]

    skipped = len(all_tweets) - len(new_tweets)
    logger.info(
        "AI filter: %d new tweets classified, %d already known (skipped), "
        "%d total AI-related",
        len(new_tweets),
        skipped,
        len(ai_tweets),
    )

    ai_ids = [t["id"] for t in ai_tweets]
    db.mark_ai_related(ai_ids)

    # Auto-follow high-quality authors
    newly_followed: list[str] = []
    try:
        from src.follower.auto_follower import AutoFollower
        follower = AutoFollower(cdp_port=cdp_port)
        newly_followed = follower.run(ai_tweets, db)
    except Exception as e:
        logger.warning("Auto-follow step failed (non-fatal): %s", e)

    # Index embeddings for AI-related tweets, then backfill any missing ones —
    # both steps share a single TweetIndexer instance to avoid duplicate init cost.
    try:
        from src.search.tweet_indexer import TweetIndexer
        indexer = TweetIndexer(db)
        indexer.index_tweets(ai_tweets)
        indexer.index_missing(db)
    except Exception as e:
        logger.warning("Tweet indexing step failed (non-fatal): %s", e)

    # Semantic deduplication
    try:
        from src.search.semantic_dedup import SemanticDeduplicator
        deduplicator = SemanticDeduplicator()
        new_tweets = db.get_tweets_by_session(session_id)
        existing_tweets = db.get_tweets_with_embeddings_recent(hours=48)
        dedup_ids = deduplicator.deduplicate(new_tweets, existing_tweets)
        marked = db.batch_mark_duplicates(dedup_ids)
        logger.info("Marked %d tweets as semantic duplicates", marked)
    except Exception as e:
        logger.warning("Semantic dedup failed (non-fatal): %s", e)

    db.complete_session(
        session_id,
        total_tweets=len(all_tweets),
        ai_tweets_count=len(ai_tweets),
    )

    return session_id, newly_followed


def run_send(output_dir: str, followed: list[str] | None = None) -> str | None:
    logger = logging.getLogger(__name__)

    db_path = os.getenv("DB_PATH", "data/tweets.db")
    db = TweetDatabase(db_path)
    reporter = ReportGenerator()

    from datetime import datetime, timezone as _tz

    rows = db.get_non_duplicate_ai_tweets()

    # Compute topic clusters once and share with both generate_report and
    # send_as_card to avoid making two identical OpenAI API calls per run.
    display_rows = (rows or [])[:20]
    clustered = reporter.cluster_topics(display_rows) if display_rows else None

    # Always generate and save the markdown report as an artifact
    report_content = reporter.generate_report(rows or [], "send", clustered=clustered)
    if followed:
        report_content += f"\n\n🤝 本次新关注：{', '.join('@' + h for h in followed)}"

    filepath = reporter.save_report(report_content, output_dir)
    logger.info("Report saved: %s", filepath)

    if not rows:
        logger.info("No unsent AI tweets to report")
        # Still send an empty card so the daily run is always visible in Feishu
        generated_at = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
        reporter.send_as_card([], session_id="—", generated_at=generated_at)
        return None

    generated_at = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
    sent_via_webhook = reporter.send_as_card(
        rows,
        session_id="send",
        generated_at=generated_at,
        followed=followed,
        clustered=clustered,
    )
    if sent_via_webhook:
        logger.info("Report sent as Feishu interactive card")
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
        choices=["crawl", "report", "search", "all"],
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
        "--query",
        type=str,
        default=None,
        help="Search query (required for search mode)",
    )
    parser.add_argument(
        "--output-dir",
        default=REPORT_DIR,
        help=f"Report output directory (default: {REPORT_DIR})",
    )
    args = parser.parse_args()

    # Print config status
    api_key = os.getenv("OPENAI_API_KEY")
    cdp_port = os.getenv("CDP_PORT", "18800")
    db_path = os.getenv("DB_PATH", "data/tweets.db")
    model_name = "gpt-4o-mini"
    if api_key:
        print(f"[Config] OpenAI API: ✅ configured ({model_name})")
    else:
        print(f"[Config] OpenAI API: ⚠️ not set, using keyword fallback")
    print(f"[Config] CDP port: {cdp_port}")
    print(f"[Config] DB path: {db_path}")
    print(f"[Config] Max tweets per feed: {args.limit}")

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Twitter AI Monitor started (mode=%s)", args.mode)

    if args.mode == "search":
        if not args.query:
            print("Error: --query required for search mode")
            sys.exit(1)
        from src.search.semantic_search import SemanticSearch
        db_path_search = os.getenv("DB_PATH", "data/tweets.db")
        db = TweetDatabase(db_path_search)
        searcher = SemanticSearch(db)
        results = searcher.search(args.query, top_k=10)
        if not results:
            print("No results found.")
        else:
            print(f"\nTop {len(results)} results for: {args.query!r}\n")
            for i, t in enumerate(results, 1):
                print(f"{i}. [{t['similarity_score']:.3f}] @{t['author']}")
                print(f"   {t['text'][:200]}")
                print(f"   {t['url']}\n")
        return

    newly_followed: list[str] = []
    if args.mode in ("crawl", "all"):
        session_id, newly_followed = run_crawl(args.limit)
        logger.info("Crawl complete (session=%s)", session_id)

    if args.mode in ("report", "all"):
        filepath = run_send(args.output_dir, followed=newly_followed)
        if filepath:
            logger.info("Done. Report at: %s", filepath)

    logger.info("Twitter AI Monitor finished")


if __name__ == "__main__":
    main()
