"""ContextLoader — loads Markdown context files into agent prompts."""
from pathlib import Path


class ContextLoader:
    def __init__(self, context_dir: str = "memory/context"):
        self.dir = Path(context_dir)

    async def load_all(self) -> str:
        """Concatenate all .md context files into a single string.
        Returns empty string if context dir is empty or missing."""
        if not self.dir.exists():
            return ""
        parts = []
        for md_file in sorted(self.dir.glob("*.md")):
            content = md_file.read_text().strip()
            if content:
                parts.append(f"# {md_file.stem}\n\n{content}")
        return "\n\n---\n\n".join(parts)

    async def load(self, filename: str) -> str:
        """Load a single context file by name. Returns empty string if missing."""
        path = self.dir / filename
        if not path.exists():
            return ""
        return path.read_text().strip()
