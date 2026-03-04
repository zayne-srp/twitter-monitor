import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


AI_KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning',
    'neural network', 'LLM', 'GPT', 'ChatGPT', 'Claude', 'Gemini',
    'transformer', 'diffusion', 'generative AI', 'AGI', 'NLP',
    'computer vision', 'reinforcement learning', 'fine-tuning',
    'foundation model', 'language model', 'OpenAI', 'Anthropic',
    'Hugging Face', 'model', 'dataset', 'inference', 'training',
    'benchmark', 'alignment', 'RLHF', 'multimodal', 'embedding',
    'vector', 'RAG', 'agent', 'automation', 'robot',
]


class AIFilter:
    def __init__(self):
        self.api_key = os.environ.get('OPENAI_API_KEY')
        self.use_openai = bool(self.api_key)
        if self.use_openai:
            if not _OPENAI_AVAILABLE:
                logger.warning("openai package not installed, falling back to keyword matching")
                self.use_openai = False
            else:
                self.client = OpenAI(api_key=self.api_key)
                logger.info("AIFilter: using OpenAI gpt-4o-mini")
        else:
            logger.info("AIFilter: OPENAI_API_KEY not set, using keyword matching fallback")

    def filter_tweets(self, tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter tweets, keeping only AI-related ones."""
        if not tweets:
            return []

        if self.use_openai:
            return self._filter_with_openai(tweets)
        else:
            return self._filter_with_keywords(tweets)

    def _filter_with_openai(self, tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use OpenAI to filter tweets in batches of 20."""
        batch_size = 20
        results = []

        for i in range(0, len(tweets), batch_size):
            batch = tweets[i:i + batch_size]
            try:
                kept = self._classify_batch(batch)
                results.extend(kept)
            except Exception as e:
                logger.error(f"OpenAI API error: {e}, falling back to keywords for this batch")
                results.extend(self._filter_with_keywords(batch))

        return results

    def _classify_batch(self, tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Classify a batch of tweets with OpenAI."""
        texts = [t.get('text', '') for t in tweets]
        numbered = '\n'.join(f"{idx + 1}. {text}" for idx, text in enumerate(texts))

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI content filter. For each tweet, determine if it's related to "
                        "AI/ML/LLM technology topics. Return a JSON array of booleans, one per tweet, "
                        "in the same order. Only mark as true if the tweet is genuinely about AI technology "
                        "(models, tools, research, industry news, etc.). "
                        "Not about general 'agent' usage unrelated to AI. "
                        "Return ONLY a JSON array like [true, false, true, ...]"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Classify these {len(tweets)} tweets:\n{numbered}",
                },
            ],
            temperature=0,
            max_tokens=200,
        )

        content = response.choices[0].message.content.strip()
        # Extract JSON array from response
        if '[' in content:
            content = content[content.index('['):content.rindex(']') + 1]
        decisions = json.loads(content)

        return [tweet for tweet, keep in zip(tweets, decisions) if keep]

    def _filter_with_keywords(self, tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fallback: filter tweets by keyword matching."""
        filtered = []
        for tweet in tweets:
            text = tweet.get('text', '').lower()
            if any(kw.lower() in text for kw in AI_KEYWORDS):
                filtered.append(tweet)
        return filtered

    def is_ai_related(self, tweet: Dict[str, Any]) -> bool:
        """Check if a single tweet is AI-related."""
        result = self.filter_tweets([tweet])
        return len(result) > 0
