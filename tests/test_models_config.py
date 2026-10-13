from pathlib import Path

import pytest

from paperbot.config import load_config
from paperbot.models import ConfigError, PaperMeta, PaperRef

VALID_ENV = {
    "DISCORD_TOKEN": "discord-token",
    "DISCORD_CHANNEL_ID": "123456789",
    "NOTION_TOKEN": "notion-token",
    "NOTION_DATABASE_ID": "208048b5cde180678e68d1f18fff76f0",
    "DEEPSEEK_API_KEY": "sk-test",
    "WIKI_REPO_PATH": r"C:\wiki",
}


def test_arxiv_ref_urls():
    ref = PaperRef("arxiv", "2411.12498")
    assert ref.abs_url == "https://arxiv.org/abs/2411.12498"
    assert ref.pdf_url == "https://arxiv.org/pdf/2411.12498"


def test_acl_ref_urls():
    ref = PaperRef("acl", "2024.emnlp-main.1142")
    assert ref.abs_url == "https://aclanthology.org/2024.emnlp-main.1142/"
    assert ref.pdf_url == "https://aclanthology.org/2024.emnlp-main.1142.pdf"


def test_first_author_empty_when_no_authors():
    meta = PaperMeta(PaperRef("arxiv", "1"), "T", (), 2024, "")
    assert meta.first_author == ""


def test_load_config_valid():
    config = load_config(VALID_ENV)
    assert config.discord_channel_id == 123456789
    assert config.notion_database_id == "208048b5cde180678e68d1f18fff76f0"
    assert config.deepseek_chat_model == "deepseek-chat"
    assert config.wiki_repo_path == Path(r"C:\wiki")


def test_load_config_lists_all_missing_settings():
    env = dict(VALID_ENV, DISCORD_TOKEN="", NOTION_TOKEN="  ")
    with pytest.raises(ConfigError) as err:
        load_config(env)
    assert "DISCORD_TOKEN" in str(err.value)
    assert "NOTION_TOKEN" in str(err.value)


def test_load_config_rejects_non_numeric_channel():
    with pytest.raises(ConfigError, match="DISCORD_CHANNEL_ID"):
        load_config(dict(VALID_ENV, DISCORD_CHANNEL_ID="papers"))


def test_load_config_accepts_database_url_and_dashed_id():
    url = "https://app.notion.com/p/208048b5cde180678e68d1f18fff76f0?v=208048b5cde181f3bfba000c733f8d65"
    assert load_config(dict(VALID_ENV, NOTION_DATABASE_ID=url)).notion_database_id == "208048b5cde180678e68d1f18fff76f0"
    dashed = "208048b5-cde1-8067-8e68-d1f18fff76f0"
    assert load_config(dict(VALID_ENV, NOTION_DATABASE_ID=dashed)).notion_database_id == "208048b5cde180678e68d1f18fff76f0"


def test_load_config_rejects_bad_database_id():
    with pytest.raises(ConfigError, match="NOTION_DATABASE_ID"):
        load_config(dict(VALID_ENV, NOTION_DATABASE_ID="not-an-id"))
