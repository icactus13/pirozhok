# 🥟 Пирожок — Telegram-бот

Живой Telegram-бот с характером: не «ассистент», а полноправный участник чата.
Работает на LLM через [OpenRouter](https://openrouter.ai/), помнит контекст
разговоров, ищет в интернете, показывает погоду и умеет расширяться скиллами
прямо из чата.

## ✨ Возможности

- 💬 **Личный характер** — общается как человек, держит контекст беседы.
- 🧠 **Долгая память** — извлекает факты о пользователе и хранит их в Qdrant
  (векторный поиск через `fastembed`).
- 📜 **История диалога** — последние N сообщений на пользователя в SQLite.
- 👥 **Групповые чаты** — молча запоминает последние 30 сообщений чата для
  контекста, отвечает по упоминанию (`@bot` или слово «пирожок»).
- 🔍 **Веб-поиск** — через self-hosted [SearXNG](https://docs.searxng.org/).
- 🌤️ **Погода и прогноз** — OpenWeatherMap (текущая + на 5 дней).
- 🧩 **Скиллы** — markdown-инструкции с YAML-frontmatter, которые модель
  подгружает по ситуации через `load_skill`.
- 📝 **Форматирование** — ответы рендерятся в Telegram MarkdownV2 через
  `telegramify-markdown` (жирный, курсив, код, спойлеры).
- ⏱️ **Рейт-лимит** — ограничение для не-админов на базе Redis.
- ⚙️ **Админка** — управление промптом, моделью и скиллами командами в чате.

## 🏗️ Архитектура

Код — пакет `src/pirojok/` (src-layout). Рантайм-данные и конфиги — в корне.

| Компонент | Модуль | Назначение |
|-----------|--------|------------|
| Точка входа | `pirojok/__main__.py` | Инициализация, polling, graceful shutdown |
| Хендлеры сообщений | `pirojok/bot/handlers.py` | Логика ответа (текст/фото/голос/файлы) |
| Админ-команды | `pirojok/bot/admin_handlers.py` | Управление из чата |
| Отправка | `pirojok/bot/tg_format.py` | Рендер ответа в MarkdownV2 + сплит длинных |
| LLM-клиент | `pirojok/services/openrouter.py` | Вызовы OpenRouter + tool-loop |
| Медиа-инструменты | `pirojok/services/{images,audio,files}.py` | Картинки, голос (STT), файлы/PDF |
| Поиск/погода | `pirojok/services/{search,weather}.py` | SearXNG, OpenWeatherMap |
| Память | `pirojok/storage/memory.py` | Qdrant: извлечение и поиск фактов |
| История/лимиты | `pirojok/storage/{db,ratelimit}.py` | SQLite + Redis |
| Настройки/скиллы | `pirojok/{settings,skills}.py` | Промпт+модель; реестр скиллов из `skills/` |

**Внешние сервисы:** OpenRouter (LLM), Qdrant (память), Redis (рейт-лимит + кэш
SearXNG), SearXNG (поиск), OpenWeatherMap (погода).

## 🚀 Запуск

### Через Docker Compose (рекомендуется)

```bash
cp .env.example .env      # заполни токены
docker compose up -d --build
```

Поднимутся четыре сервиса: `bot`, `qdrant`, `redis`, `searxng`.
Данные сохраняются в `./data/`, конфиг SearXNG — в `./searxng/`.

### Локально (через [uv](https://docs.astral.sh/uv/))

```bash
uv sync                    # создаст .venv и поставит зависимости из uv.lock
cp .env.example .env       # заполни токены, QDRANT_HOST=localhost
# нужен запущенный Qdrant, Redis и SearXNG (например, через docker compose)
uv run pirojok
```

## 🔧 Переменные окружения

| Переменная | Обязательна | Описание |
|------------|:-----------:|----------|
| `TELEGRAM_TOKEN` | ✅ | Токен бота от @BotFather |
| `OPENROUTER_API_KEY` | ✅ | Ключ OpenRouter |
| `ADMIN_USER_ID` | ✅ | Telegram ID админа (без рейт-лимита + админ-команды) |
| `OPENROUTER_MODEL` | ✅ | Основная модель (напр. `google/gemini-2.5-flash`) |
| `OPENROUTER_IMAGE_MODEL` | — | Генерация/редактирование картинок (`google/gemini-3.1-flash-image`) |
| `OPENROUTER_TRANSCRIBE_MODEL` | — | Распознавание голоса (`openai/whisper-large-v3`) |
| `OPENROUTER_PDF_ENGINE` | — | Парсер PDF: `mistral-ocr` (OCR, платный) или `pdf-text` (бесплатно) |
| `OPENWEATHER_API_KEY` | — | Ключ OpenWeatherMap (для погоды) |
| `QDRANT_HOST` / `QDRANT_PORT` | — | По умолчанию `localhost:6333` (в Docker — `qdrant`) |
| `REDIS_URL` | — | По умолчанию подставляется в compose |

## 🛠️ Админ-команды

Доступны только пользователю с `ADMIN_USER_ID`, в личке:

| Команда | Действие |
|---------|----------|
| `/settings` | Показать текущую модель, историю и промпт |
| `/setprompt <текст>` | Сменить системный промпт |
| `/setmodel <model>` | Сменить модель OpenRouter |
| `/sethistory <N>` | Размер истории диалога |
| `/skills`, `/skill <name>` | Список / просмотр скиллов |
| `/addskill`, `/delskill <name>` | Создать (диалогом) / удалить скилл |
| `/reloadskills` | Перечитать скиллы с диска |

Также можно прислать `.txt` (новый промпт) или `.md` (новый скилл) файлом.

## 🧩 Скиллы

Скилл — это `skills/<name>.md` с YAML-frontmatter:

```markdown
---
name: my_skill
description: когда применять — одной строкой
---

Инструкции для модели...
```

Имя — snake_case латиницей (2–32 символа) и должно совпадать с именем файла.
Модель видит список скиллов в системном промпте и подгружает нужный через
`load_skill(name)`.

## 📦 Деплой

`scripts/deploy.sh` собирает и обновляет бота на прод-сервере по SSH
(см. также скилл `.claude/skills/deploy`).
