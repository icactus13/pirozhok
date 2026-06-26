"""Отправка ответов модели в Telegram с корректным форматированием.

Модель выдаёт обычный (GitHub-flavored) Markdown: **жирный**, _курсив_,
~~зачёркнуто~~, ||спойлер||, `код`, ```блоки```. У Telegram свой диалект
(MarkdownV2) с обязательным экранированием спецсимволов, поэтому текст
прогоняется через telegramify_markdown.markdownify перед отправкой.
"""
import logging

import telegramify_markdown
from telegram import Message
from telegram.constants import ParseMode
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

# Telegram ограничивает сообщение 4096 символами. Режем исходный текст с
# запасом по границам абзацев/строк, затем конвертируем каждый кусок.
_CHUNK_LIMIT = 3500


def _split_text(text: str, limit: int = _CHUNK_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        block = (paragraph + "\n\n")
        if len(current) + len(block) > limit and current:
            chunks.append(current.rstrip("\n"))
            current = ""
        if len(block) > limit:
            # абзац сам по себе длиннее лимита — режем по строкам
            for line in block.splitlines(keepends=True):
                if len(current) + len(line) > limit and current:
                    chunks.append(current.rstrip("\n"))
                    current = ""
                current += line
        else:
            current += block
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks or [text]


async def reply_formatted(message: Message, text: str) -> None:
    """Ответить на сообщение, отрендерив Markdown как MarkdownV2.

    При ошибке разметки откатывается на обычный текст, чтобы ответ
    в любом случае дошёл до пользователя.
    """
    if not text:
        return
    for chunk in _split_text(text):
        try:
            rendered = telegramify_markdown.markdownify(chunk)
            await message.reply_text(rendered, parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as exc:
            logger.warning("MarkdownV2 send failed, falling back to plain: %s", exc)
            await message.reply_text(chunk)
