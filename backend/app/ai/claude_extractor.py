"""Claude extraction: page images + numbered text lines in, strict JSON (structured outputs) out.

Responses are cached on disk by file SHA-256 + model + prompt version, so a demo replays the
same result (and "cached" mode needs no network at all). Any failure raises AIUnavailable and
the pipeline falls back to the offline parser; the UI badge says which path was used.
Only the invoice document is sent: never the vendor master, bank records or other suppliers.
"""
from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime

import anthropic

from app.ai.prompts.extraction import PROMPT_VERSION, SCHEMA, SYSTEM
from app.core.config import DATA_DIR, get_settings
from app.ingestion.tokens import TextLine

CACHE_DIR = DATA_DIR / "ai_cache"
MAX_PAGES_TO_SEND = 5
IMAGE_DPI = 150
# Models that accept server-side refusal fallbacks with fallbacks="default".
_FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class AIUnavailable(RuntimeError):
    """Live/cached AI extraction could not be used; caller falls back to offline."""


def _cache_path(sha256: str, model: str):
    return CACHE_DIR / f"{sha256}_{model}_{PROMPT_VERSION}.json"


def read_cache(sha256: str, model: str) -> dict | None:
    p = _cache_path(sha256, model)
    return json.loads(p.read_text(encoding="utf-8"))["response"] if p.exists() else None


def _write_cache(sha256: str, model: str, response: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(sha256, model).write_text(json.dumps({
        "model": model, "prompt_version": PROMPT_VERSION, "created_at": datetime.now(UTC).isoformat(),
        "response": response,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def numbered_lines(lines: list[TextLine]) -> tuple[str, dict[str, TextLine]]:
    ids = {f"L{i}": ln for i, ln in enumerate(lines, start=1)}
    text = "\n".join(f"{lid} p{ln.page}: {ln.text}" for lid, ln in ids.items())
    return text, ids


def _image_blocks(images) -> list[dict]:
    blocks = []
    for img in images[:MAX_PAGES_TO_SEND]:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                   "data": base64.standard_b64encode(buf.getvalue()).decode()}})
    return blocks


def call_claude(images, lines_text: str, model: str) -> dict:
    """One structured-output request. Raises AIUnavailable on any API problem or refusal."""
    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key or None, timeout=90.0, max_retries=1)
    extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in _FALLBACK_MODELS else {}
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": [
                *_image_blocks(images),
                {"type": "text", "text": "Text lines read from the document (id, page, text):\n" + lines_text},
            ]}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            **extra,
        )
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("AI credentials rejected") from e
    except anthropic.RateLimitError as e:
        raise AIUnavailable("AI rate limited") from e
    except anthropic.APIStatusError as e:
        raise AIUnavailable(f"AI API error {e.status_code}") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("AI not reachable (offline?)") from e
    if response.stop_reason == "refusal":
        raise AIUnavailable("AI declined to process this document")
    if response.stop_reason == "max_tokens":
        raise AIUnavailable("AI response was cut off")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise AIUnavailable("AI returned no JSON")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AIUnavailable("AI returned invalid JSON") from e
    data["_model_served"] = response.model
    return data


def extract_with_claude(sha256: str, images, lines: list[TextLine], mode: str) -> tuple[dict, str, dict[str, TextLine]]:
    """Return (raw response, ai_mode used: 'live' | 'cached', line-id map)."""
    model = get_settings().anthropic_model
    lines_text, ids = numbered_lines(lines)
    cached = read_cache(sha256, model)
    if cached is not None:
        return cached, "cached", ids
    if mode == "cached":
        raise AIUnavailable("No cached AI result for this file")
    data = call_claude(images, lines_text, model)
    _write_cache(sha256, model, data)
    return data, "live", ids
