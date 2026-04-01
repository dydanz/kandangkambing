"""QAAgent — validates implementations against acceptance criteria."""
import json
import logging
import uuid

from agents.base import BaseAgent
from agents.dev import DevResult

logger = logging.getLogger("nanoclaw.agents.qa")


class QAAgent(BaseAgent):
    name = "qa"
    task_type = "review"
    prompt_file = "config/prompts/qa_prompt.md"

    async def handle(self, task: dict, dev_result: DevResult,
                     session_id: str = None) -> dict:
        """
        Override of BaseAgent.handle() with task-aware signature.
        Evaluates dev_result against task.acceptance_criteria.

        Returns:
          {
            "passed": bool,
            "criteria": [{"criterion": str, "passed": bool, "notes": str}],
            "feedback": str
          }
        """
        session_id = session_id or str(uuid.uuid4())

        # Build QA-specific instruction
        instruction = self._build_qa_instruction(task, dev_result)

        # Get history and context
        history = await self.memory.get_recent(limit=10, task_id=task["id"])
        ctx = await self.context.load_all()
        messages = self._build_messages(instruction, history, ctx)

        # Call LLM for review
        response = await self.router.route(
            task_type=self.task_type,
            messages=messages,
            session_id=session_id,
            task_id=task["id"],
            agent=self.name,
        )

        # Save to conversation history
        await self.memory.save_message(
            role=self.name, agent=self.name,
            content=response.content, task_id=task["id"],
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
        )

        # Parse structured QA response
        return self._parse_qa_response(response.content, task)

    def _build_qa_instruction(self, task: dict,
                              dev_result: DevResult) -> str:
        """Build the QA review instruction."""
        criteria = "\n".join(
            f"- {ac}" for ac in task.get("acceptance_criteria", [])
        )
        files = "\n".join(
            f"- {f}" for f in dev_result.files_changed
        )
        return (
            f"## QA Review for {task['id']}: {task.get('title', '')}\n\n"
            f"### Implementation Details\n"
            f"{dev_result.details}\n\n"
            f"### Files Changed\n{files}\n\n"
            f"### Verification Status\n"
            f"- Passed: {dev_result.verification_passed}\n"
            f"- Worktree: {dev_result.worktree_path}\n"
            f"- Branch: {dev_result.branch}\n\n"
            f"### Acceptance Criteria to Validate\n{criteria}\n\n"
            f"## Instructions\n"
            f"Evaluate each acceptance criterion. Return ONLY valid JSON:\n"
            f'{{"passed": true/false, "criteria": ['
            f'{{"criterion": "...", "passed": true/false, "notes": "..."}}], '
            f'"feedback": "..."}}'
        )

    @staticmethod
    def _parse_qa_response(content: str, task: dict) -> dict:
        """Parse the QA LLM response into structured result.
        Falls back to a sensible default if JSON parsing fails."""
        # Try to extract JSON from the response
        try:
            # Handle responses that might have text around the JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(content[start:end])
                if "passed" in result:
                    return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: treat as a text review — check for obvious pass/fail signals
        content_lower = content.lower()
        passed = (
            "all criteria met" in content_lower
            or "all pass" in content_lower
            or '"passed": true' in content_lower
        )

        return {
            "passed": passed,
            "criteria": [
                {"criterion": ac, "passed": passed, "notes": "Parsed from text response"}
                for ac in task.get("acceptance_criteria", [])
            ],
            "feedback": content,
        }
