"""
orchestrator/services/fresh_data_retriever.py
================================================
Fresh Data Retriever.
Retrieves real-time/fresh web search results for the Fresh Data route.
"""

from typing import Optional
import datetime

from orchestrator.models.context_models import RetrievedChunk
from orchestrator.services.retrieval_interface import RetrievalInterface
from orchestrator.services.observability import get_logger

logger = get_logger(__name__)


class FreshDataRetriever(RetrievalInterface):
    """
    Mock/Stub Fresh Data Retriever.
    Simulates calling an external web search or news search API.
    """

    async def search(
        self,
        query: str,
        query_vector: Optional[list[float]] = None,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[RetrievedChunk]:
        """Simulate a web search engine query and return relevance ranked snippets."""
        logger.info("fresh_data_search_triggered", query=query[:60])
        
        # Determine current year dynamically
        current_year = datetime.datetime.now().year
        
        # Simple simulated database of search results
        mock_web_db = [
            {
                "query_keywords": ["ceo", "google", "sundar", "pichai"],
                "title": "Alphabet/Google Leadership Update",
                "text": f"As of {current_year}, Sundar Pichai continues to serve as the CEO of both Alphabet Inc. and its subsidiary Google. He was appointed CEO of Google in 2015 and CEO of Alphabet in 2019.",
                "url": "https://www.google.com/about/our-company/",
                "recency": "1 day ago"
            },
            {
                "query_keywords": ["weather", "temperature", "forecast"],
                "title": "Global Weather Monitoring Service",
                "text": "Weather patterns show a localized high-pressure system causing warmer than average temperatures across the central plains this week, with light scattered showers expected towards the weekend.",
                "url": "https://weather.com/news",
                "recency": "2 hours ago"
            },
            {
                "query_keywords": ["news", "latest", "stock", "market"],
                "title": "Financial Market Summary Today",
                "text": "Stock markets show moderate gains today as tech equities rebound following solid earnings reports. Central banks hint at steady interest rates for the upcoming quarter.",
                "url": "https://bloomberg.com/markets",
                "recency": "30 minutes ago"
            }
        ]
        
        results = []
        q_lower = query.lower()
        
        # Find matching mock pages
        matched_items = []
        for item in mock_web_db:
            if any(kw in q_lower for kw in item["query_keywords"]):
                matched_items.append(item)
                
        # If no specific matches, return a generic search result
        if not matched_items:
            matched_items.append({
                "title": f"Web Search: {query[:30]}",
                "text": f"Live search results for '{query}' as of {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC. The query indicates a request for fresh information.",
                "url": "https://search.wise-rag.io/search",
                "recency": "Just now"
            })
            
        for i, item in enumerate(matched_items[:top_k]):
            results.append(RetrievedChunk(
                id=f"web-search-{i}",
                text=f"[{item['title']}] {item['text']} (Source: {item['url']}, Published: {item['recency']})",
                score=0.90 - (i * 0.05),
                source="web_search",
                metadata={
                    "title": item["title"],
                    "url": item["url"],
                    "recency": item["recency"],
                    "retrieved_at": datetime.datetime.utcnow().isoformat()
                }
            ))
            
        return results

    async def health_check(self) -> bool:
        return True
