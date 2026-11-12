"""Server-side use of the same reviewed translation files the frontend uses (en / hi).

One source of truth for supplier-facing text: frontend/src/i18n/{en,hi}.json. Supports
{{var}} interpolation and i18next-style plurals (key_one / key_other with `count`).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from app.core.config import REPO_ROOT

LANGS = ("en", "hi")


@lru_cache(maxsize=2)
def _bundle(lang: str) -> dict:
    path = REPO_ROOT / "frontend" / "src" / "i18n" / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _lookup(data: dict, key: str):
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def t(lang: str, key: str, **params) -> str:
    lang = lang if lang in LANGS else "en"
    data = _bundle(lang)
    if "count" in params:
        plural = _lookup(data, f"{key}_{'one' if params['count'] == 1 else 'other'}")
        text = plural if isinstance(plural, str) else _lookup(data, key)
    else:
        text = _lookup(data, key)
    if not isinstance(text, str):
        text = _lookup(_bundle("en"), key) if lang != "en" else None
    if not isinstance(text, str):
        return key
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(params.get(m.group(1), m.group(0))), text)


def exists(lang: str, key: str) -> bool:
    return isinstance(_lookup(_bundle(lang if lang in LANGS else "en"), key), str)
