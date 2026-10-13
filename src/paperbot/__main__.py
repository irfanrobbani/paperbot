import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from paperbot.config import load_config
from paperbot.discord_bot import PaperBot
from paperbot.dispatcher import Dispatcher
from paperbot.llm import deepseek_chat_json
from paperbot.models import PaperbotError
from paperbot.notion_store import NotionStore
from paperbot.tasks.add_paper import AddPaperTask

log = logging.getLogger("paperbot")


def _setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler("logs/paperbot.log", encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    _setup_logging()
    load_dotenv()
    try:
        config = load_config(os.environ)
        http = httpx.Client(
            timeout=60,
            follow_redirects=True,
            headers={"User-Agent": "paperbot/0.1 (personal research assistant)"},
        )
        notion = NotionStore(config.notion_token, config.notion_database_id, http)
        for note in notion.connect():
            log.info(note)
    except PaperbotError as e:
        log.error("%s", e)
        sys.exit(1)

    chat = deepseek_chat_json(config.deepseek_api_key, config.deepseek_chat_model)
    add_task = AddPaperTask(notion, chat, http, config.wiki_repo_path)
    bot = PaperBot(config.discord_channel_id, Dispatcher(add_task))
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
