# BDD Tests

## Overview

BDD tests using [behave](https://behave.readthedocs.io/) for the Twitter AI Monitor project.

## Features

| Feature File | Scenarios | Description |
|---|---|---|
| `crawler.feature` | 3 | Basic crawler behavior: truncation detection, JSON parsing |
| `full_text.feature` | 3 | Full text fetching: normal tweets, truncated tweets, error fallback |
| `thread.feature` | 3 | Thread crawling: single tweet, multi-tweet thread, dedup on save |
| `db.feature` | 3 | Database storage: normal save, thread_root_id, duplicate rejection |

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
  steps/
    crawler_steps.py
    full_text_steps.py
    thread_steps.py
    db_steps.py
```
