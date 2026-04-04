"""Auth — user whitelist check for Discord commands."""
import logging

logger = logging.getLogger("nanoclaw.safety.auth")


class Auth:
    """Whitelist-based authorization.

    Silent-ignore contract: callers should NOT send any response
    to disallowed users.
    """

    def __init__(self, allowed_user_ids: list[str]):
        self._allowed = set(allowed_user_ids)

    def is_allowed(self, user_id: str) -> bool:
        """Returns True if user_id is in the whitelist."""
        return user_id in self._allowed

    def add_user(self, user_id: str) -> None:
        """Dynamically add a user to the whitelist."""
        self._allowed.add(user_id)
        logger.info("Added user %s to whitelist", user_id)

    def remove_user(self, user_id: str) -> None:
        """Remove a user from the whitelist."""
        self._allowed.discard(user_id)
        logger.info("Removed user %s from whitelist", user_id)

    @property
    def allowed_users(self) -> set[str]:
        return set(self._allowed)
