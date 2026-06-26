"""Генерация и редактирование изображений через OpenRouter.

Тот же endpoint /chat/completions, но с modalities=["image","text"]. Результат —
base64 data URL в message.images[]. Для редактирования во вход кладётся исходное
фото как image_url. Инструменты generate_image/edit_image зовёт основная модель в
tool-loop; обработчики шлют готовое фото в чат (паттерн как on_preamble).
"""
import base64
import logging
import os
from typing import Awaitable, Callable, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# (base64_без_префикса, mime)
InputImage = Optional[Tuple[str, str]]
# async-колбэк проверки лимита: вернуть строку-отказ или None если можно
Gate = Callable[[], Awaitable[Optional[str]]]


def _data_url(b64: str, mime: str) -> str:
    return f"data:{mime};base64,{b64}"


def _decode_data_url(url: str) -> bytes | None:
    if not url.startswith("data:"):
        return None
    try:
        _, b64 = url.split(",", 1)
        return base64.b64decode(b64)
    except Exception:
        logger.warning("Failed to decode image data URL")
        return None


async def generate_image(
    model: str,
    prompt: str,
    input_image_b64: str | None = None,
    input_mime: str | None = None,
) -> bytes | None:
    """Сгенерировать (или отредактировать) изображение. Возвращает PNG/JPEG байты или None."""
    api_key = os.environ["OPENROUTER_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Pirojok",
    }
    content: list[dict] = [{"type": "text", "text": prompt}]
    if input_image_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": _data_url(input_image_b64, input_mime or "image/jpeg")},
        })
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Image generation request failed")
        return None

    try:
        message = data["choices"][0]["message"]
        images = message.get("images") or []
        if not images:
            logger.warning("No images in OpenRouter response: %s", str(data)[:300])
            return None
        url = images[0]["image_url"]["url"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Unexpected image response shape: %s", exc)
        return None

    return _decode_data_url(url)


GENERATE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Сгенерировать изображение по текстовому описанию и отправить его пользователю. "
            "Используй, когда просят нарисовать/сгенерировать/создать картинку. В prompt передай "
            "подробное конкретное описание (лучше по-английски): объект, стиль, композиция, "
            "освещение, фон. Не описывай картинку словами вместо генерации — просто зови инструмент."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Детальное описание желаемого изображения (англ. предпочтительно).",
                },
            },
            "required": ["prompt"],
        },
    },
}

EDIT_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_image",
        "description": (
            "Изменить присланное пользователем изображение по инструкции и отправить результат. "
            "Доступно только когда пользователь приложил фото. В prompt опиши, что именно изменить, "
            "сохраняя остальное без изменений (лучше по-английски)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Что изменить в изображении (англ. предпочтительно).",
                },
            },
            "required": ["prompt"],
        },
    },
}


def make_image_handlers(message, input_image: InputImage, image_model: str, gate: Gate) -> dict:
    """Пер-реквест обработчики generate_image/edit_image поверх telegram-сообщения и входного фото."""

    async def _run(prompt: str, use_input: bool) -> str:
        if use_input and not input_image:
            return "Нет картинки для редактирования — попроси пользователя прислать фото."
        refusal = await gate()
        if refusal:
            return f"Лимит на картинки исчерпан. Передай пользователю дословно: «{refusal}»"

        b64 = mime = None
        if use_input and input_image:
            b64, mime = input_image
        img = await generate_image(image_model, prompt, b64, mime)
        if img is None:
            return ("Не получилось сгенерировать изображение. Скажи пользователю, что не вышло, "
                    "и предложи переформулировать запрос.")
        try:
            await message.reply_photo(img)
        except Exception:
            logger.exception("reply_photo failed")
            return "Картинка сгенерировалась, но не отправилась — извинись перед пользователем."
        return ("Изображение готово и уже отправлено пользователю. Повторно его не описывай — "
                "просто коротко и живо прокомментируй.")

    async def generate_image_handler(prompt: str) -> str:
        return await _run(prompt, use_input=False)

    async def edit_image_handler(prompt: str) -> str:
        return await _run(prompt, use_input=True)

    return {
        "generate_image": generate_image_handler,
        "edit_image": edit_image_handler,
    }
