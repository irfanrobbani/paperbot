import difflib
import re
from dataclasses import dataclass

from paperbot.models import CATEGORIES
from paperbot.sources.resolve import find_urls


@dataclass(frozen=True)
class AddPapers:
    urls: tuple[str, ...]


@dataclass(frozen=True)
class UpdateWiki:
    category: str | None  # None when the word matched no category
    raw: str


@dataclass(frozen=True)
class Summarize:
    url: str | None


Command = AddPapers | UpdateWiki | Summarize

_UPDATE = re.compile(r"^\s*update\s+(?:the\s+)?([A-Za-z]+)\s+wiki\b", re.IGNORECASE)
_FIRST_WORD = re.compile(r"^\s*([A-Za-z]+)")


def match_category(word: str) -> str | None:
    matches = difflib.get_close_matches(word.lower(), CATEGORIES, n=1, cutoff=0.75)
    return matches[0] if matches else None


def _is_summarize(word: str) -> bool:
    return bool(difflib.get_close_matches(word.lower(), ["summarize", "summarise"], n=1, cutoff=0.8))


def parse_message(text: str) -> Command | None:
    urls = find_urls(text)
    first = _FIRST_WORD.match(text)
    if first and _is_summarize(first.group(1)):
        return Summarize(urls[0] if urls else None)
    update = _UPDATE.match(text)
    if update:
        return UpdateWiki(match_category(update.group(1)), update.group(1))
    if urls:
        return AddPapers(tuple(urls))
    return None
