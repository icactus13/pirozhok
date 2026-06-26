import logging

from telegram import Update
from telegram.ext import (
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from pirojok.settings import BotSettings
from pirojok.skills import NAME_RE, SkillError, SkillsRegistry

logger = logging.getLogger(__name__)

ASK_NAME, ASK_DESC, ASK_BODY = range(3)


def build_admin_handlers(
    settings: BotSettings,
    admin_id: int,
    skills_registry: SkillsRegistry,
) -> list:

    def admin_only(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user and update.effective_user.id == admin_id:
                return await func(update, context)
            return None
        return wrapper

    @admin_only
    async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            f"⚙️ *Текущие настройки*\n\n"
            f"🤖 Модель: `{settings.model}`\n"
            f"📜 История: `{settings.history_size}` сообщений\n\n"
            f"*Промпт:*\n{settings.system_prompt}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    @admin_only
    async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        new_prompt = update.message.text.removeprefix("/setprompt").strip()
        if not new_prompt:
            await update.message.reply_text("Укажи текст промпта после команды: /setprompt <текст>")
            return
        settings.system_prompt = new_prompt
        settings.save()
        await update.message.reply_text("✅ Промпт обновлён!")

    @admin_only
    async def cmd_setmodel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        new_model = " ".join(context.args) if context.args else ""
        if not new_model:
            await update.message.reply_text("Укажи модель: /setmodel google/gemini-2.5-flash")
            return
        settings.model = new_model
        settings.save()
        await update.message.reply_text(f"✅ Модель изменена на `{new_model}`", parse_mode="Markdown")

    @admin_only
    async def cmd_sethistory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text("Укажи число: /sethistory 10")
            return
        n = int(context.args[0])
        if n < 1:
            await update.message.reply_text("Минимальный размер истории — 1.")
            return
        settings.history_size = n
        settings.save()
        await update.message.reply_text(f"✅ Размер истории: `{n}` сообщений", parse_mode="Markdown")

    @admin_only
    async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        items = skills_registry.list()
        if not items:
            await update.message.reply_text("Скиллов пока нет. Создай через /addskill или загрузи .md.")
            return
        lines = [f"• `{s.name}` — {s.description}" for s in items]
        await update.message.reply_text(
            "🧠 *Скиллы:*\n\n" + "\n".join(lines),
            parse_mode="Markdown",
        )

    @admin_only
    async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Укажи имя: /skill <name>")
            return
        name = context.args[0]
        entry = skills_registry.get(name)
        if not entry:
            await update.message.reply_text(f"Скилла `{name}` нет.", parse_mode="Markdown")
            return
        text = f"*{entry.name}* — {entry.description}\n\n{entry.body}"
        if len(text) > 4000:
            text = text[:4000] + "\n\n…(обрезано)"
        await update.message.reply_text(text, parse_mode="Markdown")

    @admin_only
    async def cmd_delskill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Укажи имя: /delskill <name>")
            return
        name = context.args[0]
        try:
            existed = skills_registry.delete(name)
        except SkillError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return
        if existed:
            await update.message.reply_text(f"✅ Скилл `{name}` удалён.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"Скилла `{name}` и так не было.", parse_mode="Markdown")

    @admin_only
    async def cmd_reloadskills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        skills_registry.load()
        await update.message.reply_text(f"🔄 Перезагружено: {len(skills_registry.list())} скиллов.")

    @admin_only
    async def addskill_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["new_skill"] = {}
        await update.message.reply_text(
            "Создаём скилл. Имя (snake_case, латиница, 2-32 символа). /cancel — отмена."
        )
        return ASK_NAME

    @admin_only
    async def addskill_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = (update.message.text or "").strip()
        if not NAME_RE.match(name):
            await update.message.reply_text("Не похоже на snake_case. Попробуй ещё раз или /cancel.")
            return ASK_NAME
        context.user_data["new_skill"]["name"] = name
        await update.message.reply_text("Описание (одной строкой — когда применять).")
        return ASK_DESC

    @admin_only
    async def addskill_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
        desc = (update.message.text or "").strip()
        if not desc:
            await update.message.reply_text("Описание пустое. Попробуй ещё раз или /cancel.")
            return ASK_DESC
        context.user_data["new_skill"]["description"] = desc
        await update.message.reply_text("Содержимое скилла (одним сообщением).")
        return ASK_BODY

    @admin_only
    async def addskill_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
        body = (update.message.text or "").strip()
        if not body:
            await update.message.reply_text("Тело пустое. Попробуй ещё раз или /cancel.")
            return ASK_BODY
        data = context.user_data.get("new_skill") or {}
        try:
            entry = skills_registry.add_from_parts(
                name=data["name"],
                description=data["description"],
                body=body,
            )
        except SkillError as exc:
            await update.message.reply_text(f"❌ {exc}")
            context.user_data.pop("new_skill", None)
            return ConversationHandler.END
        context.user_data.pop("new_skill", None)
        await update.message.reply_text(
            f"✅ Скилл `{entry.name}` сохранён.", parse_mode="Markdown"
        )
        return ConversationHandler.END

    @admin_only
    async def addskill_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.pop("new_skill", None)
        await update.message.reply_text("Отменил.")
        return ConversationHandler.END

    @admin_only
    async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Сюда попадают только админские .txt/.md (см. фильтр ниже). Любой исход
        # завершается ApplicationHandlerStop, чтобы общий ридер файлов не дублировал.
        doc = update.message.document
        name = (doc.file_name or "").lower()

        if name.endswith(".txt"):
            file = await context.bot.get_file(doc.file_id)
            content = await file.download_as_bytearray()
            new_prompt = content.decode("utf-8").strip()
            if not new_prompt:
                await update.message.reply_text("Файл пустой, промпт не изменён.")
            else:
                settings.system_prompt = new_prompt
                settings.save()
                await update.message.reply_text("✅ Промпт загружен из файла!")
        elif name.endswith(".md"):
            file = await context.bot.get_file(doc.file_id)
            content = await file.download_as_bytearray()
            try:
                raw = content.decode("utf-8")
            except UnicodeDecodeError:
                await update.message.reply_text("❌ Файл не в UTF-8.")
            else:
                try:
                    entry = skills_registry.add_from_raw(raw)
                    await update.message.reply_text(
                        f"✅ Скилл `{entry.name}` сохранён.", parse_mode="Markdown"
                    )
                except SkillError as exc:
                    await update.message.reply_text(f"❌ {exc}")

        raise ApplicationHandlerStop

    private = filters.ChatType.PRIVATE

    addskill_conv = ConversationHandler(
        entry_points=[CommandHandler("addskill", addskill_start, filters=private)],
        states={
            ASK_NAME: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, addskill_name)],
            ASK_DESC: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, addskill_desc)],
            ASK_BODY: [MessageHandler(private & filters.TEXT & ~filters.COMMAND, addskill_body)],
        },
        fallbacks=[CommandHandler("cancel", addskill_cancel, filters=private)],
        per_chat=True,
        per_user=True,
    )

    return [
        (CommandHandler("settings", cmd_settings, filters=private), 1),
        (CommandHandler("setprompt", cmd_setprompt, filters=private), 1),
        (CommandHandler("setmodel", cmd_setmodel, filters=private), 1),
        (CommandHandler("sethistory", cmd_sethistory, filters=private), 1),
        (CommandHandler("skills", cmd_skills, filters=private), 1),
        (CommandHandler("skill", cmd_skill, filters=private), 1),
        (CommandHandler("delskill", cmd_delskill, filters=private), 1),
        (CommandHandler("reloadskills", cmd_reloadskills, filters=private), 1),
        (addskill_conv, 1),
        # Group 0: админский .txt→промпт / .md→скилл перехватывается раньше общего ридера файлов
        (
            MessageHandler(
                private
                & filters.User(admin_id)
                & (filters.Document.FileExtension("txt") | filters.Document.FileExtension("md")),
                handle_document,
            ),
            0,
        ),
    ]
