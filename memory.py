import json
import logging
import uuid

from qdrant_client import AsyncQdrantClient, models

from openrouter import ask_openrouter

logger = logging.getLogger(__name__)

COLLECTION = "user_memories"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_SIZE = 384
EXTRACT_EVERY_N = 5

_message_counters: dict[int, int] = {}


def _content_text(content) -> str:
    """Текстовое представление content (строка или мультимодальный список частей)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return " ".join(t for t in parts if t)
    return ""

_EXTRACT_PROMPT = """Проанализируй этот диалог и выдели ТОЛЬКО новые конкретные факты о пользователе, \
которые будет полезно помнить в будущих разговорах (имя, работа, интересы, предпочтения, важные события).
Не выдумывай — только то, что явно сказано.
Если нет ничего значимого — верни пустой массив.

Отвечай строго в формате JSON-массива строк, без пояснений.
Пример: ["Зовут Максим", "Работает бэкенд-разработчиком", "Любит горный велосипед"]

Диалог:
{conversation}"""


async def init_memory(client: AsyncQdrantClient) -> None:
    result = await client.get_collections()
    existing = {c.name for c in result.collections}
    if COLLECTION not in existing:
        await client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        )
        logger.info("Qdrant collection '%s' created", COLLECTION)


async def store_facts(client: AsyncQdrantClient, user_id: int, facts: list[str]) -> None:
    if not facts:
        return
    await client.upload_collection(
        collection_name=COLLECTION,
        vectors=[models.Document(text=f, model=EMBED_MODEL) for f in facts],
        payload=[{"user_id": str(user_id), "fact": f} for f in facts],
        ids=[str(uuid.uuid4()) for _ in facts],
    )
    logger.info("Stored %d facts for user %d", len(facts), user_id)


async def search_memories(client: AsyncQdrantClient, user_id: int, query: str, top_k: int = 5) -> list[str]:
    try:
        result = await client.query_points(
            collection_name=COLLECTION,
            query=models.Document(text=query, model=EMBED_MODEL),
            query_filter=models.Filter(
                must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=str(user_id)))]
            ),
            limit=top_k,
            with_payload=True,
        )
        return [p.payload.get("fact", "") for p in result.points if p.payload]
    except Exception as exc:
        logger.warning("Memory search failed for user %d: %s", user_id, exc)
        return []


async def maybe_extract_facts(
    client: AsyncQdrantClient,
    user_id: int,
    model: str,
    conversation: list[dict],
) -> None:
    _message_counters[user_id] = _message_counters.get(user_id, 0) + 1
    if _message_counters[user_id] % EXTRACT_EVERY_N != 0:
        return

    dialogue = "\n".join(
        f"{'Пользователь' if m['role'] == 'user' else 'Бот'}: {_content_text(m.get('content'))}"
        for m in conversation
        if m["role"] in ("user", "assistant")
    )
    prompt = _EXTRACT_PROMPT.format(conversation=dialogue)

    try:
        raw = await ask_openrouter(model, [{"role": "user", "content": prompt}])
        facts = json.loads(raw.strip())
        if isinstance(facts, list):
            await store_facts(client, user_id, [str(f) for f in facts if f])
    except Exception as exc:
        logger.warning("Fact extraction failed for user %d: %s", user_id, exc)
