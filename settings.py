import json
import os
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE = Path("settings.json")
PROMPT_FILE = Path("prompt.txt")


@dataclass
class BotSettings:
    system_prompt: str
    model: str
    history_size: int

    def save(self) -> None:
        data = {
            "model": self.model,
            "history_size": self.history_size,
        }
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        PROMPT_FILE.write_text(self.system_prompt, encoding="utf-8")

    @classmethod
    def load(cls) -> "BotSettings":
        prompt = PROMPT_FILE.read_text(encoding="utf-8").strip() if PROMPT_FILE.exists() else ""

        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return cls(
                system_prompt=prompt,
                model=data.get("model", os.environ["OPENROUTER_MODEL"]),
                history_size=int(data.get("history_size", 10)),
            )

        return cls(
            system_prompt=prompt,
            model=os.environ["OPENROUTER_MODEL"],
            history_size=10,
        )
