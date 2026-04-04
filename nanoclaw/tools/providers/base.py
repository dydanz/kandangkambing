"""LLM Provider abstract base class and shared types."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(Exception):
    """Raised when an LLM provider call fails."""
    pass


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, messages: list[dict],
                       model: str, **kwargs) -> LLMResponse:
        """Call this provider. Raises ProviderError on failure."""
        ...

    @abstractmethod
    def models(self) -> list[str]:
        """Return list of supported model names."""
        ...
