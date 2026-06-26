"""Чтение прикреплённых файлов.

PDF отправляем в основную модель как file-контент (парсит file-parser на стороне
OpenRouter). Текстовые файлы читаем локально и вставляем как текст.
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

# Текстовые форматы читаем сами (UTF-8) и подставляем в промпт.
TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "xml",
    "log", "ini", "cfg", "conf", "env", "rst",
    "py", "js", "ts", "jsx", "tsx", "java", "c", "h", "cpp", "cc", "hpp",
    "cs", "go", "rs", "rb", "php", "sh", "bash", "zsh", "sql", "html", "css",
    "kt", "swift", "scala", "lua", "pl", "r", "dockerfile", "toml", "gitignore",
}

# Обрезаем большие текстовые файлы, чтобы не раздувать запрос.
MAX_TEXT_CHARS = 50_000
# Bot API отдаёт файлы только до 20 МБ.
MAX_FILE_BYTES = 20 * 1024 * 1024


def _ext(filename: str) -> str:
    name = (filename or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def is_pdf(filename: str, mime: str | None) -> bool:
    return _ext(filename) == "pdf" or (mime or "") == "application/pdf"


def is_text(filename: str, mime: str | None) -> bool:
    if _ext(filename) in TEXT_EXTENSIONS:
        return True
    m = mime or ""
    return m.startswith("text/") or m in {"application/json", "application/xml"}


def extract_text(raw: bytes) -> str | None:
    """Декодировать текстовый файл в UTF-8 (с обрезкой). None если не текст."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError:
            return None
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n…(файл обрезан)"
    return text


def build_pdf_content(filename: str, raw: bytes) -> dict:
    """file-контент для OpenRouter (PDF как base64 data URL)."""
    b64 = base64.b64encode(raw).decode()
    return {
        "type": "file",
        "file": {
            "filename": filename or "document.pdf",
            "file_data": f"data:application/pdf;base64,{b64}",
        },
    }


# Плагин OpenRouter, парсящий PDF для любой модели.
# Движок: mistral-ocr (OCR, читает сканы, платный) | pdf-text (бесплатно, только текстовый слой)
# | native (нативный парсер модели — может падать на сложных PDF). Настраивается через env.
PDF_ENGINE = os.environ.get("OPENROUTER_PDF_ENGINE", "mistral-ocr")
PDF_PLUGINS = [{"id": "file-parser", "pdf": {"engine": PDF_ENGINE}}]
