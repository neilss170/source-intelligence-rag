import re
from dataclasses import dataclass

import httpx

from app.models.query import WebSource

LIVE_TERMS = {
    "available",
    "availability",
    "buy",
    "current",
    "latest",
    "link",
    "links",
    "model",
    "models",
    "news",
    "price",
    "prices",
    "product",
    "products",
    "recommend",
    "recommendation",
    "recommendations",
    "today",
    "website",
    "websites",
}


@dataclass(frozen=True, slots=True)
class WebSearchAnswer:
    answer: str
    sources: list[WebSource]


def needs_live_search(question: str) -> bool:
    terms = set(re.findall(r"[a-z]+", question.lower()))
    return bool(terms & LIVE_TERMS) or "near me" in question.lower()


class TavilySearchProvider:
    def __init__(
        self,
        api_key: str | None,
        *,
        country: str = "india",
        max_results: int = 3,
    ) -> None:
        self._api_key = api_key
        self._country = country
        self._max_results = max_results

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def search(self, question: str) -> WebSearchAnswer | None:
        if not self._api_key:
            return None
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(
                    "https://api.tavily.com/search",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": question,
                        "search_depth": "basic",
                        "include_answer": "basic",
                        "include_raw_content": False,
                        "max_results": self._max_results,
                        "country": self._country,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        sources = [
            WebSource(
                title=item.get("title") or "Web source",
                url=item.get("url") or "",
                excerpt=_compact(item.get("content") or "", 220),
            )
            for item in payload.get("results", [])[: self._max_results]
            if item.get("url")
        ]
        answer = _compact(payload.get("answer") or "", 900)
        if not answer or not sources:
            return None
        return WebSearchAnswer(
            answer=(
                f"{answer}\n\nChecked live web results. Prices and availability "
                "can change, so confirm them on the linked page before buying."
            ),
            sources=sources,
        )


def _compact(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rsplit(" ", 1)[0] + "..."
