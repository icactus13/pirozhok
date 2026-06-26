import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-z0-9_]{2,32}$")
MAX_SIZE = 64 * 1024
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class SkillError(Exception):
    pass


@dataclass
class SkillEntry:
    name: str
    description: str
    body: str


def _parse_md(raw: str) -> tuple[str, str, str]:
    if len(raw.encode("utf-8")) > MAX_SIZE:
        raise SkillError(f"Файл больше {MAX_SIZE} байт")

    m = FRONTMATTER_RE.match(raw)
    if not m:
        raise SkillError("Не нашёл YAML-frontmatter (нужны строки --- в начале)")

    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"Кривой YAML во frontmatter: {exc}")

    if not isinstance(meta, dict):
        raise SkillError("Frontmatter должен быть YAML-объектом (ключ: значение)")

    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    body = m.group(2).strip()

    if not NAME_RE.match(name):
        raise SkillError(f"Имя «{name}» не подходит — нужен snake_case латиницей, 2-32 символа")
    if not description:
        raise SkillError("В frontmatter нет description")
    if not body:
        raise SkillError("Тело скилла пустое")

    return name, description, body


def _render_md(name: str, description: str, body: str) -> str:
    fm = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


class SkillsRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._items: dict[str, SkillEntry] = {}

    def load(self) -> None:
        self._items.clear()
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            return
        for path in sorted(self.root.glob("*.md")):
            try:
                raw = path.read_text(encoding="utf-8")
                name, desc, body = _parse_md(raw)
            except (SkillError, OSError) as exc:
                logger.warning("Skipping %s: %s", path.name, exc)
                continue
            if name != path.stem:
                logger.warning("Skipping %s: name «%s» mismatches filename", path.name, name)
                continue
            self._items[name] = SkillEntry(name=name, description=desc, body=body)

    def list(self) -> list[SkillEntry]:
        return sorted(self._items.values(), key=lambda s: s.name)

    def get(self, name: str) -> SkillEntry | None:
        return self._items.get(name)

    def add_from_raw(self, raw_md: str) -> SkillEntry:
        name, desc, body = _parse_md(raw_md)
        return self._save(name, desc, body)

    def add_from_parts(self, name: str, description: str, body: str) -> SkillEntry:
        name = name.strip()
        description = description.strip()
        body = body.strip()
        if not NAME_RE.match(name):
            raise SkillError("Имя должно быть snake_case латиницей (2-32 символа)")
        if not description:
            raise SkillError("Описание пустое")
        if not body:
            raise SkillError("Тело пустое")
        return self._save(name, description, body)

    def delete(self, name: str) -> bool:
        if not NAME_RE.match(name):
            raise SkillError("Невалидное имя")
        path = self.root / f"{name}.md"
        existed = self._items.pop(name, None) is not None
        if path.exists():
            path.unlink()
            existed = True
        return existed

    def _save(self, name: str, description: str, body: str) -> SkillEntry:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{name}.md"
        path.write_text(_render_md(name, description, body), encoding="utf-8")
        entry = SkillEntry(name=name, description=description, body=body)
        self._items[name] = entry
        return entry


LOAD_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Загрузить полный текст одного из сохранённых скиллов. "
            "Используй, когда видишь подходящий скилл в секции [доступные_скиллы] "
            "и хочешь следовать его инструкциям."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя скилла из списка доступных",
                },
            },
            "required": ["name"],
        },
    },
}


def make_load_handler(registry: SkillsRegistry):
    async def handler(name: str) -> str:
        s = registry.get(name)
        if not s:
            available = ", ".join(sorted(registry._items.keys())) or "—"
            return f"Скилла «{name}» нет. Доступные: {available}"
        return s.body
    return handler
