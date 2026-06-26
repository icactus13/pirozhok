"""Распознавание речи (STT) через OpenRouter.

Голосовые сообщения Telegram приходят в OGG/Opus — whisper принимает формат "ogg"
напрямую, без конвертации. Отдельный endpoint /audio/transcriptions.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


async def transcribe(model: str, audio_b64: str, fmt: str = "ogg") -> str | None:
    """Расшифровать аудио (base64) в текст. Возвращает текст или None при ошибке."""
    api_key = os.environ["OPENROUTER_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Pirojok",
    }
    payload = {
        "model": model,
        "input_audio": {"data": audio_b64, "format": fmt},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/audio/transcriptions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Transcription request failed")
        return None

    text = (data.get("text") or "").strip()
    return text or None
