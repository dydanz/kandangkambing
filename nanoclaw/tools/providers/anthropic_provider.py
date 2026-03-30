"""Anthropic LLM provider (Claude models)."""
import json
import logging
import os

from tools.providers.base import LLMProvider, LLMResponse, ProviderError

logger = logging.getLogger("nanoclaw.providers.anthropic")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, pricing: dict):
        self._pricing = pricing.get("anthropic", {})
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
            )
        return self._client

    async def complete(self, messages: list[dict],
                       model: str, **kwargs) -> LLMResponse:
        try:
            client = self._get_client()

            # Separate system message from conversation messages
            system_msg = ""
            chat_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    chat_messages.append(m)

            params = {
                "model": model,
                "messages": chat_messages,
                "max_tokens": kwargs.get("max_tokens", 4096),
            }
            if system_msg:
                params["system"] = system_msg

            response = await client.messages.create(**params)

            tokens_in = response.usage.input_tokens
            tokens_out = response.usage.output_tokens
            cost = self._calc_cost(model, tokens_in, tokens_out)

            return LLMResponse(
                content=response.content[0].text,
                model=model,
                provider=self.name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
            )
        except Exception as e:
            logger.warning("Anthropic %s failed: %s", model, e)
            raise ProviderError(f"Anthropic {model}: {e}") from e

    def models(self) -> list[str]:
        return list(self._pricing.keys())

    def _calc_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        prices = self._pricing.get(model)
        if not prices:
            return 0.0
        return round(
            tokens_in * prices["in"] / 1_000_000
            + tokens_out * prices["out"] / 1_000_000,
            6,
        )
