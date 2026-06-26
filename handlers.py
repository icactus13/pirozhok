import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import MessageEntity, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, MessageHandler, filters

import db
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
    if not msg or not msg.text:
        return False
    if "пирожок" in msg.text.lower():
        return True
    if not msg.entities:
        return False
    bot_mention = f"@{context.bot.username}".lower()
    for entity in msg.entities:
        if entity.type == MessageEntity.MENTION:
            mention_text = msg.text[entity.offset: entity.offset + entity.length]
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


async def _process(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: BotSettings,
    qdrant,
    redis_client,
    admin_id: int,
    skills_registry: SkillsRegistry,
) -> None:
    user = update.effective_user
    chat = update.effective_chat
    user_text = update.effective_message.text or ""

    if not user_text.strip():
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

    all_tools_for_prompt = format_tools_for_prompt(TOOLS + extra_tools)
    system_prompt = _build_system_prompt(
        settings, relevant_memories, group_ctx, skills_list, all_tools_for_prompt,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(user_history)
    messages.append({"role": "user", "content": user_text})

    await db.save_user_message(user.id, "user", user_text)

    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

    async def send_preamble(text: str) -> None:
        await reply_formatted(update.effective_message, text)

    try:
        reply = await ask_openrouter(
            settings.model, messages,
            extra_tools=extra_tools or None,
            extra_handlers=extra_handlers or None,
            on_preamble=send_preamble,
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
) -> list:

    async def save_group_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return
        await db.save_group_message(
            group_id=update.effective_chat.id,
            user_id=user.id,
            username=_display_name(user),
            text=update.effective_message.text,
        )

    async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _process(update, context, settings, qdrant, redis_client, admin_id, skills_registry)

    async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_bot_mentioned(update, context):
            return
        await _process(update, context, settings, qdrant, redis_client, admin_id, skills_registry)

    return [
        # Group 0: silently save all group messages for context
        (
            MessageHandler(
                filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
                save_group_context,
            ),
            0,
        ),
        # Group 1: respond to private messages
        (
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                handle_private,
            ),
            1,
        ),
        # Group 1: respond to @mentions in groups
        (
            MessageHandler(
                filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
                handle_group,
            ),
            1,
        ),
    ]
