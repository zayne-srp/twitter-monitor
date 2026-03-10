# Twitter AI Monitor

Automated Twitter AI content crawler that monitors AI-related tweets from your timeline, filters them by relevance, stores them with deduplication, and generates daily reports.

## Features

- Crawls "For You" and "Following" Twitter feeds via agent-browser
- Filters tweets using 30+ AI-related keywords (English & Chinese)
- SQLite storage with deduplication by tweet ID
- Markdown report generation categorized by topic
- Scheduled daily execution at 10:00 AM (Asia/Shanghai)
- Feishu webhook integration for report delivery

## Prerequisites

- Python 3.10+
- [agent-browser](https://github.com/anthropics/agent-browser) CLI installed and accessible
- A Chrome/Chromium browser running with CDP enabled on port 18800
- openclaw browser running with CDP enabled on port 18800, already logged in to Twitter

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd twitter-monitor

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings (no Twitter credentials needed — uses openclaw browser session)
```

## Configuration

Edit `.env` with your settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `FEISHU_WEBHOOK_URL` | Feishu bot webhook URL | (optional) |
| `CDP_PORT` | Chrome DevTools Protocol port | `18800` |
| `DB_PATH` | SQLite database file path | `data/tweets.db` |
| `CRAWL_LIMIT` | Max tweets to fetch per feed | `50` |

## Usage

### Manual Run

```bash
# Run full pipeline (crawl + report)
./run_crawler.sh

# Or run specific modes
source .venv/bin/activate
python -m src.main --mode crawl          # Crawl only
python -m src.main --mode report         # Report only
python -m src.main --mode all            # Full pipeline
python -m src.main --mode all --limit 100  # Custom limit
python -m src.main --output-dir ./my-reports  # Custom output directory
```

### Cron Job Setup (Daily at 10:00 AM Asia/Shanghai)

```bash
# Edit crontab
crontab -e

# Add this line (adjust path as needed)
0 10 * * * cd /path/to/twitter-monitor && ./run_crawler.sh >> logs/cron.log 2>&1
```

> Note: The cron time is in your system timezone. If your system is set to
> Asia/Shanghai, use `0 10 * * *`. Adjust if your system uses a different timezone.

## Project Structure

```
twitter-monitor/
├── src/
│   ├── crawler/twitter_crawler.py   # Browser automation via agent-browser
│   ├── filter/ai_filter.py          # AI keyword filtering
│   ├── storage/db.py                # SQLite persistence & dedup
│   ├── reporter/report_generator.py # Markdown report generation
│   └── main.py                      # CLI entry point
├── tests/
│   ├── unit/                        # Unit tests
│   └── e2e/                         # End-to-end tests
├── logs/                            # Application logs
├── reports/                         # Generated reports
├── .env.example                     # Environment template
├── requirements.txt                 # Python dependencies
└── run_crawler.sh                   # Runner script
```

## Running Tests

```bash
source .venv/bin/activate
pip install pytest

# Unit tests
python -m pytest tests/unit/ -v

# E2E tests (requires Twitter account and running browser)
python -m pytest tests/e2e/ -v
```

## License

MIT
