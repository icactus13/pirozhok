import asyncio
import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import MessageEntity, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, MessageHandler, filters

import audio
import db
import files
import images
import memory as mem
import ratelimit
from meta_tools import ADMIN_TOOLS, make_admin_handlers
from openrouter import TOOLS, ask_openrouter, format_tools_for_prompt
from settings import BotSettings
from skills import LOAD_SKILL_TOOL, SkillsRegistry, make_load_handler
from tg_format import reply_formatted

logger = logging.getLogger(__name__)


def _display_name(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


def _is_bot_mentioned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg = update.effective_message
    if not msg:
        return False
    # Ответ-reply на сообщение бота = обращение к нему (работает и для голоса/файлов без текста)
    reply = msg.reply_to_message
    if reply and reply.from_user and reply.from_user.id == context.bot.id:
        return True
    text = msg.text or msg.caption  # у фото/файла текст лежит в caption
    if not text:
        return False
    if "пирожок" in text.lower():
        return True
    entities = msg.entities or msg.caption_entities
    if not entities:
        return False
    bot_mention = f"@{context.bot.username}".lower()
    for entity in entities:
        if entity.type == MessageEntity.MENTION:
            mention_text = text[entity.offset: entity.offset + entity.length]
            if mention_text.lower() == bot_mention:
                return True
    return False


_WEEKDAYS_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]
_MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _format_now() -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    weekday = _WEEKDAYS_RU[now.weekday()]
    month = _MONTHS_RU[now.month - 1]
    return f"Сегодня {weekday}, {now.day} {month} {now.year} года, {now.strftime('%H:%M')} по Москве."


def _build_system_prompt(
    settings: BotSettings,
    memories: list[str],
    group_ctx: list[dict],
    skills: list,
    tools_for_prompt: str,
) -> str:
    parts = [settings.system_prompt]
    parts.append(f"\n\n[сейчас]\n{_format_now()}")
    if tools_for_prompt:
        parts.append("\n\n[доступные_инструменты]\n" + tools_for_prompt)
    if skills:
        skills_block = "\n".join(f"- {s.name} — {s.description}" for s in skills)
        parts.append(
            "\n\n[доступные_скиллы]\n"
            "Если ситуация подходит под один из скиллов — загрузи его через "
            "load_skill(name) и следуй ему.\n\n" + skills_block
        )
    if memories:
        facts_block = "\n".join(f"- {m}" for m in memories)
        parts.append(f"\n\n[Что я знаю об этом пользователе:]\n{facts_block}")
    if group_ctx:
        lines = "\n".join(f"{m['username']}: {m['text']}" for m in group_ctx)
        parts.append(f"\n\n[Последние сообщения в чате — будь в теме разговора:]\n{lines}")
    return "".join(parts)


async def _download_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скачать самое крупное фото из сообщения как (base64, mime) или None."""
    msg = update.effective_message
    if not msg or not msg.photo:
        return None
    try:
        file = await context.bot.get_file(msg.photo[-1].file_id)
        raw = await file.download_as_bytearray()
        return base64.b64encode(bytes(raw)).decode(), "image/jpeg"
    except Exception:
        logger.exception("Failed to download photo")
        return None


async def _transcribe_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, model: str) -> str | None:
    """Скачать голосовое и расшифровать в текст."""
    msg = update.effective_message
    try:
        file = await context.bot.get_file(msg.voice.file_id)
        raw = await file.download_as_bytearray()
    except Exception:
        logger.exception("Failed to download voice")
        return None
    b64 = base64.b64encode(bytes(raw)).decode()
    return await audio.transcribe(model, b64, "ogg")


async def _read_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прочитать прикреплённый документ.

    Возвращает ("pdf", file_content) | ("text", (name, text)) | None (отказ уже отправлен).
    """
    msg = update.effective_message
    doc = msg.document
    name = doc.file_name or "файл"

    if doc.file_size and doc.file_size > files.MAX_FILE_BYTES:
        await msg.reply_text("Файл великоват — больше 20 МБ я скачать не могу 😕")
        return None
    if not (files.is_pdf(name, doc.mime_type) or files.is_text(name, doc.mime_type)):
        await msg.reply_text("Такой формат я пока не читаю 🙈 Пришли PDF или текстовый файл.")
        return None

    try:
        file = await context.bot.get_file(doc.file_id)
        raw = bytes(await file.download_as_bytearray())
    except Exception:
        logger.exception("Failed to download document")
        await msg.reply_text("Не получилось скачать файл, попробуй ещё раз.")
        return None

    if files.is_pdf(name, doc.mime_type):
        return "pdf", files.build_pdf_content(name, raw)

    text = files.extract_text(raw)
    if not text:
        await msg.reply_text("Файл пустой или не в текстовой кодировке 🤔")
        return None
    return "text", (name, text)


async def _process(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: BotSettings,
    qdrant,
    redis_client,
    admin_id: int,
    skills_registry: SkillsRegistry,
    image_model: str,
    transcribe_model: str,
) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    user_text = (msg.text or msg.caption or "").strip()

    input_image = await _download_photo(update, context)

    # Голосовое → транскрипция становится текстом запроса
    is_voice = bool(msg.voice)
    if is_voice:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        transcript = await _transcribe_voice(update, context, transcribe_model)
        if not transcript:
            await msg.reply_text("Не расслышал голосовое 🙉 Попробуй ещё раз или текстом.")
            return
        user_text = transcript

    # Документ → PDF (file-контент) или текстовый файл (инлайн в запрос)
    pdf_content = None
    plugins = None
    if msg.document:
        result = await _read_document(update, context)
        if result is None:
            return  # отказ уже отправлен
        kind, payload = result
        if kind == "pdf":
            pdf_content = payload
            plugins = files.PDF_PLUGINS
        else:
            fname, ftext = payload
            block = f"\n\n[Файл {fname}]:\n{ftext}"
            user_text = (user_text + block) if user_text else f"Вот файл «{fname}», разберись, что в нём:{block}"

    if not user_text and input_image is None and pdf_content is None:
        return

    if chat.type == "private" and user.id != admin_id:
        hit = await ratelimit.check(redis_client, user.id)
        if hit:
            if await ratelimit.should_warn(redis_client, user.id, hit):
                await update.effective_message.reply_text(ratelimit.MESSAGES[hit])
            return

    # Retrieve context
    relevant_memories = await mem.search_memories(qdrant, user.id, user_text)
    group_ctx = []
    if chat.type != "private":
        group_ctx = await db.get_group_context(chat.id, limit=30)
    user_history = await db.get_user_history(user.id, limit=settings.history_size)

    skills_list = skills_registry.list()

    extra_tools: list[dict] = []
    extra_handlers: dict = {}
    if skills_list:
        extra_tools.append(LOAD_SKILL_TOOL)
        extra_handlers["load_skill"] = make_load_handler(skills_registry)
    if user.id == admin_id:
        extra_tools.extend(ADMIN_TOOLS)
        extra_handlers.update(make_admin_handlers(settings, skills_registry))

    # Картинки: рисование — всем, редактирование — только если приложено фото.
    async def image_gate() -> str | None:
        if user.id == admin_id:
            return None
        over = await ratelimit.check_image(redis_client, user.id)
        return ratelimit.MESSAGES["image_day"] if over else None

    extra_tools.append(images.GENERATE_IMAGE_TOOL)
    if input_image is not None:
        extra_tools.append(images.EDIT_IMAGE_TOOL)
    extra_handlers.update(
        images.make_image_handlers(msg, input_image, image_model, image_gate)
    )

    all_tools_for_prompt = format_tools_for_prompt(TOOLS + extra_tools)
    system_prompt = _build_system_prompt(
        settings, relevant_memories, group_ctx, skills_list, all_tools_for_prompt,
    )

    if input_image is not None or pdf_content is not None:
        parts: list[dict] = [{"type": "text", "text": user_text or "[без подписи]"}]
        if input_image is not None:
            b64, mime = input_image
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        if pdf_content is not None:
            parts.append(pdf_content)
        user_content = parts
        label = "[прислал картинку]" if input_image is not None else "[файл pdf]"
        history_text = f"{label} {user_text}".strip()
    else:
        user_content = user_text
        history_text = f"[голос] {user_text}" if is_voice else user_text

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(user_history)
    messages.append({"role": "user", "content": user_content})

    await db.save_user_message(user.id, "user", history_text)

    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

    async def send_preamble(text: str) -> None:
        await reply_formatted(update.effective_message, text)

    try:
        reply = await ask_openrouter(
            settings.model, messages,
            extra_tools=extra_tools or None,
            extra_handlers=extra_handlers or None,
            on_preamble=send_preamble,
            plugins=plugins,
        )
    except Exception as exc:
        logger.error("OpenRouter error: %s", exc)
        await update.effective_message.reply_text("Упс, что-то пошло не так. Попробуй ещё раз 🙈")
        return

    await db.save_user_message(user.id, "assistant", reply)
    await reply_formatted(update.effective_message, reply)

    # Extract facts from conversation in background (every N messages)
    asyncio.create_task(
        mem.maybe_extract_facts(qdrant, user.id, settings.model, messages)
    )


def build_handlers(
    settings: BotSettings,
    qdrant,
    redis_client,
    admin_id: int,
    skills_registry: SkillsRegistry,
    image_model: str,
    transcribe_model: str,
) -> list:

    async def save_group_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return
        msg = update.effective_message
        text = msg.text or msg.caption
        if not text:  # фото/голос без подписи и т.п. — нечего сохранять как контекст
            return
        await db.save_group_message(
            group_id=update.effective_chat.id,
            user_id=user.id,
            username=_display_name(user),
            text=text,
        )

    async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _process(update, context, settings, qdrant, redis_client, admin_id,
                       skills_registry, image_model, transcribe_model)

    async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_bot_mentioned(update, context):
            return
        await _process(update, context, settings, qdrant, redis_client, admin_id,
                       skills_registry, image_model, transcribe_model)

    # текст, фото, голосовые и документы (.txt/.md от админа перехватываются раньше, в группе 0)
    content_filter = (filters.TEXT | filters.PHOTO | filters.VOICE | filters.Document.ALL) & ~filters.COMMAND

    return [
        # Group 0: silently save all group messages (text + captioned media) for context
        (
            MessageHandler(
                filters.ChatType.GROUPS & content_filter,
                save_group_context,
            ),
            0,
        ),
        # Group 1: respond to private messages (text/photo/voice/document)
        (
            MessageHandler(
                filters.ChatType.PRIVATE & content_filter,
                handle_private,
            ),
            1,
        ),
        # Group 1: respond to @mentions/replies in groups (text/photo/voice/document)
        (
            MessageHandler(
                filters.ChatType.GROUPS & content_filter,
                handle_group,
            ),
            1,
        ),
    ]
