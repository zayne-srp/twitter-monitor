# BDD Tests

## Overview

BDD tests using [behave](https://behave.readthedocs.io/) for the Twitter AI Monitor project.

## Features

| Feature File | Scenarios | Description |
|---|---|---|
| `crawler.feature` | 3 | Basic crawler behavior: truncation detection, JSON parsing |
| `full_text.feature` | 5 | Full text fetching: normal, truncated, error fallback, rate limit, random delay |
| `thread.feature` | 3 | Thread crawling: single tweet, multi-tweet thread, dedup on save |
| `db.feature` | 3 | Database storage: normal save, thread_root_id, duplicate rejection |
| `follower.feature` | 3 | Auto-follow idempotency: confirm success, confirm failure, skip already followed |
| `filter.feature` | 3 | Pre-filter noise: retweets, short links, empty texts |
| `search.feature` | 2 | Embedding compensation: missing embeddings, API retry/skip |
| `reporter.feature` | 4 | Report generation: author aggregation, topic clustering, fallback |
| `dedup.feature` | 4 | Semantic dedup: high similarity marked, low similarity kept, no-embedding skipped, report excludes duplicates |

## Running

```bash
cd /Users/openclaw/source/twitter-monitor
venv/bin/behave
```

## Test Strategy

- **Browser commands** are mocked via `unittest.mock.patch` on `TwitterCrawler._run_browser_command` — no real browser needed.
- **Database** uses real SQLite with temporary files (`tempfile.mktemp(suffix='.db')`), cleaned up after each scenario.
- Mock responses use double-encoded JSON to match the real `agent-browser eval` output format.

## Directory Structure

```
features/
  crawler.feature
  full_text.feature
  thread.feature
  db.feature
  follower.feature
  filter.feature
  search.feature
  reporter.feature
  dedup.feature
  steps/
    crawler_steps.py
    full_text_steps.py
    thread_steps.py
    db_steps.py
    follower_steps.py
    filter_steps.py
    search_steps.py
    reporter_steps.py
    dedup_steps.py
```
