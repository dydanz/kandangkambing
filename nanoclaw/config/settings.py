from pydantic import BaseModel, Field
from pathlib import Path
import json


class DiscordConfig(BaseModel):
    allowed_user_ids: list[str]
    command_channel_id: str
    log_channel_id: str
    commits_channel_id: str


class WorkflowConfig(BaseModel):
    max_retries: int = 2
    approval_timeout_minutes: int = 60
    job_timeout_minutes: int = 10
    max_concurrent_jobs: int = 2


class RateLimitsConfig(BaseModel):
    llm_calls_per_hour: int = 30
    claude_code_per_hour: int = 10
    git_pushes_per_hour: int = 5
    cooldown_minutes: int = 10


class BudgetConfig(BaseModel):
    daily_limit_usd: float = 5.00
    warn_at_percent: float = 0.80
    daily_report_time: str = "09:00"


class LLMRouteConfig(BaseModel):
    provider: str
    model: str


class LLMConfig(BaseModel):
    routing: dict[str, LLMRouteConfig]
    fallback_chain: list[list[str]]


class PathsConfig(BaseModel):
    project_path: str
    worktree_base: str
    github_repo: str


class Settings(BaseModel):
    discord: DiscordConfig
    workflow: WorkflowConfig
    rate_limits: RateLimitsConfig
    budget: BudgetConfig
    llm: LLMConfig
    paths: PathsConfig

    @classmethod
    def load(cls, path: str = "config/settings.json") -> "Settings":
        with open(path) as f:
            return cls(**json.load(f))
