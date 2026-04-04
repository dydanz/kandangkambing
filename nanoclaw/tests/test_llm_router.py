"""Tests for LLM Router — routing, fallback, cost logging (PR3)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.providers.base import LLMProvider, LLMResponse, ProviderError
from tools.llm_router import LLMRouter
from memory.cost_tracker import CostTracker


# --- Fake provider for testing ---

class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, responses=None, fail=False):
        self._responses = responses or {}
        self._fail = fail
        self.calls = []

    async def complete(self, messages, model, **kwargs):
        self.calls.append((messages, model))
        if self._fail:
            raise ProviderError(f"Fake {model} failure")
        return LLMResponse(
            content=f"response from {model}",
            model=model,
            provider=self.name,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
        )

    def models(self):
        return ["fake-model"]


# --- Settings stub ---

class _Route:
    def __init__(self, provider, model):
        self.provider = provider
        self.model = model

class _LLMSettings:
    def __init__(self):
        self.routing = {
            "coding": _Route("primary", "model-a"),
            "spec": _Route("secondary", "model-b"),
        }
        self.fallback_chain = [
            ["primary", "model-a"],
            ["secondary", "model-b"],
            ["tertiary", "model-c"],
        ]

class _Settings:
    def __init__(self):
        self.llm = _LLMSettings()


# --- Fixtures ---

@pytest.fixture
def cost_tracker(tmp_path):
    pricing_path = tmp_path / "pricing.json"
    pricing_path.write_text(json.dumps({
        "primary": {"model-a": {"in": 3.0, "out": 15.0}},
        "secondary": {"model-b": {"in": 2.5, "out": 10.0}},
    }))
    return CostTracker(
        db_path=str(tmp_path / "costs.db"),
        pricing_path=str(pricing_path),
    )


@pytest.fixture
def settings():
    return _Settings()


@pytest.fixture
def make_router(cost_tracker, settings, tmp_path):
    """Factory to create a router with custom providers."""
    def _make(providers: dict):
        pricing_path = tmp_path / "pricing.json"
        if not pricing_path.exists():
            pricing_path.write_text(json.dumps({}))
        router = LLMRouter.__new__(LLMRouter)
        router.providers = providers
        router.cost_tracker = cost_tracker
        router._settings = settings
        return router
    return _make


# --- Tests ---

@pytest.mark.asyncio
async def test_route_uses_correct_provider(make_router):
    primary = FakeProvider()
    secondary = FakeProvider()
    router = make_router({"primary": primary, "secondary": secondary})

    result = await router.route("coding", [{"role": "user", "content": "hi"}],
                                 session_id="s1")
    assert result.provider == "fake"
    assert result.model == "model-a"
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 0


@pytest.mark.asyncio
async def test_route_falls_back_on_failure(make_router):
    primary = FakeProvider(fail=True)
    secondary = FakeProvider()
    tertiary = FakeProvider()
    router = make_router({
        "primary": primary,
        "secondary": secondary,
        "tertiary": tertiary,
    })

    result = await router.route("coding", [{"role": "user", "content": "hi"}],
                                 session_id="s1")
    # Primary fails, should fall back to secondary
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 1
    assert result.model == "model-b"


@pytest.mark.asyncio
async def test_route_all_fail_raises(make_router):
    primary = FakeProvider(fail=True)
    secondary = FakeProvider(fail=True)
    tertiary = FakeProvider(fail=True)
    router = make_router({
        "primary": primary,
        "secondary": secondary,
        "tertiary": tertiary,
    })

    with pytest.raises(RuntimeError, match="All providers"):
        await router.route("coding", [{"role": "user", "content": "hi"}],
                           session_id="s1")


@pytest.mark.asyncio
async def test_route_unknown_task_type_raises(make_router):
    router = make_router({"primary": FakeProvider()})
    with pytest.raises(ValueError, match="Unknown task_type"):
        await router.route("nonexistent", [], session_id="s1")


@pytest.mark.asyncio
async def test_route_logs_cost(make_router, cost_tracker):
    router = make_router({"primary": FakeProvider()})
    await router.route("coding", [{"role": "user", "content": "hi"}],
                        session_id="s1", task_id="TASK-001", agent="dev")

    total = await cost_tracker.daily_total()
    assert total > 0


@pytest.mark.asyncio
async def test_route_spec_uses_secondary(make_router):
    primary = FakeProvider()
    secondary = FakeProvider()
    router = make_router({"primary": primary, "secondary": secondary})

    result = await router.route("spec", [{"role": "user", "content": "hi"}],
                                 session_id="s1")
    # spec routes to secondary/model-b
    assert len(secondary.calls) == 1
    assert result.model == "model-b"


@pytest.mark.asyncio
async def test_build_chain_deduplicates(make_router):
    router = make_router({})
    primary = _Route("primary", "model-a")
    chain = router._build_chain(primary)
    # primary/model-a appears in fallback_chain too — should only appear once
    provider_model_pairs = [(p, m) for p, m in chain]
    assert provider_model_pairs.count(("primary", "model-a")) == 1
    assert len(chain) == 3  # primary, secondary, tertiary


@pytest.mark.asyncio
async def test_llm_response_structure(make_router):
    router = make_router({"primary": FakeProvider()})
    result = await router.route("coding", [{"role": "user", "content": "hi"}],
                                 session_id="s1")
    assert isinstance(result, LLMResponse)
    assert isinstance(result.content, str)
    assert isinstance(result.tokens_in, int)
    assert isinstance(result.tokens_out, int)
    assert isinstance(result.cost_usd, float)


@pytest.mark.asyncio
async def test_fallback_skips_unregistered_provider(make_router, settings):
    # Only register primary, not secondary or tertiary
    primary = FakeProvider(fail=True)
    router = make_router({"primary": primary})

    with pytest.raises(RuntimeError, match="All providers"):
        await router.route("coding", [{"role": "user", "content": "hi"}],
                           session_id="s1")
