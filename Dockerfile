FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Слой зависимостей (кэшируется, пока не менялись pyproject.toml/uv.lock)
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# Сам проект
COPY . .
RUN uv sync --locked

# Запускаем консоль-скрипт из готового venv напрямую (без накладных uv run)
ENV PATH="/app/.venv/bin:$PATH"
CMD ["pirojok"]
