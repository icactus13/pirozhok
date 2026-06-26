import asyncio
import logging
import os
import signal
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient
from telegram.ext import Application

import db
import memory as mem
import ratelimit
from admin_handlers import build_admin_handlers
from handlers import build_handlers
from settings import BotSettings
from skills import SkillsRegistry

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

    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    for handler, group in build_handlers(settings, qdrant, redis_client, admin_id, skills_registry):
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


if __name__ == "__main__":
    asyncio.run(main())
