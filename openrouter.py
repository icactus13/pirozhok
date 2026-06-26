import json
import logging
import os
from typing import Awaitable, Callable

import httpx

from search import WEB_SEARCH_TOOL, web_search
from weather import WEATHER_FORECAST_TOOL, WEATHER_TOOL, get_forecast, get_weather

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_TOOL_ITERATIONS = 4

logger = logging.getLogger(__name__)

TOOLS = [WEB_SEARCH_TOOL, WEATHER_TOOL, WEATHER_FORECAST_TOOL]
TOOL_HANDLERS = {
    "web_search": web_search,
    "weather": get_weather,
    "weather_forecast": get_forecast,
}

PreambleCb = Callable[[str], Awaitable[None]]


def format_tools_for_prompt(tools: list[dict]) -> str:
    lines = []
    for t in tools:
        fn = t["function"]
        desc = fn["description"].splitlines()[0]
        lines.append(f"- {fn['name']} — {desc}")
    return "\n".join(lines)


async def _call_tool(handlers: dict, name: str, raw_args: str) -> str:
    handler = handlers.get(name)
    if handler is None:
        return f"Неизвестный инструмент: {name}"
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Не разобрал аргументы: {exc}"
    try:
        return await handler(**args)
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return f"Инструмент {name} упал: {exc}"


async def ask_openrouter(
    model: str,
    messages: list[dict],
    extra_tools: list[dict] | None = None,
    extra_handlers: dict | None = None,
    on_preamble: PreambleCb | None = None,
    plugins: list[dict] | None = None,
) -> str:
    api_key = os.environ["OPENROUTER_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Pirojok",
    }

    tools = TOOLS + (extra_tools or [])
    handlers = {**TOOL_HANDLERS, **(extra_handlers or {})}
    conversation = list(messages)

    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": model,
                "messages": conversation,
                "tools": tools,
            }
            if plugins:
                payload["plugins"] = plugins
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            if response.status_code >= 400:
                logger.error("OpenRouter %s: %s", response.status_code, response.text[:1000])
            response.raise_for_status()
            data = response.json()
            msg = data["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                return msg.get("content") or ""

            preamble = (msg.get("content") or "").strip()
            if preamble and on_preamble:
                try:
                    await on_preamble(preamble)
                except Exception:
                    logger.exception("on_preamble callback failed")

            conversation.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc["function"]
                result = await _call_tool(handlers, fn["name"], fn.get("arguments", ""))
                logger.info("Tool %s called with %s", fn["name"], fn.get("arguments", ""))
                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

    logger.warning("Tool loop hit max iterations (%d)", MAX_TOOL_ITERATIONS)
    return "Что-то я закопался в поиске — сформулируй вопрос ещё раз?"
