# CLAUDE.md

Шпаргалка по проекту **Пирожок** — Telegram-бота на python-telegram-bot + OpenRouter.
Подробности для людей — в `README.md`.

## Что это

Async Telegram-бот с характером (см. `prompt.txt`). LLM через OpenRouter,
память в Qdrant, история в SQLite, рейт-лимит в Redis, веб-поиск через SearXNG,
погода через OpenWeatherMap.

## Команды

```bash
uv sync                        # установить зависимости (создаёт .venv)
uv run pirojok                 # локальный запуск (нужны внешние сервисы + .env)
docker compose up -d --build   # полный стек (bot + qdrant + redis + searxng)
uv add <pkg> / uv lock         # добавить зависимость / пересобрать lock
```

Управление зависимостями — через **uv** (`pyproject.toml` + `uv.lock`). Тестов в
репозитории нет, линтеров не настроено.

## Структура

Код — пакет `src/pirojok/` (src-layout); рантайм-данные и конфиги — в корне.

- `src/pirojok/__main__.py` — точка входа (`main()`/`run()`): env-проверки, init
  сервисов, polling, graceful shutdown, глобальный error-handler.
- `src/pirojok/bot/` — Telegram-слой:
  - `handlers.py` — основной поток ответа (`_process`); личка vs группы; приём
    текста/фото/голоса/файлов; сборка системного промпта.
  - `admin_handlers.py` — админ-команды (только `ADMIN_USER_ID`).
  - `tg_format.py` — `reply_formatted()`: рендер ответа в Telegram MarkdownV2 через
    `telegramify_markdown` + сплит. **Любой ответ модели в чат идёт через него.**
- `src/pirojok/services/` — LLM и инструменты:
  - `openrouter.py` — клиент + tool-loop (`ask_openrouter`), `TOOLS`/`TOOL_HANDLERS`,
    `friendly_error()`, опц. `plugins` (PDF).
  - `images.py` (генерация/редактирование), `audio.py` (STT), `files.py` (PDF/текст),
    `search.py` (SearXNG), `weather.py` (OpenWeatherMap), `meta_tools.py` (админ-tools).
- `src/pirojok/storage/` — `db.py` (SQLite `data/bot.db`), `memory.py` (Qdrant),
  `ratelimit.py` (Redis).
- `src/pirojok/settings.py` — `BotSettings` (промпт+модель+history); промпт в
  `prompt.txt`, остальное в `settings.json` (монтируются в Docker).
- `src/pirojok/skills.py` — `SkillsRegistry`: markdown-скиллы из `skills/`.

## Конвенции

- **Язык:** весь UX, промпт, комментарии и сообщения об ошибках — на русском.
- **Импорты:** абсолютные пакетные (`from pirojok.services.openrouter import …`).
- **Async:** всё на `asyncio`; I/O — через async-клиенты (`httpx`, `aiosqlite`,
  `AsyncQdrantClient`, redis async).
- **Форматирование ответов:** только через `pirojok.bot.tg_format.reply_formatted`.
  Не добавляй `parse_mode="Markdown"` руками.
- **Новые инструменты модели:** объявляй tool-схему рядом с реализацией (как в
  `services/weather.py`) и регистрируй в `TOOLS`/`TOOL_HANDLERS` в `services/openrouter.py`.
- **Пути рантайма** (`prompt.txt`, `settings.json`, `data/`, `skills/`) — относительно
  CWD (=`/app` в Docker); не ломать, они volume-mounted и правятся на лету.
- **Скиллы:** имя snake_case латиницей (2–32), совпадает с именем файла.

## Не коммитить

`.env`, `data/` (sqlite/qdrant/redis-тома), `__pycache__/`, `.claude/settings.local.json`
— уже в `.gitignore`. Секреты — только в `.env`.
