"""OpenAI LLM provider (GPT models)."""
import logging
import os

from tools.providers.base import LLMProvider, LLMResponse, ProviderError

logger = logging.getLogger("nanoclaw.providers.openai")


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, pricing: dict):
        self._pricing = pricing.get("openai", {})
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai
            self._client = openai.AsyncOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
            )
        return self._client

    async def complete(self, messages: list[dict],
                       model: str, **kwargs) -> LLMResponse:
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", 4096),
            )

            choice = response.choices[0]
            tokens_in = response.usage.prompt_tokens
            tokens_out = response.usage.completion_tokens
            cost = self._calc_cost(model, tokens_in, tokens_out)

            return LLMResponse(
                content=choice.message.content,
                model=model,
                provider=self.name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
            )
        except Exception as e:
            logger.warning("OpenAI %s failed: %s", model, e)
            raise ProviderError(f"OpenAI {model}: {e}") from e

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
