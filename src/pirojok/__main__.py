import asyncio
import logging
import os
import signal
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient
from telegram import Update
from telegram.error import Forbidden
from telegram.ext import Application, ContextTypes

from pirojok.bot.admin_handlers import build_admin_handlers
from pirojok.bot.handlers import build_handlers
from pirojok.settings import BotSettings
from pirojok.skills import SkillsRegistry
from pirojok.storage import db
from pirojok.storage import memory as mem
from pirojok.storage import ratelimit

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    load_dotenv()

    required = ["TELEGRAM_TOKEN", "OPENROUTER_API_KEY", "ADMIN_USER_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

    settings = BotSettings.load()
    logger.info("Settings: model=%s, history=%d", settings.model, settings.history_size)

    await db.init_db()
    logger.info("SQLite ready")

    qdrant = AsyncQdrantClient(
        host=os.environ.get("QDRANT_HOST", "localhost"),
        port=int(os.environ.get("QDRANT_PORT", "6333")),
    )
    for attempt in range(1, 11):
        try:
            await mem.init_memory(qdrant)
            logger.info("Qdrant ready")
            break
        except Exception as exc:
            if attempt == 10:
                raise
            logger.warning("Qdrant not ready (attempt %d/10): %s — retrying in 3s", attempt, exc)
            await asyncio.sleep(3)

    admin_id = int(os.environ["ADMIN_USER_ID"])
    redis_client = ratelimit.make_client()
    logger.info("Redis client ready")

    skills_registry = SkillsRegistry(Path("skills"))
    skills_registry.load()
    logger.info("Skills: %d loaded", len(skills_registry.list()))

    image_model = os.environ.get("OPENROUTER_IMAGE_MODEL", "google/gemini-3.1-flash-image")
    transcribe_model = os.environ.get("OPENROUTER_TRANSCRIBE_MODEL", "openai/whisper-large-v3")
    logger.info("Image model: %s, transcribe model: %s", image_model, transcribe_model)

    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled error", exc_info=context.error)
        # Не пытаемся отвечать, если юзер заблокировал бота и т.п.
        if isinstance(context.error, Forbidden):
            return
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "Ой, я где-то споткнулся 🙈 Попробуй ещё раз, а если повторится — скажи хозяину."
                )
            except Exception:
                logger.warning("Failed to send error notice to user")

    app.add_error_handler(on_error)

    for handler, group in build_handlers(
        settings, qdrant, redis_client, admin_id, skills_registry, image_model, transcribe_model
    ):
        app.add_handler(handler, group=group)
    for handler, group in build_admin_handlers(settings, admin_id, skills_registry):
        app.add_handler(handler, group=group)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Пирожок is running. Press Ctrl+C to stop.")
        await stop.wait()
        await app.updater.stop()
        await app.stop()

    await qdrant.close()
    await redis_client.aclose()
    logger.info("Shutdown complete.")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
