import re
from typing import List

from src.crawler.twitter_crawler import Tweet

AI_KEYWORDS = [
    "AI", "人工智能", "LLM", "GPT", "Claude", "Gemini", "Grok",
    "机器学习", "深度学习", "neural network", "transformer", "RAG",
    "agent", "diffusion", "ChatGPT", "OpenAI", "Anthropic", "Google AI",
    "machine learning", "deep learning", "large language model",
    "stable diffusion", "midjourney", "DALL-E", "Sora", "Mistral",
    "Llama", "DeepSeek", "Qwen", "fine-tuning", "inference", "embedding",
    "vector database", "prompt engineering", "multimodal", "AGI",
]

# Build a compiled regex pattern for efficient matching.
# Uses word boundary for short English keywords to reduce false positives.
# Chinese keywords are matched as plain substrings (no word boundary needed).
_PATTERNS: List[re.Pattern[str]] = []
for _kw in AI_KEYWORDS:
    if re.search(r"[\u4e00-\u9fff]", _kw):
        # Chinese keyword: plain substring match
        _PATTERNS.append(re.compile(re.escape(_kw), re.IGNORECASE))
    elif len(_kw) <= 3:
        # Short English keyword: require word boundary to avoid false positives
        _PATTERNS.append(re.compile(rf"\b{re.escape(_kw)}\b", re.IGNORECASE))
    else:
        # Longer English keyword: case-insensitive substring
        _PATTERNS.append(re.compile(re.escape(_kw), re.IGNORECASE))


class AIFilter:
    def is_ai_related(self, tweet: Tweet) -> bool:
        text = tweet.text
        if not text:
            return False
        return any(pattern.search(text) for pattern in _PATTERNS)

    def filter_tweets(self, tweets: List[Tweet]) -> List[Tweet]:
        return [t for t in tweets if self.is_ai_related(t)]
