"""CTOAgent — natural language interface layer for NanoClaw."""
import json
import logging
import re
from dataclasses import dataclass

from agents.base import BaseAgent

logger = logging.getLogger("nanoclaw.agents.cto")


@dataclass
class CTODecision:
    action: str           # "execute" | "respond" | "clarify"
    command: str | None   # orchestrator command string (action=execute only)
    response: str | None  # direct answer (action=respond only)
    question: str | None  # one clarifying question (action=clarify only)
    intent: str           # "coding"|"debugging"|"planning"|"analysis"|"system"|"unclear"
    confidence: float     # 0.0–1.0
    reasoning: str        # internal note, not shown to user


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
    confidence=1.0,
    reasoning="destructive command guard triggered",
)

_DESTRUCTIVE_KEYWORDS = frozenset({"stop", "delete", "drop", "reset"})


class CTOAgent(BaseAgent):
    name = "cto"
    task_type = "cto"
    prompt_file = "config/prompts/cto_prompt.md"

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

        try:
            return CTODecision(
                action=str(data["action"]),
                command=data["command"],
                response=data["response"],
                question=data["question"],
                intent=str(data["intent"]),
                confidence=float(data["confidence"]),
                reasoning=str(data["reasoning"]),
            )
        except (TypeError, ValueError) as e:
            logger.warning("CTOAgent: field type error: %s", e)
            return _FALLBACK_DECISION
