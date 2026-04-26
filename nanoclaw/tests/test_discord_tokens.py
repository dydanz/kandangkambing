"""
Discord bot token sanity-check tests.

These are LIVE integration tests — they hit the real Discord API.
They are skipped automatically when the tokens are not set in the environment.

Run with:
    pytest tests/test_discord_tokens.py -v -s

Or from Docker:
    docker compose run --rm nanoclaw \
        pytest tests/test_discord_tokens.py -v -s
"""
import os
import pytest
import aiohttp

# ── token map ────────────────────────────────────────────────────────────────

TOKENS = {
    "NanoClaw (main)": os.getenv("DISCORD_BOT_TOKEN"),
    "CTO":             os.getenv("DISCORD_CTO_TOKEN"),
    "PMO":             os.getenv("DISCORD_PMO_TOKEN"),
    "SED":             os.getenv("DISCORD_SED_TOKEN"),
    "QAD":             os.getenv("DISCORD_QAD_TOKEN"),
}

DISCORD_API = "https://discord.com/api/v10"

# Target channel for the send-message test.
# Uses the log channel from settings — safe to post a one-off test message.
TEST_CHANNEL_ID = os.getenv("DISCORD_TEST_CHANNEL_ID", "1489972597230665939")


# ── helpers ──────────────────────────────────────────────────────────────────

async def _get_me(session: aiohttp.ClientSession, token: str) -> dict:
    """Call GET /users/@me and return the JSON body."""
    async with session.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bot {token}"},
    ) as resp:
        return {"status": resp.status, "body": await resp.json()}


async def _post_message(
    session: aiohttp.ClientSession, token: str, channel_id: str, content: str
) -> dict:
    """POST a message to a channel. Returns status + body."""
    async with session.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        json={"content": content},
    ) as resp:
        return {"status": resp.status, "body": await resp.json()}


async def _get_messages(
    session: aiohttp.ClientSession, token: str, channel_id: str, limit: int = 3
) -> dict:
    """GET recent messages from a channel."""
    async with session.get(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        params={"limit": limit},
    ) as resp:
        return {"status": resp.status, "body": await resp.json()}


# ── parametrize over all configured tokens ───────────────────────────────────

def _token_params():
    """Yield (name, token) only for tokens that are set."""
    return [
        pytest.param(name, token, id=name)
        for name, token in TOKENS.items()
        if token
    ]


# ── tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("bot_name,token", _token_params())
async def test_token_identity(bot_name: str, token: str):
    """Token is valid: GET /users/@me returns 200 with a bot user object."""
    async with aiohttp.ClientSession() as session:
        result = await _get_me(session, token)

    assert result["status"] == 200, (
        f"[{bot_name}] /users/@me returned HTTP {result['status']}: {result['body']}"
    )
    body = result["body"]
    assert body.get("bot") is True, (
        f"[{bot_name}] Expected a bot user, got: {body}"
    )
    assert "username" in body, f"[{bot_name}] Missing 'username' in response"
    print(f"\n  [{bot_name}] identity OK — username={body['username']!r}  id={body['id']!r}")


@pytest.mark.asyncio
@pytest.mark.parametrize("bot_name,token", _token_params())
async def test_token_can_read_channel(bot_name: str, token: str):
    """Token can read messages from the test channel (requires Read Messages permission)."""
    async with aiohttp.ClientSession() as session:
        result = await _get_messages(session, token, TEST_CHANNEL_ID, limit=3)

    # 200 = success, 403 = missing permission (bot joined but no read access)
    # 401 = invalid token (should not reach here if identity test passes)
    assert result["status"] in (200, 403), (
        f"[{bot_name}] Unexpected status {result['status']}: {result['body']}"
    )
    if result["status"] == 200:
        assert isinstance(result["body"], list), (
            f"[{bot_name}] Expected list of messages, got: {result['body']}"
        )
        print(f"\n  [{bot_name}] read channel OK — got {len(result['body'])} messages")
    else:
        pytest.skip(
            f"[{bot_name}] Bot lacks Read Messages permission on channel {TEST_CHANNEL_ID} "
            f"(HTTP 403) — invite the bot to the server and grant channel access."
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bot_name,token", _token_params())
async def test_token_can_post_message(bot_name: str, token: str):
    """Token can post a message to the test channel (requires Send Messages permission)."""
    async with aiohttp.ClientSession() as session:
        result = await _post_message(
            session, token, TEST_CHANNEL_ID,
            content=f"[sanity-check] `{bot_name}` bot token is valid and can post messages ✅",
        )

    if result["status"] == 403:
        pytest.skip(
            f"[{bot_name}] Bot lacks Send Messages permission on channel {TEST_CHANNEL_ID} "
            f"(HTTP 403) — invite the bot to the server and grant channel access."
        )

    assert result["status"] == 200, (
        f"[{bot_name}] POST /messages returned HTTP {result['status']}: {result['body']}"
    )
    body = result["body"]
    assert "id" in body, f"[{bot_name}] No message id in response: {body}"
    print(f"\n  [{bot_name}] post message OK — message_id={body['id']!r}")
