"""Google LLM provider (Gemini models)."""
import logging
import os

from tools.providers.base import LLMProvider, LLMResponse, ProviderError

logger = logging.getLogger("nanoclaw.providers.google")


class GoogleProvider(LLMProvider):
    name = "google"

    def __init__(self, pricing: dict):
        self._pricing = pricing.get("google", {})
        self._configured = False

    def _ensure_configured(self):
        if not self._configured:
            import google.generativeai as genai
            genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
            self._configured = True

    async def complete(self, messages: list[dict],
                       model: str, **kwargs) -> LLMResponse:
        try:
            self._ensure_configured()
            import google.generativeai as genai

            # Convert messages to Gemini format
            system_instruction = None
            contents = []
            for m in messages:
                if m["role"] == "system":
                    system_instruction = m["content"]
                elif m["role"] == "assistant":
                    contents.append({"role": "model", "parts": [m["content"]]})
                else:
                    contents.append({"role": "user", "parts": [m["content"]]})

            gen_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_instruction,
            )
            response = await gen_model.generate_content_async(contents)

            # Gemini usage metadata
            usage = response.usage_metadata
            tokens_in = usage.prompt_token_count
            tokens_out = usage.candidates_token_count
            cost = self._calc_cost(model, tokens_in, tokens_out)

            return LLMResponse(
                content=response.text,
                model=model,
                provider=self.name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
            )
        except Exception as e:
            logger.warning("Google %s failed: %s", model, e)
            raise ProviderError(f"Google {model}: {e}") from e

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
