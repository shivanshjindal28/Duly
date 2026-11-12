"""AI extraction path with a mocked Claude call: merge rules, cache, fallback, provenance."""
from __future__ import annotations

import copy

import pytest

from app.ai import claude_extractor
from app.ai.claude_extractor import AIUnavailable, numbered_lines
from app.ai.extract import extract, merge
from app.ai.offline_parser import parse
from app.ai.schema import HEADER_FIELDS, LINE_FIELDS
from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.ingestion.extract_text import acquire_tokens
from app.ingestion.tokens import group_lines
from app.samples.invoice_pdf import render_invoice_pdf
from tests.fixtures.invoices import bearings_invoice, seeded_invoice

CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    limiter.reset()
    monkeypatch.setattr(claude_extractor, "CACHE_DIR", tmp_path / "ai_cache")


def canned_response(pdf: bytes, confidence: float = 0.95) -> dict:
    """What a correct Claude answer looks like for this PDF (built from the exact text layer)."""
    tokens, method = acquire_tokens(pdf, "pdf")
    det = parse(tokens, method)
    _, ids = numbered_lines(group_lines(tokens))
    line_of = {}
    for lid, ln in ids.items():
        if "Invoice No" in ln.text:
            line_of["invoice_number"] = lid

    def f(field, name):
        return {"value": field.value, "confidence": confidence if field.value else 0.0, "line": line_of.get(name)}

    return {
        "header": {n: f(det.header[n], n) for n in HEADER_FIELDS},
        "lines": [{n: f(ln[n], n) for n in LINE_FIELDS} for ln in det.lines],
        "suspicious_text": None,
        "_model_served": "claude-sonnet-5-5",
    }


@pytest.fixture
def pdf() -> bytes:
    return render_invoice_pdf(bearings_invoice())


def test_offline_by_default_without_key(pdf):
    tokens, method = acquire_tokens(pdf, "pdf")
    ex, mode, reason, _quarantined = extract("abc", tokens, method, lambda: [])
    assert mode == "offline" and reason is None and ex.extractor == "offline-regex"


def test_agreement_raises_confidence_and_boxes_come_from_cited_line(pdf):
    tokens, method = acquire_tokens(pdf, "pdf")
    det = parse(tokens, method)
    _, ids = numbered_lines(group_lines(tokens))
    ai = canned_response(pdf, confidence=0.99)
    ex = merge(ai, det, ids, "claude-sonnet-5-5")
    f = ex.header["invoice_number"]
    assert f.value == "KES/26-27/0042" and f.source == "ai" and f.confidence == 0.99 and f.bbox
    assert ex.extractor == "claude-sonnet-5-5" and ex.extractor_version.startswith("extract-v")
    assert len(ex.lines) == 2


def test_disagreement_forces_review_and_keeps_pdf_text(pdf):
    tokens, method = acquire_tokens(pdf, "pdf")
    det = parse(tokens, method)
    _, ids = numbered_lines(group_lines(tokens))
    ai = canned_response(pdf)
    ai["header"]["total"]["value"] = "78320.00"  # model misread a digit
    ex = merge(ai, det, ids, "claude-sonnet-5-5")
    total = ex.header["total"]
    assert total.value == "87320.00"  # exact PDF text wins
    assert total.confidence < 0.85  # below threshold -> a human checks it
    ai["lines"][0]["qty"]["value"] = " 100.000 "  # formatting noise is normalised, not a disagreement
    assert merge(ai, det, ids, "m").lines[0]["qty"].confidence >= 0.95


def test_live_then_cached_upload(client, db, monkeypatch):
    calls = []
    spec = seeded_invoice(db, invoice_number="KES/AI/001")
    file = render_invoice_pdf(spec)
    canned = canned_response(file)

    def fake_call(images, lines_text, model):
        calls.append((len(images), "L1 p1:" in lines_text, model))
        return copy.deepcopy(canned)

    monkeypatch.setattr(claude_extractor, "call_claude", fake_call)
    monkeypatch.setattr(get_settings(), "ai_mode", "live")
    assert client.post("/api/auth/demo-login", json={"email": CLERK}).status_code == 200
    h = {"X-CSRF-Token": client.cookies.get("duly_csrf")}

    first = client.post("/api/invoices/upload", headers=h, files={"file": ("a.pdf", file, "application/pdf")}).json()
    assert first["ai_mode"] == "live" and calls == [(1, True, get_settings().anthropic_model)]
    assert any(f["source"] == "ai" for f in first["fields"])
    # The decision is still the rules engine's, unchanged by the AI path.
    assert first["match"]["decision"] == "BLOCK" and first["match"]["engine_version"].startswith("engine")

    second = client.post("/api/invoices/upload", headers=h, files={"file": ("a.pdf", file, "application/pdf")}).json()
    assert second["ai_mode"] == "cached" and len(calls) == 1  # same file: served from the cache


def test_ai_failure_falls_back_to_offline(pdf, monkeypatch):
    def boom(*a, **k):
        raise AIUnavailable("AI not reachable (offline?)")

    monkeypatch.setattr(claude_extractor, "call_claude", boom)
    monkeypatch.setattr(get_settings(), "ai_mode", "live")
    tokens, method = acquire_tokens(pdf, "pdf")
    ex, mode, reason, _quarantined = extract("deadbeef", tokens, method, lambda: [])
    assert mode == "offline" and "not reachable" in reason and ex.extractor == "offline-regex"


def test_cached_mode_never_calls_the_api(pdf, monkeypatch):
    monkeypatch.setattr(claude_extractor, "call_claude", lambda *a, **k: pytest.fail("network call in cached mode"))
    monkeypatch.setattr(get_settings(), "ai_mode", "cached")
    tokens, method = acquire_tokens(pdf, "pdf")
    ex, mode, reason, _quarantined = extract("nocache", tokens, method, lambda: [])
    assert mode == "offline" and "No cached" in reason


def test_unexpected_ai_error_falls_back_to_offline(monkeypatch):
    """A misconfigured client (e.g. no key reaching it) must never fail an upload."""
    def broken(images, lines_text, model):
        raise TypeError("Could not resolve authentication method")

    monkeypatch.setattr(claude_extractor, "call_claude", broken)
    monkeypatch.setattr(get_settings(), "ai_mode", "live")
    pdf = render_invoice_pdf(bearings_invoice())
    tokens, method = acquire_tokens(pdf, "pdf")
    ex, mode, reason, quarantined = extract("sha-broken", tokens, method, lambda: [])
    assert mode == "offline" and reason == "AI error (TypeError)" and quarantined is None
    assert ex.header["invoice_number"].value == "KES/26-27/0042"


def test_api_key_from_settings_reaches_the_client(monkeypatch):
    """The key is read from .env by our settings, not from os.environ: it must be passed explicitly."""
    seen = {}

    class FakeClient:
        def __init__(self, **kw):
            seen.update(kw)
            raise RuntimeError("stop here")

    monkeypatch.setattr(claude_extractor.anthropic, "Anthropic", FakeClient)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test-not-real")
    with pytest.raises(RuntimeError):
        claude_extractor.call_claude([], "", "claude-sonnet-5-5")
    assert seen["api_key"] == "sk-test-not-real"
