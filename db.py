import aiosqlite
from pathlib import Path

DB_PATH = Path("data/bot.db")


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                username    TEXT    NOT NULL,
                text        TEXT    NOT NULL,
                created_at  REAL    NOT NULL DEFAULT (unixepoch('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_group_messages_group
                ON group_messages (group_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS user_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  REAL    NOT NULL DEFAULT (unixepoch('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_user_messages_user
                ON user_messages (user_id, created_at DESC);
        """)
        await conn.commit()


async def save_group_message(group_id: int, user_id: int, username: str, text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO group_messages (group_id, user_id, username, text) VALUES (?, ?, ?, ?)",
            (group_id, user_id, username, text),
        )
        # Keep only the most recent 30 messages per group
        await conn.execute(
            """DELETE FROM group_messages
               WHERE group_id = ?
                 AND id NOT IN (
                     SELECT id FROM group_messages
                     WHERE group_id = ?
                     ORDER BY created_at DESC LIMIT 30
                 )""",
            (group_id, group_id),
        )
        await conn.commit()


async def get_group_context(group_id: int, limit: int = 30) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT username, text FROM group_messages
               WHERE group_id = ?
               ORDER BY created_at ASC LIMIT ?""",
            (group_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"username": r["username"], "text": r["text"]} for r in rows]


async def save_user_message(user_id: int, role: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO user_messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        await conn.commit()


async def get_user_history(user_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT role, content FROM (
                   SELECT role, content, created_at FROM user_messages
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?
               ) ORDER BY created_at ASC""",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def count_user_messages(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM user_messages WHERE user_id = ? AND role = 'user'",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else 0
