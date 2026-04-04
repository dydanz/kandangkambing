"""ToolRegistry — register and invoke tools by name."""
import logging
from typing import Optional

from tools.base import Tool, ToolResult

logger = logging.getLogger("nanoclaw.tool_registry")


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool by its name."""
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name. Returns None if not found."""
        return self._tools.get(name)

    async def invoke(self, name: str, input: str, **kwargs) -> ToolResult:
        """Invoke a tool by name. Raises KeyError if not registered."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not registered")
        return await tool.run(input, **kwargs)

    def list_tools(self) -> list[dict]:
        """Return list of registered tool names and descriptions."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]
