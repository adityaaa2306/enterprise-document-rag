"""Tests for provider adapters + node assigner."""
from src.core.node_assigner import assign_model_for_node, chain_for_tier
from src.core.llm_providers import get_chat_provider, resolve_provider_for_model


def test_assign_model_picks_from_chain(monkeypatch):
    from src.core import node_assigner as na

    monkeypatch.setattr(na, "_pool_load", lambda: 0.2)
    monkeypatch.setattr(na, "_grid_intensity", lambda _s=None: 300.0)
    out = assign_model_for_node(
        node_kind="regional",
        min_tier="medium",
        model_chain=["med-a", "med-b", "heavy-a"],
        state={"features": {"grid_intensity": 300}},
    )
    assert out["model_id"] in ("med-a", "med-b", "heavy-a")
    assert out["chain"][0] == "med-a"


def test_assign_prefers_earlier_under_high_load(monkeypatch):
    from src.core import node_assigner as na

    monkeypatch.setattr(na, "_pool_load", lambda: 0.95)
    monkeypatch.setattr(na, "_grid_intensity", lambda _s=None: 700.0)
    out = assign_model_for_node(
        node_kind="chunk",
        min_tier="medium",
        model_chain=["cheap", "mid", "expensive"],
        state={},
    )
    # High load → bias toward earlier (cheaper/faster) models
    assert out["model_id"] == "cheap"


def test_provider_resolution():
    assert resolve_provider_for_model("ollama/llama3").name == "ollama"
    assert get_chat_provider("openai_compatible").name == "openai_compatible"
    assert chain_for_tier("light")
