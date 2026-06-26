# CLAUDE.md

Шпаргалка по проекту **Пирожок** — Telegram-бота на python-telegram-bot + OpenRouter.
Подробности для людей — в `README.md`.

## Что это

Async Telegram-бот с характером (см. `prompt.txt`). LLM через OpenRouter,
память в Qdrant, история в SQLite, рейт-лимит в Redis, веб-поиск через SearXNG,
погода через OpenWeatherMap.

## Команды

```bash
docker compose up -d --build   # полный стек (bot + qdrant + redis + searxng)
python bot.py                  # локальный запуск (нужны внешние сервисы + .env)
pip install -r requirements.txt
```

Тестов в репозитории нет. Линтеров не настроено.

## Карта кода

- `bot.py` — точка входа: env-проверки, init сервисов, polling, graceful shutdown.
- `handlers.py` — основной поток ответа (`_process`); личка vs группы; сборка
  системного промпта из настроек, памяти, контекста группы и списка инструментов.
- `openrouter.py` — клиент OpenRouter + tool-loop (`ask_openrouter`), реестр
  `TOOLS` / `TOOL_HANDLERS`, поддержка preamble-сообщений.
- `tg_format.py` — `reply_formatted()`: рендер ответа модели в Telegram MarkdownV2
  через `telegramify_markdown` + сплит длинных сообщений. **Любой ответ модели в
  чат идёт через него, не через голый `reply_text`.**
- `settings.py` — `BotSettings` (промпт + модель + history_size); промпт в
  `prompt.txt`, остальное в `settings.json` (оба монтируются в Docker).
- `db.py` — SQLite (`data/bot.db`): `user_messages` (история) и `group_messages`
  (последние 30 на группу).
- `memory.py` — Qdrant: извлечение фактов о юзере (фоном) и векторный поиск.
- `skills.py` — `SkillsRegistry`: markdown-скиллы из `skills/` с YAML-frontmatter;
  модель грузит их через `load_skill`.
- `admin_handlers.py` + `meta_tools.py` — админ-команды и админ-tools (только
  `ADMIN_USER_ID`).
- `search.py` (SearXNG), `weather.py` (OpenWeatherMap), `ratelimit.py` (Redis).

## Конвенции

- **Язык:** весь UX, промпт, комментарии и сообщения об ошибках — на русском.
- **Async:** всё на `asyncio`; I/O — через async-клиенты (`httpx`, `aiosqlite`,
  `AsyncQdrantClient`, redis async).
- **Форматирование ответов:** только через `tg_format.reply_formatted`. Модель
  выдаёт обычный Markdown — Telegram требует MarkdownV2 с экранированием, это
  делает `telegramify_markdown`. Не добавляй `parse_mode="Markdown"` руками.
- **Новые инструменты модели:** объявляй tool-схему рядом с реализацией (как в
  `weather.py`/`search.py`) и регистрируй в `TOOLS`/`TOOL_HANDLERS` в `openrouter.py`.
- **Скиллы:** имя snake_case латиницей (2–32), совпадает с именем файла.

## Не коммитить

`.env`, `data/` (sqlite/qdrant/redis-тома), `__pycache__/`, `.claude/settings.local.json`
— уже в `.gitignore`. Секреты — только в `.env`.
