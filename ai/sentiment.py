"""
ai/sentiment.py
Crypto news sentiment analysis using CryptoCompare News API.
Scores news as bullish/bearish/neutral per symbol.
"""
import httpx
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger
from datetime import datetime, timezone

from config.settings import settings


# ── Keyword dictionaries ───────────────────────────────────────────────────

BULLISH_WORDS = {
    "surge", "rally", "bullish", "breakout", "pump", "moon", "buy",
    "adoption", "upgrade", "partnership", "launch", "listing", "all-time high",
    "ath", "recover", "growth", "institutional", "accumulate", "hodl", "green",
    "outperform", "upside", "gain", "milestone", "optimistic", "positive",
}

BEARISH_WORDS = {
    "crash", "dump", "bearish", "sell", "panic", "ban", "hack",
    "regulation", "lawsuit", "fraud", "rug", "scam", "liquidate",
    "downtrend", "plunge", "collapse", "red", "loss", "fear",
    "vulnerability", "exploit", "risk", "warning", "bear",
}

# Map from symbol to relevant keywords in news
SYMBOL_KEYWORDS = {
    "BTCUSDT": ["bitcoin", "btc", "bitcoin etf", "satoshi", "crypto"],
    "ETHUSDT": ["ethereum", "eth", "vitalik", "merge", "eip"],
    "SOLUSDT": ["solana", "sol", "solana defi"],
    "BNBUSDT": ["binance", "bnb", "bsc"],
    "XRPUSDT": ["ripple", "xrp"],
}


@dataclass
class NewsItem:
    title: str
    body: str
    url: str
    source: str
    published_at: int
    sentiment_score: float = 0.0   # -1.0 to 1.0
    sentiment_label: str = "neutral"  # bullish | bearish | neutral
    relevant_symbols: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at,
            "sentiment_score": round(self.sentiment_score, 3),
            "sentiment_label": self.sentiment_label,
            "relevant_symbols": self.relevant_symbols,
        }


@dataclass
class SymbolSentiment:
    symbol: str
    score: float          # -1.0 (very bearish) to 1.0 (very bullish)
    label: str            # bullish | bearish | neutral
    news_count: int
    top_headlines: List[str]

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "score": round(self.score, 3),
            "label": self.label,
            "news_count": self.news_count,
            "top_headlines": self.top_headlines[:3],
        }


class SentimentAnalyzer:
    """
    Fetches crypto news from CryptoCompare and CoinGecko,
    then computes sentiment scores per symbol using keyword analysis.
    """

    CC_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"
    CG_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"

    def __init__(self):
        self.api_key = settings.cryptocompare_api_key
        self._cache: Dict[str, SymbolSentiment] = {}
        self._news_cache: List[NewsItem] = []

    def _keyword_sentiment(self, text: str) -> float:
        """Score text using keyword matching. Returns -1.0 to 1.0."""
        text_lower = text.lower()
        bullish_hits = sum(1 for w in BULLISH_WORDS if w in text_lower)
        bearish_hits = sum(1 for w in BEARISH_WORDS if w in text_lower)
        total = bullish_hits + bearish_hits
        if total == 0:
            return 0.0
        return (bullish_hits - bearish_hits) / total

    def _find_relevant_symbols(self, text: str) -> List[str]:
        """Find which symbols are mentioned in the text."""
        text_lower = text.lower()
        relevant = []
        for symbol, keywords in SYMBOL_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                relevant.append(symbol)
        return relevant

    async def fetch_news(self, limit: int = 50) -> List[NewsItem]:
        """Fetch latest crypto news from CryptoCompare."""
        headers = {}
        if self.api_key:
            headers["authorization"] = f"Apikey {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.CC_NEWS_URL,
                    params={"lang": "EN", "limit": limit, "sortOrder": "latest"},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                articles = data.get("Data", [])

        except Exception as e:
            logger.warning(f"CryptoCompare fetch failed: {e}. Using CoinGecko fallback.")
            articles = []

        # Also try CoinGecko trending (no API key needed)
        trending = await self._fetch_coingecko_trending()

        news_items = []
        for a in articles:
            text = f"{a.get('title', '')} {a.get('body', '')}"
            score = self._keyword_sentiment(text)
            label = "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral"
            news_items.append(NewsItem(
                title=a.get("title", ""),
                body=a.get("body", "")[:300],
                url=a.get("url", ""),
                source=a.get("source", ""),
                published_at=a.get("published_on", 0),
                sentiment_score=score,
                sentiment_label=label,
                relevant_symbols=self._find_relevant_symbols(text),
            ))

        news_items.extend(trending)
        self._news_cache = news_items
        logger.info(f"Fetched {len(news_items)} news items")
        return news_items

    async def _fetch_coingecko_trending(self) -> List[NewsItem]:
        """Fetch trending coins from CoinGecko as bullish signals."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.CG_TRENDING_URL)
                resp.raise_for_status()
                data = resp.json()

            trending_items = []
            for coin in data.get("coins", [])[:7]:
                c = coin.get("item", {})
                name = c.get("name", "")
                symbol = c.get("symbol", "").upper()
                title = f"🔥 Trending: {name} ({symbol}) is top trending on CoinGecko"

                news_items = [
                    NewsItem(
                        title=title,
                        body=title,
                        url="https://coingecko.com",
                        source="CoinGecko Trending",
                        published_at=int(datetime.now(timezone.utc).timestamp()),
                        sentiment_score=0.4,  # Trending = mildly bullish
                        sentiment_label="bullish",
                        relevant_symbols=self._find_relevant_symbols(name + " " + symbol),
                    )
                ]
                trending_items.extend(news_items)
            return trending_items

        except Exception as e:
            logger.warning(f"CoinGecko trending fetch failed: {e}")
            return []

    async def get_symbol_sentiment(self, symbol: str) -> SymbolSentiment:
        """Get aggregated sentiment for a specific symbol."""
        if not self._news_cache:
            await self.fetch_news()

        relevant = [n for n in self._news_cache if symbol in n.relevant_symbols]

        if not relevant:
            return SymbolSentiment(
                symbol=symbol, score=0.0, label="neutral",
                news_count=0, top_headlines=[]
            )

        avg_score = sum(n.sentiment_score for n in relevant) / len(relevant)
        label = "bullish" if avg_score > 0.15 else "bearish" if avg_score < -0.15 else "neutral"

        return SymbolSentiment(
            symbol=symbol,
            score=avg_score,
            label=label,
            news_count=len(relevant),
            top_headlines=[n.title for n in relevant[:5]],
        )

    async def get_all_sentiments(self) -> Dict[str, SymbolSentiment]:
        """Get sentiment for all configured symbols."""
        await self.fetch_news()
        result = {}
        for sym in settings.symbols:
            result[sym] = await self.get_symbol_sentiment(sym)
        return result

    def get_cached_news(self) -> List[dict]:
        """Return cached news as dicts for API response."""
        return [n.to_dict() for n in self._news_cache[:30]]


# Singleton
_analyzer: Optional[SentimentAnalyzer] = None


def get_sentiment_analyzer() -> SentimentAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentAnalyzer()
    return _analyzer
