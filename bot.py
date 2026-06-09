from __future__ import annotations

import json
import logging
import io
import math
import os
import re
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from urllib import error, parse, request


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
TELEGRAM_MESSAGE_LIMIT = 4096
SAFE_MESSAGE_CHUNK = 3900
MAX_TUNING_TEXT_CHARS = 12000
MAX_MEMORY_ITEMS_PER_CHAT = 40
MAX_MEMORY_ITEM_CHARS = 500
MAX_WEB_CONTEXT_CHARS = 6000
MAX_RAG_CONTEXT_CHARS = 6000
MAX_RECENT_DOCUMENTS_PER_CHAT = 5
RAG_CHUNK_CHARS = 1200
RAG_CHUNK_OVERLAP = 180
RAG_MAX_FILE_BYTES = 12 * 1024 * 1024
RAG_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}
WEB_SEARCH_KEYWORDS = (
    "today",
    "latest",
    "current",
    "recent",
    "now",
    "news",
    "price",
    "weather",
    "schedule",
    "stock",
    "crypto",
    "сегодня",
    "сейчас",
    "актуаль",
    "последн",
    "свеж",
    "новост",
    "цена",
    "курс",
    "погода",
    "расписание",
    "котиров",
)
MULTI_CHAIN_KEYWORDS = (
    "analyze",
    "compare",
    "plan",
    "strategy",
    "decide",
    "why",
    "how",
    "debug",
    "architecture",
    "risk",
    "tradeoff",
    "анализ",
    "сравн",
    "план",
    "стратег",
    "реши",
    "почему",
    "как",
    "отлад",
    "архитект",
    "риск",
    "выбери",
)
IMAGE_REQUEST_PATTERNS = (
    r"\b(?:сгенерируй|сгенерировать|создай|сделай|нарисуй|изобрази|покажи)\b.*\b(?:картинк\w*|изображени\w*|фото|рисунок|арт|пикчу)\b",
    r"\b(?:картинк\w*|изображени\w*|фото|рисунок|арт|пикчу)\b.*\b(?:сгенерируй|сгенерировать|создай|сделай|нарисуй|изобрази|покажи)\b",
    r"\b(?:draw|generate|create|make|paint|render)\b.*\b(?:image|picture|photo|art|drawing|illustration)\b",
    r"\b(?:image|picture|photo|art|drawing|illustration)\b.*\b(?:draw|generate|create|make|paint|render)\b",
    r"^\s*(?:нарисуй|изобрази|сгенерируй|draw|generate|paint|render)\b",
)


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "bot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. Add it to .env or set it as an environment variable.")
    return value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid %s=%r; using %s.", name, value, default)
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logging.warning("Invalid %s=%r; using %s.", name, value, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on", "y"}:
        return True
    if value in {"0", "false", "no", "off", "n"}:
        return False
    logging.warning("Invalid %s=%r; using %s.", name, value, default)
    return default


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TelegramGroqBot/1.0 (+https://telegram.org/)",
            **(headers or {}),
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def request_json(
    method: str,
    url: str,
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TelegramGroqBot/1.0 (+https://telegram.org/)",
            **(headers or {}),
        },
        method=method,
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "TelegramGroqBot/1.0 (+https://telegram.org/)",
            **(headers or {}),
        },
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def post_binary(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[bytes, str]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": "TelegramGroqBot/1.0 (+https://telegram.org/)",
            **(headers or {}),
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
            return response.read(), content_type
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def post_multipart(
    url: str,
    fields: dict[str, Any],
    files: dict[str, tuple[str, bytes, str]],
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    boundary = f"----TelegramGroqBot{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for name, (filename, content, content_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(content)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    req = request.Request(
        url,
        data=bytes(body),
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "TelegramGroqBot/1.0 (+https://telegram.org/)",
            **(headers or {}),
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body_text[:1000]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def split_message(text: str) -> list[str]:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return [text]

    chunks: list[str] = []
    remaining = text

    while len(remaining) > SAFE_MESSAGE_CHUNK:
        cut_at = max(
            remaining.rfind("\n", 0, SAFE_MESSAGE_CHUNK),
            remaining.rfind(". ", 0, SAFE_MESSAGE_CHUNK),
            remaining.rfind("! ", 0, SAFE_MESSAGE_CHUNK),
            remaining.rfind("? ", 0, SAFE_MESSAGE_CHUNK),
            remaining.rfind(" ", 0, SAFE_MESSAGE_CHUNK),
        )
        if cut_at < 1000:
            cut_at = SAFE_MESSAGE_CHUNK

        chunks.append(remaining[:cut_at].strip())
        remaining = remaining[cut_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


def normalize_command(text: str) -> str:
    first = text.strip().split(maxsplit=1)[0].lower()
    return first.split("@", 1)[0]


def command_argument(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def read_optional_text(path: Path, max_chars: int = MAX_TUNING_TEXT_CHARS) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > max_chars:
        logging.warning("Truncated %s from %s to %s chars.", path, len(text), max_chars)
        text = text[:max_chars].strip()
    return text


def truncate_text(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def chunk_text(text: str, chunk_chars: int = RAG_CHUNK_CHARS, overlap: int = RAG_CHUNK_OVERLAP) -> list[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines())
    cleaned = "\n".join(line for line in cleaned.splitlines() if line)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_chars, len(cleaned))
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def vector_to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def should_use_web_search(prompt: str) -> bool:
    lowered = prompt.lower()
    if "http://" in lowered or "https://" in lowered:
        return True
    return any(keyword in lowered for keyword in WEB_SEARCH_KEYWORDS)


def should_use_multi_chain(prompt: str) -> bool:
    lowered = prompt.lower()
    if len(prompt) >= 180:
        return True
    if "?" in prompt and len(prompt) >= 90:
        return True
    return any(keyword in lowered for keyword in MULTI_CHAIN_KEYWORDS)


def normalize_document_name(text: str) -> str:
    normalized = text.strip().strip("\"'`.,:;!?()[]{}")
    lowered = normalized.lower()
    for marker in (" в документе ", " в файле ", " документ ", " файл ", " про ", " в "):
        if marker in lowered:
            normalized = normalized[lowered.rfind(marker) + len(marker) :].strip()
            lowered = normalized.lower()

    replacements = {
        ".пдф": ".pdf",
        ".тхт": ".txt",
        ".текст": ".txt",
        ".мд": ".md",
    }
    for old, new in replacements.items():
        if lowered.endswith(old):
            return normalized[: -len(old)] + new
    return normalized


def extract_document_names(text: str) -> list[str]:
    pattern = r"[\wА-Яа-яЁё ._\-()]+?\.(?:pdf|txt|md|markdown|пдф|тхт|текст|мд)\b"
    names: list[str] = []
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        name = normalize_document_name(match.group(0))
        if name and name not in names:
            names.append(name)
    return names


def asks_about_document(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "документ",
            "файл",
            "pdf",
            "пдф",
            "что тут",
            "что там",
            "что написано",
            "скинут",
            "загруж",
            "отправ",
        )
    )


def is_image_generation_request(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    non_image_targets = (
        "текст",
        "ответ",
        "план",
        "код",
        "список",
        "таблиц",
        "документ",
        "письмо",
        "резюме",
        "пост",
        "сообщение",
        "text",
        "answer",
        "plan",
        "code",
        "list",
        "table",
        "document",
        "email",
        "message",
    )
    explicit_visual_words = (
        "картин",
        "изображ",
        "фото",
        "рисунок",
        "арт",
        "пикч",
        "image",
        "picture",
        "photo",
        "drawing",
        "illustration",
        "art",
    )
    if any(word in lowered for word in non_image_targets) and not any(
        word in lowered for word in explicit_visual_words
    ):
        return False
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in IMAGE_REQUEST_PATTERNS)


def extract_image_prompt(text: str) -> str:
    prompt = text.strip()
    prompt = re.sub(r"^@\w+\s+", "", prompt).strip()

    cleanup_patterns = (
        r"^(?:пожалуйста\s*,?\s*)?(?:сгенерируй|сгенерировать|создай|сделай|нарисуй|изобрази|покажи)\s+(?:мне\s+|нам\s+)?",
        r"^(?:please\s+)?(?:draw|generate|create|make|paint|render)\s+(?:me\s+|us\s+)?",
        r"^(?:картинку|изображение|фото|рисунок|арт|пикчу)\s+(?:с\s+|про\s+|о\s+)?",
        r"^(?:an\s+|a\s+)?(?:image|picture|photo|drawing|illustration|art)\s+(?:of\s+|about\s+)?",
    )
    for pattern in cleanup_patterns:
        prompt = re.sub(pattern, "", prompt, flags=re.IGNORECASE).strip(" .,;:-")

    prompt = re.sub(
        r"^(?:картинку|изображение|фото|рисунок|арт|пикчу)\s+(?:с\s+|про\s+|о\s+)?",
        "",
        prompt,
        flags=re.IGNORECASE,
    ).strip(" .,;:-")
    prompt = re.sub(
        r"^(?:an\s+|a\s+)?(?:image|picture|photo|drawing|illustration|art)\s+(?:of\s+|about\s+)?",
        "",
        prompt,
        flags=re.IGNORECASE,
    ).strip(" .,;:-")

    return prompt or text.strip()


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.exception("Could not parse JSON file: %s", path)
        return default


def save_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_few_shot_examples(path: Path, limit: int) -> list[dict[str, str]]:
    if limit <= 0 or not path.exists():
        return []

    examples: list[dict[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            logging.warning("Skipping invalid JSONL line %s in %s.", line_number, path)
            continue

        user = str(item.get("user", "")).strip()
        assistant = str(item.get("assistant", "")).strip()
        if user and assistant:
            examples.append({"user": user, "assistant": assistant})
        if len(examples) >= limit:
            break
    return examples


class TelegramGroqBot:
    def __init__(
        self,
        telegram_token: str,
        groq_api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        history_messages: int,
        profile_file: Path,
        knowledge_file: Path,
        recent_db_file: Path,
        examples_file: Path,
        memory_file: Path,
        few_shot_examples: int,
        ground_check_enabled: bool,
        ground_check_max_tokens: int,
        multi_chain_enabled: bool,
        multi_chain_count: int,
        multi_chain_max_tokens: int,
        tavily_api_key: str,
        tavily_enabled: bool,
        tavily_auto_search: bool,
        tavily_search_depth: str,
        tavily_max_results: int,
        cloudflare_api_token: str,
        cloudflare_account_id: str,
        cloudflare_image_model: str,
        cloudflare_image_width: int,
        cloudflare_image_height: int,
        cloudflare_image_num_steps: int,
        cloudflare_image_guidance: float,
        supabase_url: str,
        supabase_anon_key: str,
        supabase_service_key: str,
        rag_enabled: bool,
        rag_embedding_model: str,
        rag_match_count: int,
        rag_similarity_threshold: float,
    ) -> None:
        self.telegram_token = telegram_token
        self.groq_api_key = groq_api_key
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.profile_file = profile_file
        self.knowledge_file = knowledge_file
        self.recent_db_file = recent_db_file
        self.examples_file = examples_file
        self.memory_file = memory_file
        self.few_shot_examples = few_shot_examples
        self.ground_check_enabled = ground_check_enabled
        self.ground_check_max_tokens = ground_check_max_tokens
        self.multi_chain_enabled = multi_chain_enabled
        self.multi_chain_count = max(1, min(multi_chain_count, 4))
        self.multi_chain_max_tokens = multi_chain_max_tokens
        self.tavily_api_key = tavily_api_key
        self.tavily_enabled = tavily_enabled and bool(tavily_api_key)
        self.tavily_auto_search = tavily_auto_search
        self.tavily_search_depth = tavily_search_depth
        self.tavily_max_results = tavily_max_results
        self.cloudflare_api_token = cloudflare_api_token
        self.cloudflare_account_id = cloudflare_account_id
        self.cloudflare_image_model = cloudflare_image_model
        self.cloudflare_image_width = cloudflare_image_width
        self.cloudflare_image_height = cloudflare_image_height
        self.cloudflare_image_num_steps = cloudflare_image_num_steps
        self.cloudflare_image_guidance = cloudflare_image_guidance
        self.image_enabled = bool(cloudflare_api_token and cloudflare_account_id)
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_anon_key = supabase_anon_key
        self.supabase_service_key = supabase_service_key
        self.rag_embedding_model = rag_embedding_model
        self.rag_match_count = rag_match_count
        self.rag_similarity_threshold = rag_similarity_threshold
        self.rag_enabled = rag_enabled and bool(
            self.supabase_url and self.supabase_service_key and cloudflare_api_token and cloudflare_account_id
        )
        self.histories: dict[int, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=history_messages))
        self.recent_documents: dict[int, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=MAX_RECENT_DOCUMENTS_PER_CHAT)
        )
        self.chat_memory: dict[str, list[str]] = {}
        self.profile_text = ""
        self.knowledge_text = ""
        self.recent_db_text = ""
        self.examples: list[dict[str, str]] = []
        self.username = ""
        self.reload_tuning()
        self.load_memory()

    def telegram_url(self, method: str) -> str:
        return TELEGRAM_API.format(token=self.telegram_token, method=method)

    def telegram_call(self, method: str, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        data = post_json(self.telegram_url(method), payload, timeout=timeout)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data

    def get_me(self) -> dict[str, Any]:
        data = self.telegram_call("getMe", {})
        result = data["result"]
        self.username = result.get("username", "")
        return result

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": 50,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        return self.telegram_call("getUpdates", payload, timeout=65)["result"]

    def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        for chunk in split_message(text or "Пустой ответ от модели."):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if reply_to_message_id is not None:
                payload["reply_parameters"] = {"message_id": reply_to_message_id}
            self.telegram_call("sendMessage", payload)

    def send_typing(self, chat_id: int) -> None:
        try:
            self.telegram_call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception as exc:
            logging.warning("Could not send typing action: %s", exc)

    def send_upload_photo(self, chat_id: int) -> None:
        try:
            self.telegram_call("sendChatAction", {"chat_id": chat_id, "action": "upload_photo"}, timeout=10)
        except Exception as exc:
            logging.warning("Could not send upload_photo action: %s", exc)

    def send_photo_bytes(
        self,
        chat_id: int,
        image_bytes: bytes,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> None:
        fields: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            fields["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            fields["reply_parameters"] = json.dumps({"message_id": reply_to_message_id}, ensure_ascii=False)

        data = post_multipart(
            self.telegram_url("sendPhoto"),
            fields=fields,
            files={"photo": ("image.png", image_bytes, "image/png")},
            timeout=90,
        )
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")

    def generate_image(self, prompt: str) -> bytes:
        if not self.image_enabled:
            raise RuntimeError(
                "Cloudflare image generation is not fully configured. "
                "Add CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to .env."
            )

        payload = {
            "prompt": prompt,
            "width": self.cloudflare_image_width,
            "height": self.cloudflare_image_height,
            "num_steps": self.cloudflare_image_num_steps,
            "guidance": self.cloudflare_image_guidance,
        }

        run_url = (
            f"{CLOUDFLARE_API_BASE}/accounts/{self.cloudflare_account_id}"
            f"/ai/run/{self.cloudflare_image_model}"
        )
        image_bytes, content_type = post_binary(
            run_url,
            payload,
            headers={"Authorization": f"Bearer {self.cloudflare_api_token}"},
            timeout=180,
        )

        if not content_type.startswith("image/"):
            preview = image_bytes[:1000].decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloudflare did not return an image. Content-Type: {content_type}. Body: {preview}")

        return image_bytes

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.cloudflare_api_token or not self.cloudflare_account_id:
            raise RuntimeError("Cloudflare embeddings are not configured.")

        run_url = (
            f"{CLOUDFLARE_API_BASE}/accounts/{self.cloudflare_account_id}"
            f"/ai/run/{self.rag_embedding_model}"
        )
        data = post_json(
            run_url,
            {"text": texts},
            headers={"Authorization": f"Bearer {self.cloudflare_api_token}"},
            timeout=120,
        )
        embeddings = data.get("result", {}).get("data")
        if not isinstance(embeddings, list):
            raise RuntimeError(f"Unexpected Cloudflare embedding response: {data}")
        return embeddings

    def supabase_headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.supabase_service_key,
            "Authorization": f"Bearer {self.supabase_service_key}",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def supabase_rest_url(self, path: str) -> str:
        return f"{self.supabase_url}/rest/v1/{path.lstrip('/')}"

    def ensure_rag_ready(self) -> None:
        if not self.rag_enabled:
            raise RuntimeError("Supabase RAG is not configured. Check SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and Cloudflare settings.")

    def save_rag_chunks(
        self,
        source_name: str,
        file_unique_id: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> int:
        self.ensure_rag_ready()
        if len(chunks) != len(embeddings):
            raise RuntimeError("Chunk and embedding counts do not match.")

        safe_file_id = parse.quote(file_unique_id, safe="")
        request_json(
            "DELETE",
            self.supabase_rest_url(f"rag_chunks?file_unique_id=eq.{safe_file_id}"),
            headers=self.supabase_headers(),
            timeout=60,
        )

        rows = []
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            rows.append(
                {
                    "source_name": source_name,
                    "file_unique_id": file_unique_id,
                    "chunk_index": index,
                    "content": chunk,
                    "embedding": vector_to_pgvector(embedding),
                    "metadata": {"source": "telegram_document"},
                }
            )

        for start in range(0, len(rows), 50):
            request_json(
                "POST",
                self.supabase_rest_url("rag_chunks"),
                rows[start : start + 50],
                headers=self.supabase_headers("return=minimal"),
                timeout=120,
            )
        return len(rows)

    def search_rag(self, query: str) -> list[dict[str, Any]]:
        if not self.rag_enabled:
            return []
        query_embedding = self.embed_texts([query])[0]
        payload = {
            "query_embedding": vector_to_pgvector(query_embedding),
            "match_count": self.rag_match_count,
            "similarity_threshold": self.rag_similarity_threshold,
        }
        results = request_json(
            "POST",
            self.supabase_rest_url("rpc/match_rag_chunks"),
            payload,
            headers=self.supabase_headers(),
            timeout=60,
        )
        return results if isinstance(results, list) else []

    def get_rag_chunks_by_source_name(self, source_name: str, limit: int = 8) -> list[dict[str, Any]]:
        if not self.rag_enabled:
            return []
        safe_source = parse.quote(source_name, safe="")
        select_path = "rag_chunks?select=source_name,file_unique_id,chunk_index,content"
        rows = request_json(
            "GET",
            self.supabase_rest_url(
                f"{select_path}"
                f"&source_name=eq.{safe_source}"
                f"&order=chunk_index.asc"
                f"&limit={limit}"
            ),
            headers=self.supabase_headers(),
            timeout=60,
        )
        if isinstance(rows, list) and rows:
            return rows

        safe_ilike = parse.quote(f"*{source_name}*", safe="*")
        fallback_rows = request_json(
            "GET",
            self.supabase_rest_url(
                f"{select_path}"
                f"&source_name=ilike.{safe_ilike}"
                f"&order=chunk_index.asc"
                f"&limit={limit}"
            ),
            headers=self.supabase_headers(),
            timeout=60,
        )
        return fallback_rows if isinstance(fallback_rows, list) else []

    def find_rag_chunks_by_document_names(self, document_names: list[str], limit_per_file: int = 8) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for name in document_names:
            for row in self.get_rag_chunks_by_source_name(name, limit=limit_per_file):
                key = (str(row.get("source_name", "")), int(row.get("chunk_index") or 0))
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
        return rows

    def remember_recent_document(self, chat_id: int, filename: str, file_unique_id: str, chunk_count: int) -> None:
        docs = self.recent_documents[chat_id]
        doc = {
            "source_name": filename,
            "file_unique_id": file_unique_id,
            "chunk_count": chunk_count,
            "saved_at": int(time.time()),
        }
        docs.append(doc)

    def build_recent_document_context(self, chat_id: int, query: str) -> str:
        docs = list(self.recent_documents.get(chat_id, []))
        if not docs:
            return ""

        mentioned_names = extract_document_names(query)
        target_names = mentioned_names
        if not target_names and asks_about_document(query):
            target_names = [str(docs[-1].get("source_name", ""))]

        if not target_names:
            return ""

        rows = self.find_rag_chunks_by_document_names(target_names)
        if not rows:
            available = ", ".join(str(doc.get("source_name", "unknown")) for doc in docs[-3:])
            return f"Recent uploaded documents in this chat: {available}. No exact chunks were found by filename."

        parts = [
            "Exact document context from recently uploaded Telegram files. "
            "Prefer this over guesses when the user asks what is inside a named or recent document."
        ]
        for index, row in enumerate(rows, start=1):
            source = row.get("source_name", "unknown")
            chunk_index = row.get("chunk_index", "")
            content = truncate_text(str(row.get("content", "")), 1200)
            parts.append(f"Document source {index}: {source}\nChunk: {chunk_index}\nContent: {content}")
        return truncate_text("\n\n".join(parts), MAX_RAG_CONTEXT_CHARS)

    def build_rag_context(self, query: str, chat_id: int | None = None) -> str:
        parts: list[str] = []
        mentioned_names = extract_document_names(query)

        if mentioned_names:
            rows = self.find_rag_chunks_by_document_names(mentioned_names)
            if rows:
                parts.append(
                    "Exact document context from filenames mentioned by the user. "
                    "Prefer this over guesses when answering about these files."
                )
                for index, row in enumerate(rows, start=1):
                    source = row.get("source_name", "unknown")
                    chunk_index = row.get("chunk_index", "")
                    content = truncate_text(str(row.get("content", "")), 1200)
                    parts.append(f"Named document source {index}: {source}\nChunk: {chunk_index}\nContent: {content}")

        if chat_id is not None and not mentioned_names:
            recent_context = self.build_recent_document_context(chat_id, query)
            if recent_context:
                parts.append(recent_context)

        matches = self.search_rag(query)
        if not matches:
            return truncate_text("\n\n".join(parts), MAX_RAG_CONTEXT_CHARS)

        parts.append("RAG context from Supabase vector search. Use it when relevant; do not invent beyond it.")
        for index, match in enumerate(matches, start=1):
            source = match.get("source_name", "unknown")
            similarity = match.get("similarity", "")
            content = truncate_text(str(match.get("content", "")), 1200)
            parts.append(f"RAG source {index}: {source}\nSimilarity: {similarity}\nContent: {content}")
        return truncate_text("\n\n".join(parts), MAX_RAG_CONTEXT_CHARS)

    def download_telegram_file(self, file_id: str) -> bytes:
        data = self.telegram_call("getFile", {"file_id": file_id})
        file_path = data["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{self.telegram_token}/{file_path}"
        with request.urlopen(file_url, timeout=120) as response:
            return response.read()

    def extract_document_text(self, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            return content.decode("utf-8", errors="replace")
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise RuntimeError("pypdf is not installed. Run: python -m pip install pypdf") from exc
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            return "\n\n".join(pages)
        raise RuntimeError(f"Unsupported file type: {suffix}. Send PDF, TXT, or MD.")

    def ingest_document(self, document: dict[str, Any]) -> tuple[int, str, str]:
        self.ensure_rag_ready()
        filename = document.get("file_name") or f"telegram-file-{document.get('file_unique_id', 'unknown')}"
        suffix = Path(filename).suffix.lower()
        if suffix not in RAG_SUPPORTED_EXTENSIONS:
            raise RuntimeError("Поддерживаются только PDF, TXT, MD файлы.")

        file_size = int(document.get("file_size") or 0)
        if file_size > RAG_MAX_FILE_BYTES:
            raise RuntimeError(f"Файл слишком большой. Максимум: {RAG_MAX_FILE_BYTES // (1024 * 1024)} MB.")

        content = self.download_telegram_file(document["file_id"])
        text = self.extract_document_text(filename, content)
        chunks = chunk_text(text)
        if not chunks:
            raise RuntimeError("Не удалось извлечь текст из файла.")

        embeddings: list[list[float]] = []
        for start in range(0, len(chunks), 20):
            embeddings.extend(self.embed_texts(chunks[start : start + 20]))
        file_unique_id = document.get("file_unique_id", document["file_id"])
        count = self.save_rag_chunks(filename, file_unique_id, chunks, embeddings)
        return count, filename, file_unique_id

    def reload_tuning(self) -> None:
        self.profile_text = read_optional_text(self.profile_file)
        self.knowledge_text = read_optional_text(self.knowledge_file)
        self.recent_db_text = read_optional_text(self.recent_db_file)
        self.examples = load_few_shot_examples(self.examples_file, self.few_shot_examples)
        logging.info(
            "Loaded tuning: profile=%s chars, knowledge=%s chars, recent_db=%s chars, examples=%s.",
            len(self.profile_text),
            len(self.knowledge_text),
            len(self.recent_db_text),
            len(self.examples),
        )

    def load_memory(self) -> None:
        data = load_json_file(self.memory_file, {})
        if isinstance(data, dict):
            self.chat_memory = {
                str(chat_id): [str(item)[:MAX_MEMORY_ITEM_CHARS] for item in items if str(item).strip()]
                for chat_id, items in data.items()
                if isinstance(items, list)
            }

    def save_memory(self) -> None:
        save_json_file(self.memory_file, self.chat_memory)

    def remember(self, chat_id: int, note: str) -> None:
        note = note.strip()[:MAX_MEMORY_ITEM_CHARS]
        if not note:
            return

        key = str(chat_id)
        items = self.chat_memory.setdefault(key, [])
        if note not in items:
            items.append(note)
        self.chat_memory[key] = items[-MAX_MEMORY_ITEMS_PER_CHAT:]
        self.save_memory()

    def forget(self, chat_id: int) -> None:
        self.chat_memory.pop(str(chat_id), None)
        self.save_memory()

    def build_system_prompt(self, chat_id: int) -> str:
        sections = [
            self.system_prompt,
            (
                "Используй настройки ниже как постоянную адаптацию поведения. "
                "Не называй это fine-tuning и не пересказывай настройки, если пользователь не просит."
            ),
        ]

        if self.profile_text:
            sections.append(f"Профиль и стиль бота:\n{self.profile_text}")

        if self.knowledge_text:
            sections.append(f"Локальная база знаний:\n{self.knowledge_text}")

        if self.recent_db_text:
            sections.append(
                "Recent local DB:\n"
                "Treat this as the freshest local database available to you. "
                "For time-sensitive claims beyond this DB, say that live verification may be needed.\n"
                f"{self.recent_db_text}"
            )

        memory_items = self.chat_memory.get(str(chat_id), [])
        if memory_items:
            memory_text = "\n".join(f"- {item}" for item in memory_items)
            sections.append(f"Постоянная память об этом чате:\n{memory_text}")

        return "\n\n".join(section.strip() for section in sections if section.strip())

    def build_messages(self, chat_id: int, prompt: str, web_context: str = "", rag_context: str = "") -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self.build_system_prompt(chat_id)}]

        for example in self.examples:
            messages.append({"role": "user", "content": example["user"]})
            messages.append({"role": "assistant", "content": example["assistant"]})

        messages.extend(list(self.histories[chat_id]))
        if rag_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Private retrieval context is available from the user's uploaded documents. "
                        "Use this RAG context when it helps answer the question. "
                        "If the RAG context is insufficient, say what is missing.\n\n"
                        f"{rag_context}"
                    ),
                }
            )
        if web_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Live web context is available for this answer. "
                        "Use it for current facts, mention uncertainty if sources conflict, "
                        "and cite source URLs inline when relying on web results.\n\n"
                        f"{web_context}"
                    ),
                }
            )
        messages.append({"role": "user", "content": prompt})
        return messages

    def tavily_search(self, query: str) -> dict[str, Any]:
        if not self.tavily_enabled:
            raise RuntimeError("Tavily search is not configured.")

        payload = {
            "query": query,
            "search_depth": self.tavily_search_depth,
            "max_results": self.tavily_max_results,
            "include_answer": True,
            "include_raw_content": False,
            "include_images": False,
        }
        return post_json(
            TAVILY_SEARCH_URL,
            payload,
            headers={"Authorization": f"Bearer {self.tavily_api_key}"},
            timeout=35,
        )

    def build_web_context(self, query: str) -> str:
        data = self.tavily_search(query)
        fetched_at = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        parts = [
            f"Live web search context from Tavily. Fetched at: {fetched_at}.",
            "Use this context for current facts. Cite URLs when using web results.",
        ]

        answer = str(data.get("answer", "")).strip()
        if answer:
            parts.append(f"Tavily answer summary:\n{truncate_text(answer, 1200)}")

        results = data.get("results", [])
        if isinstance(results, list):
            for index, result in enumerate(results, start=1):
                if not isinstance(result, dict):
                    continue
                title = str(result.get("title", "")).strip() or "Untitled"
                url = str(result.get("url", "")).strip()
                content = str(result.get("content", "") or result.get("raw_content", "")).strip()
                score = result.get("score", "")
                result_text = (
                    f"Source {index}: {title}\n"
                    f"URL: {url}\n"
                    f"Score: {score}\n"
                    f"Snippet: {truncate_text(content, 900)}"
                )
                parts.append(result_text)

        return truncate_text("\n\n".join(parts), MAX_WEB_CONTEXT_CHARS)

    def call_groq(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 90,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_completion_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }

        data = post_json(
            GROQ_CHAT_COMPLETIONS_URL,
            payload,
            headers={"Authorization": f"Bearer {self.groq_api_key}"},
            timeout=timeout,
        )

        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Groq response: {data}") from exc

    def build_ground_check(
        self,
        chat_id: int,
        prompt: str,
        answer: str,
        web_context: str = "",
        rag_context: str = "",
    ) -> str:
        context_parts = []
        if web_context:
            context_parts.append(f"Live web context:\n{web_context[:3000]}")
        if rag_context:
            context_parts.append(f"RAG context:\n{rag_context[:3000]}")
        if self.knowledge_text:
            context_parts.append(f"Knowledge base:\n{self.knowledge_text[:3000]}")
        if self.recent_db_text:
            context_parts.append(f"Recent DB:\n{self.recent_db_text[:3000]}")
        memory_items = self.chat_memory.get(str(chat_id), [])
        if memory_items:
            context_parts.append("Chat memory:\n" + "\n".join(f"- {item}" for item in memory_items[-10:]))

        context = "\n\n".join(context_parts) or "No local knowledge, recent DB, or saved chat memory was available."
        auditor_messages = [
            {
                "role": "system",
                "content": (
                    "You are a private internal grounding auditor for a Telegram chatbot. "
                    "Do not reveal private chain-of-thought. Do not solve the user's task again. "
                    "Return a concise internal verification only for the next model step. "
                    "Check whether the answer is supported by the user prompt, conversation context, local knowledge, recent DB, or general stable knowledge. "
                    "If the answer includes time-sensitive facts and no recent DB evidence is available, flag that live verification may be needed. "
                    "Use this exact format:\n"
                    "- Basis: ...\n"
                    "- Assumptions / gaps: ...\n"
                    "- Freshness: ...\n"
                    "- Confidence: High/Medium/Low"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User prompt:\n{prompt}\n\n"
                    f"Assistant answer:\n{answer}\n\n"
                    f"Available local context:\n{context}"
                ),
            },
        ]
        return self.call_groq(
            auditor_messages,
            max_tokens=self.ground_check_max_tokens,
            temperature=0.0,
            timeout=60,
        )

    def revise_with_ground_check(self, prompt: str, draft_answer: str, ground_check: str) -> str:
        revision_messages = [
            {
                "role": "system",
                "content": (
                    "You are the final response editor for a Telegram chatbot. "
                    "Use the private grounding audit to correct the draft answer if needed. "
                    "Return only the final user-facing answer. "
                    "Do not mention ground check, internal audit, hidden reasoning, or confidence labels. "
                    "Keep the user's language and keep the answer concise."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User prompt:\n{prompt}\n\n"
                    f"Draft answer:\n{draft_answer}\n\n"
                    f"Private grounding audit:\n{ground_check}\n\n"
                    "Produce the final answer only."
                ),
            },
        ]
        return self.call_groq(
            revision_messages,
            max_tokens=self.max_tokens,
            temperature=0.2,
            timeout=90,
        )

    def build_private_reasoning_pass(
        self,
        prompt: str,
        draft_answer: str,
        web_context: str,
        rag_context: str,
        role_name: str,
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are one private reasoning pass inside a Telegram chatbot. "
                    "Do not reveal hidden chain-of-thought. Do not write the final answer. "
                    "Give a concise internal review only: useful evidence, possible mistakes, missing context, and recommended correction. "
                    f"Perspective: {role_name}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User prompt:\n{prompt}\n\n"
                    f"Draft answer:\n{draft_answer}\n\n"
                    f"RAG context:\n{rag_context or 'none'}\n\n"
                    f"Web context:\n{web_context or 'none'}"
                ),
            },
        ]
        return self.call_groq(
            messages,
            max_tokens=self.multi_chain_max_tokens,
            temperature=0.15,
            timeout=60,
        )

    def revise_with_multi_chain(
        self,
        prompt: str,
        draft_answer: str,
        private_reviews: list[str],
        ground_check: str = "",
    ) -> str:
        reviews_text = "\n\n".join(
            f"Private pass {index}:\n{review}" for index, review in enumerate(private_reviews, start=1)
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the final response synthesizer for a Telegram chatbot. "
                    "Use the private reasoning passes and optional grounding audit to improve the answer. "
                    "Return only the final user-facing answer. "
                    "Do not mention private passes, chain-of-thought, internal audit, or confidence labels. "
                    "Keep the user's language and keep the answer practical."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User prompt:\n{prompt}\n\n"
                    f"Draft answer:\n{draft_answer}\n\n"
                    f"Private reasoning passes:\n{reviews_text or 'none'}\n\n"
                    f"Private grounding audit:\n{ground_check or 'none'}\n\n"
                    "Produce the final answer only."
                ),
            },
        ]
        return self.call_groq(messages, max_tokens=self.max_tokens, temperature=0.2, timeout=90)

    def ask_groq(self, chat_id: int, prompt: str, force_web: bool = False, force_multi_chain: bool = False) -> str:
        history = self.histories[chat_id]
        web_context = ""
        rag_context = ""
        wants_web = force_web or (self.tavily_auto_search and should_use_web_search(prompt))
        wants_multi_chain = force_multi_chain or (self.multi_chain_enabled and should_use_multi_chain(prompt))

        if self.rag_enabled:
            try:
                rag_context = self.build_rag_context(prompt, chat_id=chat_id)
            except Exception:
                logging.exception("RAG search failed")

        if self.tavily_enabled and wants_web:
            try:
                web_context = self.build_web_context(prompt)
                logging.info("Tavily search used for chat_id=%s.", chat_id)
            except Exception as exc:
                logging.exception("Tavily search failed")
                if force_web:
                    web_context = (
                        "Live web search was requested, but Tavily search failed. "
                        f"Error: {exc}. Tell the user that live verification failed."
                    )

        answer = self.call_groq(self.build_messages(chat_id, prompt, web_context=web_context, rag_context=rag_context))
        final_answer = answer
        ground_check = ""

        private_reviews: list[str] = []
        if wants_multi_chain:
            roles = [
                "logic and completeness reviewer",
                "evidence and grounding reviewer",
                "practical usefulness reviewer",
                "risk and edge-case reviewer",
            ]
            for role_name in roles[: self.multi_chain_count]:
                try:
                    private_reviews.append(
                        self.build_private_reasoning_pass(prompt, answer, web_context, rag_context, role_name)
                    )
                except Exception:
                    logging.exception("Multi-chain reasoning pass failed")

        if self.ground_check_enabled:
            try:
                ground_check = self.build_ground_check(
                    chat_id,
                    prompt,
                    answer,
                    web_context=web_context,
                    rag_context=rag_context,
                )
            except Exception:
                logging.exception("Ground check failed")
                ground_check = ""

        if private_reviews:
            try:
                final_answer = self.revise_with_multi_chain(prompt, answer, private_reviews, ground_check=ground_check)
            except Exception:
                logging.exception("Multi-chain synthesis failed")
                final_answer = answer
        elif ground_check:
            final_answer = self.revise_with_ground_check(prompt, answer, ground_check)

        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": final_answer})
        return final_answer

    def command_reply(self, chat_id: int, message_id: int, text: str) -> bool:
        command = normalize_command(text)

        if command == "/start":
            self.send_message(
                chat_id,
                "Привет! Напиши мне вопрос, и я отвечу через Groq AI.\n\n"
                "Команды: /help, /reset, /model",
                message_id,
            )
            return True

        if command == "/help":
            self.send_message(
                chat_id,
                "Я отвечаю на обычные сообщения в личном чате.\n\n"
                "Для картинки просто напиши обычным текстом: сгенерируй кота в космосе.\n"
                "/reset - очистить историю диалога\n"
                "/model - показать текущую модель\n"
                "/ask текст - задать вопрос в группе",
                message_id,
            )
            return True

        if command == "/reset":
            self.histories.pop(chat_id, None)
            self.send_message(chat_id, "История диалога очищена.", message_id)
            return True

        if command == "/model":
            self.send_message(chat_id, f"Текущая модель Groq: {self.model}", message_id)
            return True

        if command == "/tuning":
            memory_count = len(self.chat_memory.get(str(chat_id), []))
            self.send_message(
                chat_id,
                "Статус настройки бота:\n"
                f"- профиль: {len(self.profile_text)} символов\n"
                f"- база знаний: {len(self.knowledge_text)} символов\n"
                f"- few-shot примеры: {len(self.examples)}\n"
                f"- память этого чата: {memory_count} записей",
                message_id,
            )
            return True

        if command == "/reload":
            self.reload_tuning()
            self.load_memory()
            self.send_message(chat_id, "Настройки перезагружены.", message_id)
            return True

        if command == "/remember":
            note = command_argument(text)
            if not note:
                self.send_message(chat_id, "Напиши так: /remember что нужно запомнить", message_id)
                return True
            self.remember(chat_id, note)
            self.send_message(chat_id, "Запомнил для этого чата.", message_id)
            return True

        if command == "/memory":
            items = self.chat_memory.get(str(chat_id), [])
            if not items:
                self.send_message(chat_id, "Постоянная память этого чата пока пуста.", message_id)
                return True
            memory_text = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
            self.send_message(chat_id, f"Память этого чата:\n{memory_text}", message_id)
            return True

        if command == "/forget":
            self.forget(chat_id)
            self.send_message(chat_id, "Постоянная память этого чата очищена.", message_id)
            return True

        if command == "/commands":
            self.send_message(
                chat_id,
                "Команды:\n"
                "/start - запуск\n"
                "/help - помощь\n"
                "/reset - очистить историю\n"
                "/model - текущая модель\n"
                "/tuning - статус настройки\n"
                "/reload - перечитать настройки\n"
                "/remember текст - запомнить факт\n"
                "/memory - показать память\n"
                "/forget - очистить память\n"
                "/web текст - поиск в интернете\n"
                "/search текст - поиск в интернете\n"
                "/rag - статус RAG/Supabase\n"
                "/rag_search текст - поиск по загруженным PDF/TXT/MD\n"
                "/ask текст - вопрос в группе",
                message_id,
            )
            return True

        if command == "/rag":
            self.send_message(
                chat_id,
                "RAG/Supabase:\n"
                f"- enabled: {'yes' if self.rag_enabled else 'no'}\n"
                f"- url: {'set' if self.supabase_url else 'missing'}\n"
                f"- service key: {'set' if self.supabase_service_key else 'missing'}\n"
                f"- embedding model: {self.rag_embedding_model}\n\n"
                "Чтобы добавить знания, отправь PDF/TXT/MD файл прямо в этот чат.",
                message_id,
            )
            return True

        if command == "/rag_search":
            query = command_argument(text)
            if not query:
                self.send_message(chat_id, "Напиши так: /rag_search что искать в документах", message_id)
                return True
            try:
                matches = self.search_rag(query)
            except Exception as exc:
                logging.exception("RAG search command failed")
                self.send_message(chat_id, f"RAG search не сработал.\n\nОшибка: {exc}", message_id)
                return True
            if not matches:
                self.send_message(chat_id, "Ничего не нашёл в RAG базе.", message_id)
                return True
            lines = []
            for index, match in enumerate(matches, start=1):
                lines.append(
                    f"{index}. {match.get('source_name', 'unknown')} | similarity={match.get('similarity')}\n"
                    f"{truncate_text(str(match.get('content', '')), 700)}"
                )
            self.send_message(chat_id, "\n\n".join(lines), message_id)
            return True

        if command in {"/web", "/search"}:
            query = command_argument(text)
            if not query:
                self.send_message(chat_id, "Напиши так: /web что нужно найти в интернете", message_id)
                return True
            self.send_typing(chat_id)
            try:
                answer = self.ask_groq(chat_id, query, force_web=True)
            except Exception as exc:
                logging.exception("Web answer failed")
                self.send_message(chat_id, f"Не получилось ответить с web search.\n\nОшибка: {exc}", message_id)
                return True
            self.send_message(chat_id, answer, message_id)
            return True

        return False

    def extract_prompt(self, message: dict[str, Any]) -> str | None:
        text = (message.get("text") or "").strip()
        if not text:
            return None

        chat_type = message.get("chat", {}).get("type", "private")
        if chat_type == "private":
            return text

        lower_text = text.lower()
        mention = f"@{self.username.lower()}" if self.username else ""

        if normalize_command(text) == "/ask":
            parts = text.split(maxsplit=1)
            return parts[1].strip() if len(parts) > 1 else "Привет! Чем можешь помочь?"

        if mention and mention in lower_text:
            return text.replace(f"@{self.username}", "").strip() or "Привет! Чем можешь помочь?"

        return None

    def handle_message(self, message: dict[str, Any]) -> None:
        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        text = (message.get("text") or "").strip()
        caption = (message.get("caption") or "").strip()

        document = message.get("document")
        if document:
            self.send_typing(chat_id)
            try:
                count, filename, file_unique_id = self.ingest_document(document)
                self.remember_recent_document(chat_id, filename, file_unique_id, count)
                self.histories[chat_id].append(
                    {
                        "role": "user",
                        "content": f"Я отправил документ {filename}. Подпись к файлу: {caption or 'без подписи'}.",
                    }
                )
                self.histories[chat_id].append(
                    {
                        "role": "assistant",
                        "content": f"Файл {filename} добавлен в RAG. В нём {count} chunks.",
                    }
                )
                if caption:
                    answer = self.ask_groq(chat_id, caption)
                    self.send_message(chat_id, f"Файл добавлен в RAG: {filename}\nChunks: {count}\n\n{answer}", message_id)
                else:
                    self.send_message(chat_id, f"Файл добавлен в RAG: {filename}\nChunks: {count}", message_id)
            except Exception as exc:
                logging.exception("Document ingest failed")
                self.send_message(chat_id, f"Не получилось добавить файл в RAG.\n\nОшибка: {exc}", message_id)
            return

        if text.startswith("/") and self.command_reply(chat_id, message_id, text):
            return

        prompt = self.extract_prompt(message)
        if not prompt:
            return

        if is_image_generation_request(prompt):
            image_prompt = extract_image_prompt(prompt)
            self.send_upload_photo(chat_id)
            try:
                image_bytes = self.generate_image(image_prompt)
                self.send_photo_bytes(chat_id, image_bytes, caption=image_prompt, reply_to_message_id=message_id)
                self.histories[chat_id].append({"role": "user", "content": prompt})
                self.histories[chat_id].append(
                    {"role": "assistant", "content": f"Сгенерировал изображение по описанию: {image_prompt}"}
                )
            except Exception as exc:
                logging.exception("Natural image generation failed")
                self.send_message(chat_id, f"Не получилось сгенерировать картинку.\n\nОшибка: {exc}", message_id)
            return

        self.send_typing(chat_id)

        try:
            answer = self.ask_groq(chat_id, prompt)
        except Exception as exc:
            logging.exception("Groq request failed")
            self.send_message(
                chat_id,
                "Не получилось получить ответ от Groq. Проверь API key, лимиты аккаунта и название модели.\n\n"
                f"Ошибка: {exc}",
                message_id,
            )
            return

        self.send_message(chat_id, answer, message_id)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if message:
            self.handle_message(message)


def main() -> int:
    setup_logging()
    load_env()

    telegram_token = require_env("TELEGRAM_BOT_TOKEN")
    groq_api_key = require_env("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    system_prompt = os.getenv(
        "BOT_SYSTEM_PROMPT",
        "Ты полезный ИИ-ассистент в Telegram. Отвечай ясно, по делу и на языке пользователя.",
    ).strip()
    temperature = env_float("GROQ_TEMPERATURE", 0.7)
    max_tokens = env_int("GROQ_MAX_TOKENS", 1200)
    history_messages = env_int("BOT_HISTORY_MESSAGES", 20)
    profile_file = Path(os.getenv("BOT_PROFILE_FILE", "bot_profile.md").strip())
    knowledge_file = Path(os.getenv("BOT_KNOWLEDGE_FILE", "bot_knowledge.md").strip())
    recent_db_file = Path(os.getenv("BOT_RECENT_DB_FILE", "recent_db.md").strip())
    examples_file = Path(os.getenv("BOT_EXAMPLES_FILE", "training_examples.jsonl").strip())
    memory_file = Path(os.getenv("BOT_MEMORY_FILE", "data/chat_memory.json").strip())
    few_shot_examples = env_int("BOT_FEW_SHOT_EXAMPLES", 6)
    ground_check_enabled = env_bool("BOT_GROUND_CHECK", True)
    ground_check_max_tokens = env_int("BOT_GROUND_CHECK_MAX_TOKENS", 220)
    multi_chain_enabled = env_bool("BOT_MULTI_CHAIN_REASONING", True)
    multi_chain_count = env_int("BOT_MULTI_CHAIN_COUNT", 3)
    multi_chain_max_tokens = env_int("BOT_MULTI_CHAIN_MAX_TOKENS", 260)
    tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()
    tavily_enabled = env_bool("TAVILY_SEARCH_ENABLED", bool(tavily_api_key))
    tavily_auto_search = env_bool("TAVILY_AUTO_SEARCH", True)
    tavily_search_depth = os.getenv("TAVILY_SEARCH_DEPTH", "advanced").strip() or "advanced"
    tavily_max_results = env_int("TAVILY_MAX_RESULTS", 5)
    cloudflare_api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    cloudflare_account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    cloudflare_image_model = os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/stabilityai/stable-diffusion-xl-base-1.0").strip()
    cloudflare_image_width = env_int("CLOUDFLARE_IMAGE_WIDTH", 1024)
    cloudflare_image_height = env_int("CLOUDFLARE_IMAGE_HEIGHT", 1024)
    cloudflare_image_num_steps = env_int("CLOUDFLARE_IMAGE_NUM_STEPS", 20)
    cloudflare_image_guidance = env_float("CLOUDFLARE_IMAGE_GUIDANCE", 7.5)
    supabase_url = os.getenv("SUPABASE_URL", "https://qvhfyblwlqvayvkipckd.supabase.co").strip()
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    rag_enabled = env_bool("RAG_ENABLED", True)
    rag_embedding_model = os.getenv("RAG_EMBEDDING_MODEL", "@cf/baai/bge-small-en-v1.5").strip()
    rag_match_count = env_int("RAG_MATCH_COUNT", 5)
    rag_similarity_threshold = env_float("RAG_SIMILARITY_THRESHOLD", 0.25)

    bot = TelegramGroqBot(
        telegram_token=telegram_token,
        groq_api_key=groq_api_key,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        history_messages=history_messages,
        profile_file=profile_file,
        knowledge_file=knowledge_file,
        recent_db_file=recent_db_file,
        examples_file=examples_file,
        memory_file=memory_file,
        few_shot_examples=few_shot_examples,
        ground_check_enabled=ground_check_enabled,
        ground_check_max_tokens=ground_check_max_tokens,
        multi_chain_enabled=multi_chain_enabled,
        multi_chain_count=multi_chain_count,
        multi_chain_max_tokens=multi_chain_max_tokens,
        tavily_api_key=tavily_api_key,
        tavily_enabled=tavily_enabled,
        tavily_auto_search=tavily_auto_search,
        tavily_search_depth=tavily_search_depth,
        tavily_max_results=tavily_max_results,
        cloudflare_api_token=cloudflare_api_token,
        cloudflare_account_id=cloudflare_account_id,
        cloudflare_image_model=cloudflare_image_model,
        cloudflare_image_width=cloudflare_image_width,
        cloudflare_image_height=cloudflare_image_height,
        cloudflare_image_num_steps=cloudflare_image_num_steps,
        cloudflare_image_guidance=cloudflare_image_guidance,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
        supabase_service_key=supabase_service_key,
        rag_enabled=rag_enabled,
        rag_embedding_model=rag_embedding_model,
        rag_match_count=rag_match_count,
        rag_similarity_threshold=rag_similarity_threshold,
    )

    me = bot.get_me()
    username = me.get("username", "unknown")
    logging.info("Bot @%s started. Press Ctrl+C to stop.", username)

    offset: int | None = None
    while True:
        try:
            updates = bot.get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                bot.handle_update(update)
        except KeyboardInterrupt:
            logging.info("Stopped.")
            return 0
        except Exception as exc:
            logging.exception("Polling error: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
