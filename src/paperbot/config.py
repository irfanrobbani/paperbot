import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from paperbot.models import ConfigError

REQUIRED = (
    "DISCORD_TOKEN",
    "DISCORD_CHANNEL_ID",
    "NOTION_TOKEN",
    "NOTION_DATABASE_ID",
    "DEEPSEEK_API_KEY",
    "WIKI_REPO_PATH",
)


@dataclass(frozen=True)
class Config:
    discord_token: str
    discord_channel_id: int
    notion_token: str
    notion_database_id: str
    deepseek_api_key: str
    deepseek_chat_model: str
    wiki_repo_path: Path


def _notion_id(value: str) -> str:
    """Accept a bare ID, a dashed UUID, or a database URL; return 32 hex chars."""
    path = value.split("?", 1)[0].replace("-", "").lower()
    match = re.search(r"[0-9a-f]{32}", path)
    if not match:
        raise ConfigError("NOTION_DATABASE_ID must be a Notion database ID or URL")
    return match.group(0)


def load_config(env: Mapping[str, str]) -> Config:
    missing = [key for key in REQUIRED if not env.get(key, "").strip()]
    if missing:
        raise ConfigError("Missing settings in .env: " + ", ".join(missing))
    try:
        channel_id = int(env["DISCORD_CHANNEL_ID"].strip())
    except ValueError:
        raise ConfigError("DISCORD_CHANNEL_ID must be a number") from None
    return Config(
        discord_token=env["DISCORD_TOKEN"].strip(),
        discord_channel_id=channel_id,
        notion_token=env["NOTION_TOKEN"].strip(),
        notion_database_id=_notion_id(env["NOTION_DATABASE_ID"]),
        deepseek_api_key=env["DEEPSEEK_API_KEY"].strip(),
        deepseek_chat_model=env.get("DEEPSEEK_CHAT_MODEL", "").strip() or "deepseek-chat",
        wiki_repo_path=Path(env["WIKI_REPO_PATH"].strip()),
    )
