"""CTOAgent — natural language interface layer for NanoClaw."""
import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from agents.base import BaseAgent

logger = logging.getLogger("nanoclaw.agents.cto")


@dataclass(frozen=True)
class CTODecision:
    action: str           # "execute" | "respond" | "clarify" | "document"
    command: str | None   # orchestrator command string (action=execute only)
    response: str | None  # direct answer (action=respond only)
    question: str | None  # one clarifying question (action=clarify only)
    intent: str           # "coding"|"debugging"|"planning"|"analysis"|"system"|"research"|"unclear"
    confidence: float     # 0.0–1.0
    reasoning: str        # internal note, not shown to user
    # document-action fields (None/False for all other actions)
    doc_title: str | None = None
    doc_filename: str | None = None
    save_to_repo: bool = False
    document_content: str | None = None


_FALLBACK_DECISION = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="I didn't quite follow that — could you rephrase or give me more detail?",
    intent="unclear",
    confidence=0.0,
    reasoning="parse failure",
)

_DESTRUCTIVE_CLARIFY = CTODecision(
    action="clarify",
    command=None,
    response=None,
    question="That looks like a destructive action — can you confirm exactly what you want to do?",
    intent="unclear",
    confidence=0.0,
    reasoning="destructive command guard triggered",
)

_DESTRUCTIVE_KEYWORDS = frozenset({"stop", "delete", "drop", "reset"})


class CTOAgent(BaseAgent):
    name = "cto"
    task_type = "cto"
    prompt_file = "config/prompts/cto_prompt.md"

    async def process(self, message: str, session_id: str) -> CTODecision:
        """Classify message intent via LLM and return a routing decision."""
        try:
            raw = await self.handle(message, session_id=session_id)
        except Exception as e:
            logger.error("CTOAgent LLM call failed: %s", e)
            return _FALLBACK_DECISION

        decision = self._parse_decision(raw)
        return self._apply_destructive_guard(decision)

    async def research(self, topic: str, doc_title: str, session_id: str) -> str:
        """Deep Sonnet LLM pass — generates a structured markdown research document."""
        research_prompt_path = Path("config/prompts/cto_research_prompt.md")
        if research_prompt_path.exists():
            system = research_prompt_path.read_text().strip()
        else:
            system = "You are a technical researcher. Generate structured markdown documents."

        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n"
                    f"Document title: {doc_title}\n\n"
                    "Produce the full research document now."
                ),
            },
        ]

        response = await self.router.route(
            task_type="research",
            messages=messages,
            session_id=session_id,
            agent=self.name,
        )

        await self.memory.save_message(
            role=self.name,
            agent=self.name,
            content=response.content,
            task_id=None,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
        )
        return response.content

    @staticmethod
    def _apply_destructive_guard(decision: CTODecision) -> CTODecision:
        """Downgrade execute decisions with destructive keywords to clarify."""
        if decision.action != "execute" or not decision.command:
            return decision
        command_words = set(decision.command.lower().split())
        if command_words & _DESTRUCTIVE_KEYWORDS:
            logger.warning("CTOAgent: destructive guard triggered for: %s", decision.command)
            return _DESTRUCTIVE_CLARIFY
        return decision

    @staticmethod
    def _parse_decision(raw: str) -> CTODecision:
        """Parse LLM response into a CTODecision. Returns clarify fallback on any error."""
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("CTOAgent: no JSON object found in response")
            return _FALLBACK_DECISION

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("CTOAgent: JSON parse error: %s", e)
            return _FALLBACK_DECISION

        required = {"action", "command", "response", "question",
                    "intent", "confidence", "reasoning"}
        if not required.issubset(data.keys()):
            logger.warning("CTOAgent: missing fields: %s", required - data.keys())
            return _FALLBACK_DECISION

        valid_actions = {"execute", "respond", "clarify", "document"}
        if data.get("action") not in valid_actions:
            logger.warning("CTOAgent: unknown action '%s'", data.get("action"))
            return _FALLBACK_DECISION

        if data.get("action") == "document":
            if not data.get("doc_title") or not data.get("doc_filename"):
                logger.warning("CTOAgent: document action missing doc_title/doc_filename")
                return _FALLBACK_DECISION

        try:
            return CTODecision(
                action=str(data["action"]),
                command=data["command"],
                response=data["response"],
                question=data["question"],
                intent=str(data["intent"]),
                confidence=float(data["confidence"]),
                reasoning=str(data["reasoning"]),
                doc_title=data.get("doc_title"),
                doc_filename=data.get("doc_filename"),
                save_to_repo=bool(data.get("save_to_repo", False)),
                document_content=None,
            )
        except (TypeError, ValueError) as e:
            logger.warning("CTOAgent: field type error: %s", e)
            return _FALLBACK_DECISION
