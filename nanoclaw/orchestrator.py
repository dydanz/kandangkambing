"""NanoClaw Orchestrator — command parsing and routing (stub)."""
import logging

logger = logging.getLogger("nanoclaw.orchestrator")


class Orchestrator:
    """Parses Discord commands and routes to the appropriate handler.

    Stub implementation — echoes commands back for verification.
    Full routing added in PR6.
    """

    async def handle(self, command: str, user_id: str) -> str:
        logger.info("Received command from %s: %s", user_id, command)
        return f"Echo: {command}"
