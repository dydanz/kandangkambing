"""BaseAgent — shared LLM interaction pattern for all agents."""
import logging
import uuid
from pathlib import Path

from tools.llm_router import LLMRouter
from memory.shared import SharedMemory
from memory.context_loader import ContextLoader

logger = logging.getLogger("nanoclaw.agents.base")


class BaseAgent:
    name: str = "base"
    task_type: str = "simple"
    prompt_file: str = None  # path to prompt markdown, set by subclass

    def __init__(self, router: LLMRouter, memory: SharedMemory,
                 context: ContextLoader):
        self.router = router
        self.memory = memory
        self.context = context
        self._system_prompt = None

    def _load_prompt(self) -> str:
        """Load system prompt from markdown file. Cached after first load."""
        if self._system_prompt is not None:
            return self._system_prompt
        if self.prompt_file and Path(self.prompt_file).exists():
            self._system_prompt = Path(self.prompt_file).read_text().strip()
        else:
            self._system_prompt = f"You are the {self.name} agent."
        return self._system_prompt

    async def handle(self, instruction: str,
                     task_id: str = None,
                     session_id: str = None) -> str:
        """Send instruction to LLM with context and history. Returns response text."""
        session_id = session_id or str(uuid.uuid4())
        history = await self.memory.get_recent(limit=10, task_id=task_id)
        ctx = await self.context.load_all()
        messages = self._build_messages(instruction, history, ctx)

        response = await self.router.route(
            task_type=self.task_type,
            messages=messages,
            session_id=session_id,
            task_id=task_id,
            agent=self.name,
        )

        await self.memory.save_message(
            role=self.name, agent=self.name,
            content=response.content, task_id=task_id,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
        )
        return response.content

    def _build_messages(self, instruction: str, history: list[dict],
                        ctx: str) -> list[dict]:
        """Build the message list for the LLM call."""
        system_prompt = self._load_prompt()
        if ctx:
            system_prompt = f"{system_prompt}\n\n---\n\n## Project Context\n\n{ctx}"

        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        for msg in history:
            role = "assistant" if msg["agent"] == self.name else "user"
            messages.append({"role": role, "content": msg["content"]})

        # Add current instruction
        messages.append({"role": "user", "content": instruction})
        return messages
