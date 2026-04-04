"""PMAgent — turns feature requests into structured specs with tasks."""
from agents.base import BaseAgent


class PMAgent(BaseAgent):
    name = "pm"
    task_type = "spec"
    prompt_file = "config/prompts/pm_prompt.md"

    # PMAgent does NOT persist tasks — it returns JSON to WorkflowEngine.
    # WorkflowEngine calls _parse_tasks() then creates tasks via TaskStore.
    # This keeps PMAgent stateless and testable in isolation.
    #
    # No handle() override needed — BaseAgent.handle() is used directly.
    # JSON output is enforced by the PM prompt (pm_prompt.md), not by code.
