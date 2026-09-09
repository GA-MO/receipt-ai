"""Model routing: the fallback list handed to OpenRouter.

A retired model must not take the whole pipeline down — OpenRouter walks the
`models` list when one is unavailable, and the 2026-09 sweep showed the
candidates are interchangeable on accuracy, so falling through costs nothing.
"""

import pytest

from app.config import settings
from app.services import llm_client
from app.services.llm_client import generate_json, model_routing_list


def _with(primary, fallbacks, fn):
    old = (settings.openrouter_model, settings.openrouter_fallback_models)
    settings.openrouter_model, settings.openrouter_fallback_models = primary, fallbacks
    try:
        return fn()
    finally:
        settings.openrouter_model, settings.openrouter_fallback_models = old


def test_primary_comes_first():
    got = _with("a/one", "b/two,c/three", model_routing_list)
    assert got == ["a/one", "b/two", "c/three"]


def test_default_primary_is_not_a_preview():
    # A missing .env must not silently drop the app onto a preview model.
    assert "preview" not in type(settings)().openrouter_model


def test_duplicate_and_blank_entries_dropped():
    got = _with("a/one", " b/two , a/one ,, ", model_routing_list)
    assert got == ["a/one", "b/two"]


def test_empty_fallbacks_give_single_entry():
    assert _with("a/one", "", model_routing_list) == ["a/one"]


def _fake_call(monkeypatch, behaviour):
    """Replace the HTTP call; record which models were asked for."""
    seen: list[str] = []

    def fake(model, routing, *args, **kw):
        seen.append(model)
        return behaviour(model)

    monkeypatch.setattr(llm_client, "_generate_json_openrouter", fake)
    monkeypatch.setattr(llm_client.settings, "llm_retry_delay", 0)
    return seen


def test_retired_primary_falls_through_to_next_model(monkeypatch):
    def behaviour(model):
        if model == "a/retired":
            raise Exception("Error code: 400 - a/retired is not a valid model ID")
        return "{}"

    seen = _with("a/retired", "b/live", lambda: _fake_call(monkeypatch, behaviour))
    out = _with("a/retired", "b/live", lambda: generate_json(prompt="x"))
    assert out == "{}"
    assert seen == ["a/retired", "b/live"]


def test_retired_model_is_not_retried_before_falling_through(monkeypatch):
    # Backing off three times against a model that cannot exist only delays the
    # fallback; one attempt per model is enough.
    def behaviour(model):
        if model == "a/retired":
            raise Exception("404 model not found")
        return "{}"

    seen = _with("a/retired", "b/live", lambda: _fake_call(monkeypatch, behaviour))
    _with("a/retired", "b/live", lambda: generate_json(prompt="x"))
    assert seen.count("a/retired") == 1


def test_real_failure_does_not_walk_the_fallback_list(monkeypatch):
    # A rate limit or a bad payload must surface, not silently spend money
    # re-running the whole list.
    seen = _with("a/one", "b/two", lambda: _fake_call(
        monkeypatch, lambda model: (_ for _ in ()).throw(Exception("429 rate limited"))))
    with pytest.raises(RuntimeError):
        _with("a/one", "b/two", lambda: generate_json(prompt="x"))
    assert "b/two" not in seen


def test_all_models_exhausted_reports_the_list(monkeypatch):
    _with("a/one", "b/two", lambda: _fake_call(
        monkeypatch, lambda model: (_ for _ in ()).throw(Exception("404 model not found"))))
    with pytest.raises(RuntimeError, match="No usable OpenRouter model"):
        _with("a/one", "b/two", lambda: generate_json(prompt="x"))


def test_no_preview_models_in_the_default_chain():
    # A preview fallback would reintroduce exactly the retirement risk the
    # chain exists to remove.
    defaults = type(settings)()
    chain = [defaults.openrouter_model, *defaults.openrouter_fallback_models.split(",")]
    assert not [m for m in chain if "preview" in m]
