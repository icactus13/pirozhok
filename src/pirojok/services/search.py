import logging
import os

import httpx

logger = logging.getLogger(__name__)

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")


async def web_search(query: str, num_results: int = 5) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{SEARXNG_URL}/search",
                params={"q": query, "format": "json", "language": "ru"},
                headers={"User-Agent": "Pirojok/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("SearXNG error: %s", exc)
        return f"Не получилось дойти до поиска: {exc}"

    results = data.get("results", [])[:num_results]
    if not results:
        return f"По запросу «{query}» ничего не нашлось."

    lines = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        snippet = ((r.get("content") or "").strip())[:400]
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines)


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Поиск в интернете. Используй, когда нужна свежая или фактическая "
            "информация: новости, погода, цены, события, актуальные данные, "
            "имена, даты. Не используй для болтовни, шуток, поддержки или "
            "вопросов на которые ты можешь ответить из общих знаний."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос на нужном языке",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Сколько результатов вернуть (1-10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}
