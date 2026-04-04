"""LLMRouter — multi-provider routing with fallback chain and cost recording."""
import json
import logging
from pathlib import Path

from tools.providers.base import LLMProvider, LLMResponse, ProviderError
from tools.providers.anthropic_provider import AnthropicProvider
from tools.providers.openai_provider import OpenAIProvider
from tools.providers.google_provider import GoogleProvider
from memory.cost_tracker import CostTracker

logger = logging.getLogger("nanoclaw.llm_router")


class LLMRouter:
    def __init__(self, cost_tracker: CostTracker, settings,
                 pricing_path: str = "config/pricing.json"):
        self.providers: dict[str, LLMProvider] = {}
        self.cost_tracker = cost_tracker
        self._settings = settings
        self._register_providers(pricing_path)

    def _register_providers(self, pricing_path: str) -> None:
        pricing = json.loads(Path(pricing_path).read_text())
        self.providers["anthropic"] = AnthropicProvider(pricing)
        self.providers["openai"] = OpenAIProvider(pricing)
        self.providers["google"] = GoogleProvider(pricing)

    async def route(
        self,
        task_type: str,
        messages: list[dict],
        session_id: str,
        task_id: str = None,
        agent: str = "unknown",
    ) -> LLMResponse:
        """Route to best provider for task_type. Falls back on failure."""
        routing = self._settings.llm.routing
        if task_type not in routing:
            raise ValueError(f"Unknown task_type: {task_type}")

        primary = routing[task_type]
        chain = self._build_chain(primary)
        last_error = None

        for provider_name, model in chain:
            if provider_name not in self.providers:
                logger.warning("Provider %s not registered, skipping", provider_name)
                continue
            try:
                provider = self.providers[provider_name]
                response = await provider.complete(messages, model)
                await self.cost_tracker.log(
                    session_id, task_id, agent,
                    provider_name, model,
                    response.tokens_in, response.tokens_out,
                )
                return response
            except (ProviderError, Exception) as e:
                last_error = e
                logger.warning(
                    "Provider %s/%s failed, trying next: %s",
                    provider_name, model, e,
                )
                continue

        raise RuntimeError(
            f"All providers in fallback chain failed. Last error: {last_error}"
        )

    def _build_chain(self, primary) -> list[tuple[str, str]]:
        """Build fallback chain starting with primary provider.

        Prepends the task-specific primary model, then appends entries from
        fallback_chain that aren't already in the list. Deduplication is
        intentional — the primary model is not tried twice.
        """
        chain = [(primary.provider, primary.model)]
        for entry in self._settings.llm.fallback_chain:
            pair = (entry[0], entry[1])
            if pair not in chain:
                chain.append(pair)
        return chain
