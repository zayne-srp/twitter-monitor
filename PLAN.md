# Twitter AI Monitor - Implementation Plan

## Overview

This project crawls Twitter feeds using `agent-browser` CLI (via subprocess), filters for AI-related content, stores tweets in SQLite with deduplication, and generates categorized markdown reports.

## Twitter Page Structure & Selectors

### Login Flow
1. Navigate to `https://twitter.com/i/flow/login`
2. Fill username field: `input[autocomplete="username"]`
3. Click "Next" button
4. Fill password field: `input[name="password"]`
5. Click "Log in" button
6. Wait for redirect to home timeline

### Feed URLs
- **For You feed**: `https://twitter.com/home` (default tab)
- **Following feed**: `https://twitter.com/home?tab=following` (or click "Following" tab)

### Tweet Selectors
| Element | Selector | Description |
|---------|----------|-------------|
| Tweet container | `article[data-testid="tweet"]` | Each tweet is an article element |
| Tweet text | `div[data-testid="tweetText"]` | The body text of the tweet |
| Author name | `div[data-testid="User-Name"]` | Contains display name and @handle |
| Timestamp | `time[datetime]` | ISO datetime in `datetime` attribute |
| Tweet link | `a[href*="/status/"]` | Link containing tweet ID |
| Like count | `div[data-testid="like"]` | Like button area |
| Retweet count | `div[data-testid="retweet"]` | Retweet button area |
| Engagement text | `span[aria-label]` | Aria labels contain engagement counts |

### Scrolling Strategy
- Use `agent-browser act --action "scroll" --ref <page-ref>` to scroll down
- Capture snapshots after each scroll to collect more tweets
- Continue until reaching desired tweet count or max scroll attempts

## Module Design

### 1. TwitterCrawler (`src/crawler/twitter_crawler.py`)

**Class**: `TwitterCrawler`

**Data Structure**:
```python
@dataclass(frozen=True)
class Tweet:
    id: str            # Extracted from /status/<id> URL
    text: str          # Tweet body text
    author: str        # @handle
    url: str           # Full tweet URL
    timestamp: str     # ISO format datetime
    likes: int         # Like count
    retweets: int      # Retweet count
    feed_type: str     # "for_you" or "following"
```

**Methods**:
- `login(username, password) -> bool` - Automate Twitter login via agent-browser
- `get_for_you_feed(limit=50) -> List[Tweet]` - Crawl For You timeline
- `get_following_feed(limit=50) -> List[Tweet]` - Crawl Following timeline
- `_run_browser_command(*args) -> dict` - Execute agent-browser subprocess
- `_parse_tweets_from_snapshot(snapshot, feed_type) -> List[Tweet]` - Parse snapshot JSON

**agent-browser Commands Used**:
```bash
agent-browser --cdp 18800 navigate <url>
agent-browser --cdp 18800 snapshot -i --json
agent-browser --cdp 18800 act --action "click" --ref <ref>
agent-browser --cdp 18800 act --action "fill" --ref <ref> --value <text>
agent-browser --cdp 18800 act --action "scroll" --ref <ref>
```

### 2. AIFilter (`src/filter/ai_filter.py`)

**Keywords** (30+ terms): AI, LLM, GPT, Claude, Gemini, Grok, machine learning, deep learning, neural network, transformer, RAG, agent, diffusion, ChatGPT, OpenAI, Anthropic, Google AI, stable diffusion, midjourney, DALL-E, Sora, Mistral, Llama, DeepSeek, Qwen, fine-tuning, inference, embedding, vector database, prompt engineering, multimodal, AGI, 人工智能, 机器学习, 深度学习

**Methods**:
- `is_ai_related(tweet) -> bool` - Case-insensitive keyword matching with word boundary awareness
- `filter_tweets(tweets) -> List[Tweet]` - Filter a list, returning only AI-related tweets

### 3. TweetDatabase (`src/storage/db.py`)

**Tables**:
```sql
CREATE TABLE IF NOT EXISTS tweets (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    url TEXT NOT NULL,
    timestamp TEXT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    feed_type TEXT NOT NULL,
    crawl_session_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS crawl_sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    total_tweets INTEGER DEFAULT 0,
    ai_tweets_count INTEGER DEFAULT 0
);
```

**Methods**:
- `save_tweet(tweet, session_id) -> bool` - Insert with dedup (INSERT OR IGNORE)
- `save_tweets(tweets, session_id) -> int` - Batch insert, return count of new tweets
- `get_tweets_by_session(session_id) -> List[dict]` - Retrieve session tweets
- `create_session() -> str` - Create new crawl session
- `complete_session(session_id, total, ai_count)` - Mark session complete
- `get_recent_tweets(hours=24) -> List[dict]` - Get tweets from last N hours

### 4. ReportGenerator (`src/reporter/report_generator.py`)

**Categories**:
- Models & Research (GPT, Claude, Llama, etc.)
- Tools & Products (ChatGPT, Midjourney, etc.)
- Industry News (funding, acquisitions, launches)
- Tutorials & Technical (fine-tuning, RAG, embeddings)
- Opinion & Discussion (general AI discourse)

**Methods**:
- `generate_report(tweets, session_id) -> str` - Create markdown report
- `categorize_tweet(tweet) -> str` - Assign tweet to category
- `save_report(content, output_dir) -> str` - Write report file

### 5. Main Entry Point (`src/main.py`)

**CLI Arguments**:
- `--mode [crawl|report|all]` - Operation mode (default: all)
- `--limit N` - Max tweets per feed (default: 50)
- `--output-dir PATH` - Report output directory (default: reports/)

**Flow**:
1. Load .env configuration
2. Initialize logging to logs/
3. If crawl: login -> crawl For You -> crawl Following -> filter -> store
4. If report: load recent tweets -> generate report -> save
5. If all: crawl then report

## Test Strategy

### Unit Tests (`tests/unit/`)
- **test_crawler.py**: Mock subprocess calls, test Tweet parsing, login flow
- **test_filter.py**: Test keyword matching with various inputs
- **test_db.py**: In-memory SQLite, test CRUD and dedup
- **test_reporter.py**: Test report generation and categorization

### E2E Tests (`tests/e2e/`)
- **test_e2e.py**: Full pipeline test (requires real Twitter account)
  - Marked with `@pytest.mark.e2e` for selective execution
  - Tests login, crawl, filter, store, report pipeline

### Coverage Target
- 80%+ line coverage on unit tests
- All error paths tested (login failure, empty feeds, browser timeout)

## Error Handling Strategy

| Scenario | Handling |
|----------|----------|
| Browser not running | Log error, raise RuntimeError |
| Login failure | Retry once, then log and abort |
| Empty feed | Log warning, return empty list |
| Network timeout | Subprocess timeout (30s), log error |
| Duplicate tweet | INSERT OR IGNORE, count skipped |
| Invalid tweet data | Skip tweet, log warning |
| Report generation failure | Log error, return partial report |

## Security Considerations

- Credentials loaded from .env (never hardcoded)
- .env in .gitignore
- Database files in .gitignore
- No credentials in log output
- Subprocess calls use list args (no shell injection)
