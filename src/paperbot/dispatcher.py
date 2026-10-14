from dataclasses import dataclass

from paperbot.commands import AddPapers, Command, Summarize, UpdateWiki
from paperbot.models import CATEGORIES

DISCORD_LIMIT = 2000


@dataclass(frozen=True)
class Reply:
    ok: bool
    text: str


def chunk_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split text into Discord-sized messages, preferring paragraph boundaries."""
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        while len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class Dispatcher:
    def __init__(self, add_task) -> None:
        self.add_task = add_task

    def handle(self, cmd: Command) -> Reply:
        match cmd:
            case AddPapers(urls=urls):
                outcomes = self.add_task.run_many(urls)
                return Reply(all(o.ok for o in outcomes), "\n\n".join(o.line for o in outcomes))
            case UpdateWiki(category=None, raw=raw):
                return Reply(False, f"❌ Unknown category '{raw}'. Use one of: {', '.join(CATEGORIES)}.")
            case UpdateWiki():
                return Reply(False, "🚧 Wiki updates are not built yet.")
            case Summarize():
                return Reply(False, "🚧 Summarize is not built yet.")
        return Reply(False, "❌ Unknown command.")
