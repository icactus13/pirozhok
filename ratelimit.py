import os

import redis.asyncio as redis

LIMIT_PER_MINUTE = 10
LIMIT_PER_HOUR = 60
IMAGE_LIMIT_PER_DAY = 5

MESSAGES = {
    "minute": "Эй, помедленнее — я не успеваю отвечать 🥲",
    "hour": "Слушай, ты сегодня уже здорово наобщался. Давай вернёмся через часик?",
    "image_day": "На сегодня лимит картинок исчерпан 🎨 Давай вернёмся к рисованию завтра!",
}


def make_client() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/1")
    return redis.from_url(url, decode_responses=True)


async def check(client: redis.Redis, user_id: int) -> str | None:
    pipe = client.pipeline()
    pipe.incr(f"rl:m:{user_id}")
    pipe.expire(f"rl:m:{user_id}", 60, nx=True)
    pipe.incr(f"rl:h:{user_id}")
    pipe.expire(f"rl:h:{user_id}", 3600, nx=True)
    m, _, h, _ = await pipe.execute()
    if h > LIMIT_PER_HOUR:
        return "hour"
    if m > LIMIT_PER_MINUTE:
        return "minute"
    return None


async def should_warn(client: redis.Redis, user_id: int, kind: str) -> bool:
    ttl = 60 if kind == "minute" else 3600
    return bool(await client.set(f"rl:w{kind[0]}:{user_id}", "1", nx=True, ex=ttl))


async def check_image(client: redis.Redis, user_id: int) -> bool:
    """Инкрементит суточный счётчик генераций. True — лимит превышен."""
    pipe = client.pipeline()
    pipe.incr(f"rl:img:{user_id}")
    pipe.expire(f"rl:img:{user_id}", 86400, nx=True)
    count, _ = await pipe.execute()
    return count > IMAGE_LIMIT_PER_DAY
