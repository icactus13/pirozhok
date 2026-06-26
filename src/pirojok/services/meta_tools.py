import logging

from pirojok.settings import BotSettings
from pirojok.skills import SkillError, SkillsRegistry

logger = logging.getLogger(__name__)


READ_PROMPT_TOOL = {
    "type": "function",
    "function": {
        "name": "read_prompt",
        "description": (
            "Прочитать текущий системный промпт (твои инструкции). "
            "Используй когда админ просит показать/обсудить/изменить промпт — сначала прочти, потом меняй."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

UPDATE_PROMPT_TOOL = {
    "type": "function",
    "function": {
        "name": "update_prompt",
        "description": (
            "Перезаписать системный промпт целиком. ТОЛЬКО когда админ явно просит "
            "изменить твой характер, добавить правило или переписать инструкции. "
            "Перед перезаписью прочти текущий через read_prompt, иначе сотрёшь то, что было."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "new_text": {
                    "type": "string",
                    "description": "Новый полный текст системного промпта.",
                },
            },
            "required": ["new_text"],
        },
    },
}

CREATE_OR_UPDATE_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "create_or_update_skill",
        "description": (
            "Создать новый скилл или перезаписать существующий. Скилл — это инструкция "
            "под конкретный сценарий, которую ты сможешь загрузить через load_skill."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя скилла, snake_case латиницей (2-32 символа).",
                },
                "description": {
                    "type": "string",
                    "description": "Краткое описание — когда применять. Видно тебе же в списке доступных скиллов.",
                },
                "body": {
                    "type": "string",
                    "description": "Полный текст скилла — инструкции, формат ответа, примеры.",
                },
            },
            "required": ["name", "description", "body"],
        },
    },
}

DELETE_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "delete_skill",
        "description": "Удалить скилл по имени. Только когда админ явно об этом попросил.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя скилла."},
            },
            "required": ["name"],
        },
    },
}


ADMIN_TOOLS = [
    READ_PROMPT_TOOL,
    UPDATE_PROMPT_TOOL,
    CREATE_OR_UPDATE_SKILL_TOOL,
    DELETE_SKILL_TOOL,
]


def make_admin_handlers(settings: BotSettings, skills_registry: SkillsRegistry) -> dict:
    async def read_prompt() -> str:
        return settings.system_prompt

    async def update_prompt(new_text: str) -> str:
        old_len = len(settings.system_prompt)
        settings.system_prompt = new_text.strip()
        settings.save()
        logger.info("Prompt updated by admin tool: %d → %d chars", old_len, len(new_text))
        return f"Промпт обновлён ({old_len} → {len(new_text)} символов)."

    async def create_or_update_skill(name: str, description: str, body: str) -> str:
        try:
            entry = skills_registry.add_from_parts(name, description, body)
        except SkillError as exc:
            return f"Не получилось: {exc}"
        logger.info("Skill saved by admin tool: %s", entry.name)
        return f"Скилл «{entry.name}» сохранён."

    async def delete_skill(name: str) -> str:
        try:
            existed = skills_registry.delete(name)
        except SkillError as exc:
            return f"Не получилось: {exc}"
        return "Удалил." if existed else f"Скилла «{name}» и так не было."

    return {
        "read_prompt": read_prompt,
        "update_prompt": update_prompt,
        "create_or_update_skill": create_or_update_skill,
        "delete_skill": delete_skill,
    }
