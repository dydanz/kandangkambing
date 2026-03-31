"""Tool abstract base class and shared types."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Optional[dict] = field(default_factory=dict)


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, input: str, **kwargs) -> ToolResult:
        ...
