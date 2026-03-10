# Twitter AI Monitor - Claude Code Guide

## Project Overview
Automated Twitter AI content crawler that runs daily at 10:00 AM (Asia/Shanghai),
filters AI-related tweets, and sends reports to Feishu.

## Architecture
- src/crawler/twitter_crawler.py - Uses agent-browser CLI via subprocess
- src/filter/ai_filter.py - Keyword-based AI content filter
- src/storage/db.py - SQLite storage with dedup
- src/reporter/report_generator.py - Markdown report generation
- src/main.py - Entry point

## Key Constraints
- Use agent-browser --cdp 18800 for browser operations (NO Playwright/Selenium)
- Use project venv: .venv/
- Config via .env file (never hardcode credentials)
- Logs go to logs/ directory

## Running
./run_crawler.sh
