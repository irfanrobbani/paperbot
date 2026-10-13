# Paperbot Plan 1 — Foundation + "Add paper" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Discord bot that, when an arXiv or ACL Anthology link is pasted in `#papers`, creates a Notion row (Paper, Author, Year, Link, Category, Wiki=Pending, Summarized=false) and saves the PDF to `<wiki>/<category>/raw/`.

**Architecture:** One Python process. `discord.py` listens in one channel, parses each message into a command and puts it on an asyncio queue; a single worker runs each job (synchronous code in a thread) through a `Dispatcher`. Services are small, synchronous and dependency-injected (`httpx.Client`, a `chat_json` callable) so they are unit-tested offline with `httpx.MockTransport` and fakes.

**Tech Stack:** Python ≥3.11 (dev on 3.13), uv, discord.py 2.5+, httpx, openai SDK (pointed at DeepSeek), python-dotenv, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-paperbot-design.md`

This is **Plan 1 of 3** (spec §11 build order). Plan 2 = Summarize (spec §6.2). Plan 3 = wiki repo setup + merge (spec §9) and Update wiki (spec §6.3). In this plan, the `update … wiki` and `summarize …` commands are parsed but answer "not built yet".

## Global Constraints

- Python `>=3.11`; dependencies managed with `uv` (`uv sync`, `uv run pytest`).
- Categories are exactly `visual`, `argumentation`, `other` (lowercase internally).
- Notion is called over REST with `httpx`, header `Notion-Version: 2022-06-28` (no Notion SDK).
- Notion properties: Paper (title), Author (rich_text), Year (number), Link (url), Category (select **or multi_select**: the real database uses multi_select; the bot writes one value), Wiki (select: `Pending`/`Ingested`/`Failed`), Summarized (checkbox). Names and select options matched case-insensitively; a new option is written capitalized (`Other`).
- Link is always stored as the canonical abstract URL: `https://arxiv.org/abs/<id>` (no version) or `https://aclanthology.org/<id>/`.
- DeepSeek via `openai` SDK with `base_url="https://api.deepseek.com"`; model from `DEEPSEEK_CHAT_MODEL`, default `deepseek-chat`.
- PDFs go to `<WIKI_REPO_PATH>/<category>/raw/<safe title>.pdf`; task 1 never runs git.
- Jobs are processed one at a time.
- Discord messages are ≤2000 characters each.
- Secrets only in `.env` (git-ignored). Only messages in `DISCORD_CHANNEL_ID` are handled; messages from bots are ignored.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (use a second `-m`).

## Review Focus

1. Links wrapped by Discord/Markdown (`<https://…>`, `[text](https://…)`, trailing `.`/`)`) must still resolve → test in Task 2.
2. The same paper pasted as abstract link, PDF link, or another arXiv version (`v1`/`v2`) — including old Notion rows that stored a PDF link — must be detected as "already added" → tests in Task 7 (`find_by_ref`) and Task 9.
3. Titles containing Windows-illegal characters (`:` `?` `"` `/`), trailing dots, or reserved names must give a valid filename → test in Task 5.
4. A PDF URL that returns an HTML page (rate limit / error page) must not be saved as a `.pdf`; the row is still created with a warning → tests in Task 5 and Task 9.
5. The user's Notion database uses different capitalization (`paper`, option `Argumentation`) and a multi_select Category with no `Other` option yet → must match case-insensitively, write `Other` in the existing style, and never overwrite an existing wrongly-typed `Wiki` column → tests in Task 7.

---

## File Structure

```
paperbot/
  pyproject.toml              # deps, pytest config
  .python-version             # 3.13
  .env.example                # documented settings
  README.md                   # setup: Discord app, Notion integration, .env, run
  src/paperbot/
    __init__.py
    __main__.py               # wiring + startup checks + bot.run
    models.py                 # PaperRef, PaperMeta, CATEGORIES, error classes
    config.py                 # Config, load_config(env)
    sources/
      __init__.py             # fetch_metadata(ref, http) dispatch + re-exports
      resolve.py              # find_urls(text), resolve_url(url)
      arxiv.py                # parse_arxiv_atom, fetch_arxiv
      acl.py                  # parse_acl_page, fetch_acl
    pdf.py                    # safe_filename, download_pdf
    llm.py                    # ChatJSON, deepseek_chat_json, classify_paper
    notion_store.py           # NotionStore (connect, find_by_ref, create_paper)
    commands.py               # AddPapers/UpdateWiki/Summarize, parse_message
    tasks/
      __init__.py
      add_paper.py            # AddPaperTask
    dispatcher.py             # Reply, Dispatcher, chunk_message
    discord_bot.py            # PaperBot (discord.Client + queue worker)
  tests/
    fixtures/arxiv_2411.12498.xml
    fixtures/acl_2024.emnlp-main.1142.html
    test_models_config.py
    test_resolve.py
    test_arxiv.py
    test_acl.py
    test_pdf.py
    test_llm.py
    test_notion_store.py
    test_commands.py
    test_add_paper.py
    test_dispatcher.py
```

All commands below run from `C:\Users\Irfan Robbani\github\paperbot`.

---

### Task 1: Project scaffold, models and config

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.env.example`, `src/paperbot/__init__.py`, `src/paperbot/models.py`, `src/paperbot/config.py`
- Test: `tests/test_models_config.py`

**Interfaces:**
- Produces:
  - `CATEGORIES: tuple[str, ...] = ("visual", "argumentation", "other")`
  - `class PaperbotError(Exception)` and subclasses `UnsupportedURL`, `MetadataError`, `PdfDownloadError`, `NotionError`, `ConfigError` — messages are safe to show in Discord.
  - `PaperRef(source: Literal["arxiv","acl"], id: str)` with properties `abs_url: str`, `pdf_url: str`.
  - `PaperMeta(ref: PaperRef, title: str, authors: tuple[str, ...], year: int, abstract: str)` with property `first_author: str`.
  - `Config` dataclass and `load_config(env: Mapping[str, str]) -> Config`.

- [ ] **Step 1: Create project files**

`pyproject.toml`:
```toml
[project]
name = "paperbot"
version = "0.1.0"
description = "Discord bot that files research papers into Notion and a research wiki"
requires-python = ">=3.11"
dependencies = [
  "discord.py>=2.5",
  "httpx>=0.27",
  "openai>=1.40",
  "python-dotenv>=1.0",
]

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/paperbot"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.python-version`:
```
3.13
```

`.env.example`:
```
# Discord bot token (Developer Portal > Bot > Reset Token)
DISCORD_TOKEN=
# ID of the #papers channel (Discord developer mode > right-click channel > Copy Channel ID)
DISCORD_CHANNEL_ID=
# Notion internal integration secret (notion.so/my-integrations)
NOTION_TOKEN=
# Notion database ID or the full database URL
NOTION_DATABASE_ID=208048b5cde180678e68d1f18fff76f0
# DeepSeek API key (platform.deepseek.com)
DEEPSEEK_API_KEY=
DEEPSEEK_CHAT_MODEL=deepseek-chat
# Folder of the paper-wiki repo (category folders live directly inside it)
WIKI_REPO_PATH=C:\Users\Irfan Robbani\Documents\paper-wiki
```

`src/paperbot/__init__.py`:
```python
"""Paperbot: files research papers into Notion and a research wiki."""
```

- [ ] **Step 2: Write the failing tests**

`tests/test_models_config.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv sync` then `uv run pytest tests/test_models_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.config'`

- [ ] **Step 4: Implement models and config**

`src/paperbot/models.py`:
```python
from dataclasses import dataclass
from typing import Literal

CATEGORIES: tuple[str, ...] = ("visual", "argumentation", "other")


class PaperbotError(Exception):
    """Base error. Its message is shown to the user in Discord."""


class UnsupportedURL(PaperbotError):
    pass


class MetadataError(PaperbotError):
    pass


class PdfDownloadError(PaperbotError):
    pass


class NotionError(PaperbotError):
    pass


class ConfigError(PaperbotError):
    pass


@dataclass(frozen=True)
class PaperRef:
    source: Literal["arxiv", "acl"]
    id: str

    @property
    def abs_url(self) -> str:
        if self.source == "arxiv":
            return f"https://arxiv.org/abs/{self.id}"
        return f"https://aclanthology.org/{self.id}/"

    @property
    def pdf_url(self) -> str:
        if self.source == "arxiv":
            return f"https://arxiv.org/pdf/{self.id}"
        return f"https://aclanthology.org/{self.id}.pdf"


@dataclass(frozen=True)
class PaperMeta:
    ref: PaperRef
    title: str
    authors: tuple[str, ...]
    year: int
    abstract: str

    @property
    def first_author(self) -> str:
        return self.authors[0] if self.authors else ""
```

`src/paperbot/config.py`:
```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_config.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .python-version .env.example uv.lock src/paperbot/__init__.py src/paperbot/models.py src/paperbot/config.py tests/test_models_config.py
git commit -m "feat: project scaffold, models and config" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: URL finding and resolution

**Files:**
- Create: `src/paperbot/sources/__init__.py` (empty for now), `src/paperbot/sources/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `PaperRef`, `UnsupportedURL` from Task 1.
- Produces:
  - `find_urls(text: str) -> list[str]` — all http(s) URLs in a message, stopping at `<>()[]` and whitespace (so Discord `<…>` and Markdown `[…](…)` wrappers are dropped), with trailing `.,;:!?` stripped.
  - `resolve_url(url: str) -> PaperRef` — raises `UnsupportedURL` for anything that is not an arXiv or ACL paper URL.

- [ ] **Step 1: Write the failing tests**

`tests/test_resolve.py`:
```python
import pytest

from paperbot.models import PaperRef, UnsupportedURL
from paperbot.sources.resolve import find_urls, resolve_url

FLEE = PaperRef("acl", "2024.emnlp-main.1142")
ALT = PaperRef("arxiv", "2411.12498")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://arxiv.org/abs/2411.12498", ALT),
        ("https://arxiv.org/abs/2411.12498v2", ALT),
        ("https://arxiv.org/pdf/2411.12498v2", ALT),
        ("https://arxiv.org/pdf/2411.12498.pdf", ALT),
        ("https://arxiv.org/pdf/2411.12498v1.pdf", ALT),
        ("http://www.arxiv.org/abs/2411.12498/", ALT),
        ("https://arxiv.org/html/2411.12498v2", ALT),
        ("https://arxiv.org/abs/hep-th/9901001v1", PaperRef("arxiv", "hep-th/9901001")),
        ("https://aclanthology.org/2024.emnlp-main.1142/", FLEE),
        ("https://aclanthology.org/2024.emnlp-main.1142", FLEE),
        ("https://aclanthology.org/2024.emnlp-main.1142.pdf", FLEE),
        ("https://aclanthology.org/2023.findings-acl.12/", PaperRef("acl", "2023.findings-acl.12")),
        ("https://aclanthology.org/P19-1001/", PaperRef("acl", "P19-1001")),
        ("https://aclanthology.org/P19-1001.pdf", PaperRef("acl", "P19-1001")),
    ],
)
def test_resolve_supported_urls(url, expected):
    assert resolve_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/paper.pdf",
        "https://arxiv.org/list/cs.CL/recent",
        "https://aclanthology.org/events/emnlp-2024/",
        "https://app.notion.com/p/208048b5cde180678e68d1f18fff76f0",
        "not a url",
    ],
)
def test_resolve_unsupported_urls(url):
    with pytest.raises(UnsupportedURL):
        resolve_url(url)


def test_find_urls_unwraps_discord_and_markdown_links():
    # Review Focus 1
    text = (
        "read <https://arxiv.org/abs/2411.12498> and "
        "[flee](https://aclanthology.org/2024.emnlp-main.1142/). "
        "also https://aclanthology.org/2024.emnlp-main.1142.pdf."
    )
    assert find_urls(text) == [
        "https://arxiv.org/abs/2411.12498",
        "https://aclanthology.org/2024.emnlp-main.1142/",
        "https://aclanthology.org/2024.emnlp-main.1142.pdf",
    ]
    assert [resolve_url(u) for u in find_urls(text)] == [ALT, FLEE, FLEE]


def test_find_urls_none():
    assert find_urls("update the visual wiki") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.sources'`

- [ ] **Step 3: Implement**

`src/paperbot/sources/__init__.py`: empty file.

`src/paperbot/sources/resolve.py`:
```python
import re
from urllib.parse import urlparse

from paperbot.models import PaperRef, UnsupportedURL

_URL = re.compile(r"https?://[^\s<>()\[\]]+")

_ARXIV_NEW = r"\d{4}\.\d{4,5}"
_ARXIV_OLD = r"[a-z\-]+(?:\.[A-Z]{2})?/\d{7}"
_ARXIV_PATH = re.compile(
    rf"^/(?:abs|pdf|html)/({_ARXIV_NEW}|{_ARXIV_OLD})(?:v\d+)?(?:\.pdf)?/?$"
)

_ACL_ID = r"(?:\d{4}\.[a-z0-9]+(?:-[a-z0-9]+)*\.\d+|[A-Z]\d{2}-\d{4})"
_ACL_PATH = re.compile(rf"^/({_ACL_ID})(?:\.pdf|/)?$")


def find_urls(text: str) -> list[str]:
    """All http(s) URLs in a Discord message, without wrapping punctuation."""
    return [url.rstrip(".,;:!?") for url in _URL.findall(text)]


def resolve_url(url: str) -> PaperRef:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("arxiv.org", "export.arxiv.org"):
        match = _ARXIV_PATH.match(parsed.path)
        if match:
            return PaperRef("arxiv", match.group(1))
    elif host == "aclanthology.org":
        match = _ACL_PATH.match(parsed.path)
        if match:
            return PaperRef("acl", match.group(1))
    raise UnsupportedURL(f"unsupported link: {url}")
```

Note: `_URL` excludes `(`, `)`, `[`, `]`, `<`, `>` so Markdown and Discord wrappers end the match.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: all passed (21 tests)

- [ ] **Step 5: Commit**

```bash
git add src/paperbot/sources tests/test_resolve.py
git commit -m "feat: find and resolve arXiv/ACL paper URLs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: arXiv metadata

**Files:**
- Create: `src/paperbot/sources/arxiv.py`, `tests/fixtures/arxiv_2411.12498.xml`
- Test: `tests/test_arxiv.py`

**Interfaces:**
- Consumes: `PaperRef`, `PaperMeta`, `MetadataError`.
- Produces: `parse_arxiv_atom(xml_text: str, ref: PaperRef) -> PaperMeta`, `fetch_arxiv(ref: PaperRef, http: httpx.Client) -> PaperMeta`.

- [ ] **Step 1: Add the fixture** (trimmed real response from `export.arxiv.org/api/query?id_list=2411.12498`; the title line break is deliberate — arXiv wraps long titles)

`tests/fixtures/arxiv_2411.12498.xml`:
```xml
<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <id>https://arxiv.org/api/48ySV3d9QMmJH9/1IThSDydokeM</id>
  <title>arXiv Query: search_query=&amp;id_list=2411.12498&amp;start=0&amp;max_results=1</title>
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2411.12498v2</id>
    <title>Enhancing Reasoning Capabilities of LLMs via
      Principled Synthetic Logic Corpus</title>
    <updated>2024-12-23T10:36:38Z</updated>
    <summary>Large language models (LLMs) are capable of solving a wide range of tasks,
yet they have struggled with reasoning. To address this, we propose Additional
Logic Training (ALT).</summary>
    <published>2024-11-19T13:31:53Z</published>
    <author>
      <name>Terufumi Morishita</name>
    </author>
    <author>
      <name>Gaku Morio</name>
    </author>
    <author>
      <name>Atsuki Yamaguchi</name>
    </author>
    <author>
      <name>Yasuhiro Sogawa</name>
    </author>
  </entry>
</feed>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_arxiv.py`:
```python
from pathlib import Path

import httpx
import pytest

from paperbot.models import MetadataError, PaperRef
from paperbot.sources.arxiv import fetch_arxiv, parse_arxiv_atom

FIXTURES = Path(__file__).parent / "fixtures"
REF = PaperRef("arxiv", "2411.12498")
XML = (FIXTURES / "arxiv_2411.12498.xml").read_text(encoding="utf-8")

EMPTY_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom"><id>x</id></feed>"""


def test_parse_arxiv_atom_extracts_metadata():
    meta = parse_arxiv_atom(XML, REF)
    assert meta.ref == REF
    assert meta.title == "Enhancing Reasoning Capabilities of LLMs via Principled Synthetic Logic Corpus"
    assert meta.authors == ("Terufumi Morishita", "Gaku Morio", "Atsuki Yamaguchi", "Yasuhiro Sogawa")
    assert meta.first_author == "Terufumi Morishita"
    assert meta.year == 2024
    assert meta.abstract.startswith("Large language models (LLMs) are capable of solving a wide range of tasks, yet")
    assert "\n" not in meta.abstract


def test_parse_arxiv_atom_unknown_id_raises():
    with pytest.raises(MetadataError, match="2411.12498"):
        parse_arxiv_atom(EMPTY_FEED, REF)


def test_parse_arxiv_atom_garbage_raises():
    with pytest.raises(MetadataError):
        parse_arxiv_atom("<html>rate limited", REF)


def test_fetch_arxiv_queries_api_by_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(200, text=XML)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    meta = fetch_arxiv(REF, http)
    assert seen["url"].host == "export.arxiv.org"
    assert seen["url"].params["id_list"] == "2411.12498"
    assert meta.year == 2024


def test_fetch_arxiv_http_error_raises_metadata_error():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(MetadataError, match="503"):
        fetch_arxiv(REF, http)


def test_fetch_arxiv_network_error_raises_metadata_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(MetadataError, match="arXiv"):
        fetch_arxiv(REF, http)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_arxiv.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.sources.arxiv'`

- [ ] **Step 4: Implement**

`src/paperbot/sources/arxiv.py`:
```python
import xml.etree.ElementTree as ET

import httpx

from paperbot.models import MetadataError, PaperMeta, PaperRef

ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def parse_arxiv_atom(xml_text: str, ref: PaperRef) -> PaperMeta:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise MetadataError(f"arXiv returned an unreadable response for {ref.id}") from e
    entry = root.find(f"{_ATOM}entry")
    if entry is None or not _clean(entry.findtext(f"{_ATOM}title")):
        raise MetadataError(f"arXiv paper {ref.id} not found")
    published = entry.findtext(f"{_ATOM}published") or ""
    if not published[:4].isdigit():
        raise MetadataError(f"arXiv paper {ref.id} has no publication date")
    return PaperMeta(
        ref=ref,
        title=_clean(entry.findtext(f"{_ATOM}title")),
        authors=tuple(
            _clean(author.findtext(f"{_ATOM}name"))
            for author in entry.findall(f"{_ATOM}author")
        ),
        year=int(published[:4]),
        abstract=_clean(entry.findtext(f"{_ATOM}summary")),
    )


def fetch_arxiv(ref: PaperRef, http: httpx.Client) -> PaperMeta:
    try:
        response = http.get(ARXIV_API, params={"id_list": ref.id, "max_results": 1})
    except httpx.HTTPError as e:
        raise MetadataError(f"Could not reach arXiv: {e}") from e
    if response.status_code != 200:
        raise MetadataError(f"arXiv API returned HTTP {response.status_code}")
    return parse_arxiv_atom(response.text, ref)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_arxiv.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/paperbot/sources/arxiv.py tests/fixtures/arxiv_2411.12498.xml tests/test_arxiv.py
git commit -m "feat: fetch arXiv paper metadata" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: ACL Anthology metadata and the `fetch_metadata` dispatcher

The ACL abstract page carries `citation_*` meta tags (title, one per author in "First Last" form with proper Unicode, publication date) and the abstract inside `<div class="card-body acl-abstract"><h5>…</h5><span>…</span></div>`. This is simpler and cleaner than the `.bib` file (whose authors are LaTeX-escaped, and which often has no abstract).

**Files:**
- Create: `src/paperbot/sources/acl.py`, `tests/fixtures/acl_2024.emnlp-main.1142.html`
- Modify: `src/paperbot/sources/__init__.py`
- Test: `tests/test_acl.py`

**Interfaces:**
- Consumes: `PaperRef`, `PaperMeta`, `MetadataError`, `fetch_arxiv` (Task 3).
- Produces: `parse_acl_page(html: str, ref: PaperRef) -> PaperMeta`, `fetch_acl(ref, http) -> PaperMeta`, and in `paperbot.sources`: `fetch_metadata(ref: PaperRef, http: httpx.Client) -> PaperMeta`, re-exporting `find_urls`, `resolve_url`.

- [ ] **Step 1: Add the fixture** (trimmed real page; save as UTF-8; the inner `<span class=tex-math>` checks nested spans)

`tests/fixtures/acl_2024.emnlp-main.1142.html`:
```html
<!doctype html><html lang=en-us><head>
<meta content="Flee the Flaw: Annotating the Underlying Logic of Fallacious Arguments Through Templates and Slot-filling" name=citation_title>
<meta content="Irfan Robbani" name=citation_author>
<meta content="Paul Reisert" name=citation_author>
<meta content="Camélia Guerraoui" name=citation_author>
<meta content="Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing" name=citation_conference_title>
<meta content="2024/11" name=citation_publication_date>
</head><body>
<div class="card-body acl-abstract"><h5 class=card-title>Abstract</h5><span>Prior research in computational argumentation has mainly focused on scoring the quality of arguments, with less attention on explicating logical errors. In this work, we introduce <span class=tex-math>four</span> sets of explainable templates.</span></div>
<div class="card-body"><span>Not part of the abstract</span></div>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_acl.py`:
```python
from pathlib import Path

import httpx
import pytest

from paperbot.models import MetadataError, PaperRef
from paperbot.sources import fetch_metadata
from paperbot.sources.acl import fetch_acl, parse_acl_page

FIXTURES = Path(__file__).parent / "fixtures"
REF = PaperRef("acl", "2024.emnlp-main.1142")
HTML = (FIXTURES / "acl_2024.emnlp-main.1142.html").read_text(encoding="utf-8")


def test_parse_acl_page_extracts_metadata():
    meta = parse_acl_page(HTML, REF)
    assert meta.title == (
        "Flee the Flaw: Annotating the Underlying Logic of Fallacious Arguments "
        "Through Templates and Slot-filling"
    )
    assert meta.authors == ("Irfan Robbani", "Paul Reisert", "Camélia Guerraoui")
    assert meta.first_author == "Irfan Robbani"
    assert meta.year == 2024
    assert meta.abstract == (
        "Prior research in computational argumentation has mainly focused on scoring "
        "the quality of arguments, with less attention on explicating logical errors. "
        "In this work, we introduce four sets of explainable templates."
    )


def test_parse_acl_page_year_falls_back_to_id():
    html = HTML.replace('<meta content="2024/11" name=citation_publication_date>', "")
    assert parse_acl_page(html, REF).year == 2024


def test_parse_acl_page_without_title_raises():
    with pytest.raises(MetadataError, match="title"):
        parse_acl_page("<html><body>nothing</body></html>", REF)


def test_parse_acl_page_without_abstract_gives_empty_abstract():
    html = HTML.replace("acl-abstract", "something-else")
    assert parse_acl_page(html, REF).abstract == ""


def test_fetch_acl_requests_abstract_page():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, text=HTML)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_acl(REF, http).first_author == "Irfan Robbani"
    assert seen["url"] == "https://aclanthology.org/2024.emnlp-main.1142/"


def test_fetch_acl_404_raises_not_found():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(MetadataError, match="not found"):
        fetch_acl(REF, http)


def test_fetch_metadata_dispatches_by_source():
    def handler(request):
        if request.url.host == "aclanthology.org":
            return httpx.Response(200, text=HTML)
        return httpx.Response(200, text=(FIXTURES / "arxiv_2411.12498.xml").read_text(encoding="utf-8"))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_metadata(REF, http).first_author == "Irfan Robbani"
    assert fetch_metadata(PaperRef("arxiv", "2411.12498"), http).first_author == "Terufumi Morishita"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_acl.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_metadata'`

- [ ] **Step 4: Implement**

`src/paperbot/sources/acl.py`:
```python
import re
from html.parser import HTMLParser

import httpx

from paperbot.models import MetadataError, PaperMeta, PaperRef


class _AclPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.abstract_parts: list[str] = []
        self._in_abstract = False
        self._span_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta":
            name = attributes.get("name") or ""
            if name.startswith("citation_"):
                self.meta.setdefault(name, []).append(attributes.get("content") or "")
        elif tag == "div" and "acl-abstract" in (attributes.get("class") or "").split():
            self._in_abstract = True
        elif tag == "span" and self._in_abstract:
            self._span_depth += 1

    def handle_endtag(self, tag):
        if tag == "span" and self._span_depth:
            self._span_depth -= 1
            if self._span_depth == 0:
                self._in_abstract = False

    def handle_data(self, data):
        if self._span_depth:
            self.abstract_parts.append(data)


def _clean(text: str) -> str:
    return " ".join(text.split())


def parse_acl_page(html: str, ref: PaperRef) -> PaperMeta:
    parser = _AclPageParser()
    parser.feed(html)
    parser.close()
    title = _clean((parser.meta.get("citation_title") or [""])[0])
    if not title:
        raise MetadataError(f"No title found on the ACL Anthology page for {ref.id}")
    date = (parser.meta.get("citation_publication_date") or [""])[0]
    year = re.match(r"\d{4}", date) or re.match(r"\d{4}", ref.id)
    if not year:
        raise MetadataError(f"No publication year found for {ref.id}")
    return PaperMeta(
        ref=ref,
        title=title,
        authors=tuple(_clean(a) for a in parser.meta.get("citation_author", []) if a.strip()),
        year=int(year.group(0)),
        abstract=_clean("".join(parser.abstract_parts)),
    )


def fetch_acl(ref: PaperRef, http: httpx.Client) -> PaperMeta:
    try:
        response = http.get(ref.abs_url)
    except httpx.HTTPError as e:
        raise MetadataError(f"Could not reach ACL Anthology: {e}") from e
    if response.status_code == 404:
        raise MetadataError(f"{ref.id} not found on ACL Anthology")
    if response.status_code != 200:
        raise MetadataError(f"ACL Anthology returned HTTP {response.status_code}")
    return parse_acl_page(response.text, ref)
```

`src/paperbot/sources/__init__.py`:
```python
import httpx

from paperbot.models import PaperMeta, PaperRef
from paperbot.sources.acl import fetch_acl
from paperbot.sources.arxiv import fetch_arxiv
from paperbot.sources.resolve import find_urls, resolve_url

__all__ = ["fetch_metadata", "find_urls", "resolve_url"]


def fetch_metadata(ref: PaperRef, http: httpx.Client) -> PaperMeta:
    if ref.source == "arxiv":
        return fetch_arxiv(ref, http)
    return fetch_acl(ref, http)
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: all passed (Tasks 1–4)

- [ ] **Step 6: Commit**

```bash
git add src/paperbot/sources tests/fixtures/acl_2024.emnlp-main.1142.html tests/test_acl.py
git commit -m "feat: fetch ACL Anthology metadata and dispatch by source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: PDF filename and download

**Files:**
- Create: `src/paperbot/pdf.py`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Consumes: `PdfDownloadError`.
- Produces: `safe_filename(title: str, max_len: int = 150) -> str` (always ends in `.pdf`), `download_pdf(url: str, dest: pathlib.Path, http: httpx.Client) -> pathlib.Path`. `download_pdf` skips the download if `dest` already exists and is non-empty; writes atomically via a `.part` file; raises `PdfDownloadError` on network error, non-200, or a body that does not start with `%PDF`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pdf.py`:
```python
import httpx
import pytest

from paperbot.models import PdfDownloadError
from paperbot.pdf import download_pdf, safe_filename

PDF_BYTES = b"%PDF-1.7\n fake pdf body"


# Review Focus 3
@pytest.mark.parametrize(
    "title,expected",
    [
        ("Flee the Flaw: Annotating the Underlying Logic", "Flee the Flaw Annotating the Underlying Logic.pdf"),
        ('What "Logic"? A/B <test> | x*y\\z', "What Logic A B test x y z.pdf"),
        ("Results so far...", "Results so far.pdf"),
        ("Line one\nline two\ttab", "Line one line two tab.pdf"),
        ("", "paper.pdf"),
        ("   ", "paper.pdf"),
        ("CON", "paper CON.pdf"),
        ("Camélia's Corpus", "Camélia's Corpus.pdf"),
    ],
)
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_safe_filename_truncates_long_titles():
    name = safe_filename("A" * 300)
    assert name == "A" * 150 + ".pdf"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_pdf_writes_file_and_creates_folders(tmp_path):
    dest = tmp_path / "argumentation" / "raw" / "Paper.pdf"
    result = download_pdf("https://arxiv.org/pdf/2411.12498", dest, _client(lambda r: httpx.Response(200, content=PDF_BYTES)))
    assert result == dest
    assert dest.read_bytes() == PDF_BYTES
    assert not dest.with_suffix(".part").exists()


def test_download_pdf_rejects_html_body(tmp_path):
    # Review Focus 4
    dest = tmp_path / "Paper.pdf"
    with pytest.raises(PdfDownloadError, match="did not return a PDF"):
        download_pdf("https://x/y.pdf", dest, _client(lambda r: httpx.Response(200, text="<html>slow down</html>")))
    assert not dest.exists()


def test_download_pdf_http_error(tmp_path):
    with pytest.raises(PdfDownloadError, match="404"):
        download_pdf("https://x/y.pdf", tmp_path / "P.pdf", _client(lambda r: httpx.Response(404)))


def test_download_pdf_network_error(tmp_path):
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(PdfDownloadError, match="boom"):
        download_pdf("https://x/y.pdf", tmp_path / "P.pdf", _client(handler))


def test_download_pdf_skips_existing_file(tmp_path):
    dest = tmp_path / "P.pdf"
    dest.write_bytes(PDF_BYTES)

    def handler(request):
        raise AssertionError("should not download again")

    assert download_pdf("https://x/y.pdf", dest, _client(handler)) == dest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.pdf'`

- [ ] **Step 3: Implement**

`src/paperbot/pdf.py`:
```python
import re
from pathlib import Path

import httpx

from paperbot.models import PdfDownloadError

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_filename(title: str, max_len: int = 150) -> str:
    """A Windows-safe PDF filename made from the paper title."""
    name = " ".join(_ILLEGAL.sub(" ", title).split())
    name = name[:max_len].rstrip(" .")
    if not name or name.upper() in _RESERVED:
        name = f"paper {name}".strip()
    return f"{name}.pdf"


def download_pdf(url: str, dest: Path, http: httpx.Client) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        response = http.get(url)
    except httpx.HTTPError as e:
        raise PdfDownloadError(f"Could not download PDF: {e}") from e
    if response.status_code != 200:
        raise PdfDownloadError(f"PDF download failed (HTTP {response.status_code})")
    if not response.content.startswith(b"%PDF"):
        raise PdfDownloadError("The PDF link did not return a PDF")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".part")
    partial.write_bytes(response.content)
    partial.replace(dest)
    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pdf.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/paperbot/pdf.py tests/test_pdf.py
git commit -m "feat: safe PDF filenames and validated PDF download" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: DeepSeek client and paper classification

**Files:**
- Create: `src/paperbot/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `CATEGORIES`.
- Produces:
  - `ChatJSON = Callable[[str, str], str]` — `(system_prompt, user_prompt) -> raw JSON string`.
  - `deepseek_chat_json(api_key: str, model: str) -> ChatJSON` (real client; not unit-tested).
  - `Classification(category: str, reason: str, guessed: bool = False)`.
  - `classify_paper(chat: ChatJSON, title: str, abstract: str) -> Classification` — never raises; after 2 failed attempts returns `Classification("other", ..., guessed=True)` (spec §7).

- [ ] **Step 1: Write the failing tests**

`tests/test_llm.py`:
```python
import json

from paperbot.llm import CLASSIFY_SYSTEM, classify_paper


class FakeChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_classify_returns_category_and_reason():
    chat = FakeChat(json.dumps({"category": "argumentation", "reason": "About fallacies."}))
    result = classify_paper(chat, "Flee the Flaw", "fallacy templates")
    assert (result.category, result.reason, result.guessed) == ("argumentation", "About fallacies.", False)
    system, user = chat.calls[0]
    assert system == CLASSIFY_SYSTEM
    assert "Flee the Flaw" in user and "fallacy templates" in user


def test_classify_normalizes_case():
    chat = FakeChat('{"category": " Visual ", "reason": "memes"}')
    assert classify_paper(chat, "MemeCap", "").category == "visual"


def test_classify_retries_once_after_bad_output():
    chat = FakeChat("not json", '{"category": "other", "reason": "speech"}')
    result = classify_paper(chat, "T", "A")
    assert result.category == "other" and not result.guessed
    assert len(chat.calls) == 2


def test_classify_unknown_category_then_failure_defaults_to_guessed_other():
    chat = FakeChat('{"category": "nlp"}', RuntimeError("API down"))
    result = classify_paper(chat, "T", "A")
    assert result.category == "other"
    assert result.guessed is True


def test_classify_non_object_json_is_a_failure():
    chat = FakeChat("[1, 2]", "[]")
    assert classify_paper(chat, "T", "A").guessed is True


def test_classify_truncates_long_abstract_and_marks_missing_one():
    chat = FakeChat('{"category": "other", "reason": ""}', '{"category": "other", "reason": ""}')
    classify_paper(chat, "T", "x" * 10_000)
    assert len(chat.calls[0][1]) < 3_200
    classify_paper(chat, "T", "")
    assert "(not available)" in chat.calls[1][1]


def test_system_prompt_mentions_json_and_all_categories():
    # DeepSeek JSON mode requires the word "json" in the prompt.
    assert "json" in CLASSIFY_SYSTEM.lower()
    for category in ("visual", "argumentation", "other"):
        assert category in CLASSIFY_SYSTEM
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.llm'`

- [ ] **Step 3: Implement**

`src/paperbot/llm.py`:
```python
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from openai import OpenAI

from paperbot.models import CATEGORIES

log = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
ChatJSON = Callable[[str, str], str]


def deepseek_chat_json(api_key: str, model: str) -> ChatJSON:
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=60)

    def chat(system: str, user: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return chat


@dataclass(frozen=True)
class Classification:
    category: str
    reason: str
    guessed: bool = False


CLASSIFY_SYSTEM = """You classify research papers into exactly one category.

Categories:
- visual: research involving images, e.g. image reasoning, image captioning, visual question answering, meme understanding or interpretation, anything related to images.
- argumentation: research on logical reasoning, logical structure, argument mining, argumentation schemes, fallacy classification, fallacious argument understanding, argument parsing, and similar.
- other: anything related to neither visual nor argumentation.

If a paper fits both visual and argumentation, choose the one that is its main focus.

Answer with a JSON object: {"category": "visual" | "argumentation" | "other", "reason": "<one short sentence>"}"""

_MAX_ABSTRACT = 3000


def classify_paper(chat: ChatJSON, title: str, abstract: str) -> Classification:
    user = f"Title: {title}\n\nAbstract: {abstract[:_MAX_ABSTRACT] or '(not available)'}"
    for attempt in (1, 2):
        try:
            data = json.loads(chat(CLASSIFY_SYSTEM, user))
            category = str(data.get("category", "")).strip().lower()
            if category in CATEGORIES:
                return Classification(category, str(data.get("reason", "")).strip())
            log.warning("Classifier attempt %d returned unknown category %r", attempt, category)
        except Exception:
            log.exception("Classifier attempt %d failed", attempt)
    return Classification("other", "Classifier failed; defaulted to other.", guessed=True)
```

Note: `data.get` on a JSON list raises `AttributeError`, which the `except` treats as a failed attempt — covered by `test_classify_non_object_json_is_a_failure`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/paperbot/llm.py tests/test_llm.py
git commit -m "feat: DeepSeek client and paper classification" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Notion store

**Files:**
- Create: `src/paperbot/notion_store.py`
- Test: `tests/test_notion_store.py`

**Interfaces:**
- Consumes: `PaperMeta`, `PaperRef`, `NotionError`, `resolve_url` (Task 2), `UnsupportedURL`.
- Produces:
  - `NotionPage(id: str, url: str)`.
  - `NotionStore(token: str, database_id: str, http: httpx.Client)` with:
    - `connect() -> list[str]` — loads the schema, matches property names and select options case-insensitively, accepts Category as `select` or `multi_select`, auto-creates **only missing** `Wiki`/`Summarized`, raises `NotionError` listing every remaining problem. Returns human-readable notes about created properties. Must be called before the other methods.
    - `find_by_ref(ref: PaperRef) -> NotionPage | None` — queries Link `contains ref.id`, then keeps only results whose Link resolves to the same `PaperRef` (handles PDF links, versions, and IDs that are prefixes of other IDs).
    - `create_paper(meta: PaperMeta, category: str) -> NotionPage` — Wiki=`Pending`, Summarized=false; Category written as a one-value multi_select or a select, matching the column type; a missing option is written capitalized.

- [ ] **Step 1: Write the failing tests**

`tests/test_notion_store.py`:
```python
import copy
import json

import httpx
import pytest

from paperbot.models import NotionError, PaperMeta, PaperRef
from paperbot.notion_store import NOTION_VERSION, NotionStore

DB_ID = "208048b5cde180678e68d1f18fff76f0"

# Mirrors the real "Paper and Book" database: multi_select Category without an
# "Other" option, plus an unnamed checkbox and a file column the bot ignores.
# Review Focus 5: lowercase "paper", capitalized select options.
BASE_PROPERTIES = {
    "paper": {"type": "title", "title": {}},
    "Author": {"type": "rich_text", "rich_text": {}},
    "Year": {"type": "number", "number": {}},
    "Link": {"type": "url", "url": {}},
    "Category": {"type": "multi_select", "multi_select": {"options": [{"name": "Visual"}, {"name": "Argumentation"}]}},
    "": {"type": "checkbox", "checkbox": {}},
    "Files & media": {"type": "files", "files": {}},
    "Wiki": {"type": "select", "select": {"options": [{"name": "Pending"}, {"name": "Ingested"}, {"name": "Failed"}]}},
    "Summarized": {"type": "checkbox", "checkbox": {}},
}


class FakeNotionAPI:
    def __init__(self, properties=None, query_results=None, fail_status=None):
        self.db = {"object": "database", "id": DB_ID, "properties": copy.deepcopy(properties or BASE_PROPERTIES)}
        self.query_results = query_results or []
        self.fail_status = fail_status
        self.requests: list[tuple[str, str, dict | None]] = []
        self.headers: list[httpx.Headers] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        self.headers.append(request.headers)
        if self.fail_status:
            return httpx.Response(self.fail_status, json={"message": "API token is invalid."})
        path = request.url.path
        if path == f"/v1/databases/{DB_ID}" and request.method == "GET":
            return httpx.Response(200, json=self.db)
        if path == f"/v1/databases/{DB_ID}" and request.method == "PATCH":
            for name, spec in body["properties"].items():
                (prop_type,) = spec.keys()
                self.db["properties"][name] = {"type": prop_type, **spec}
            return httpx.Response(200, json=self.db)
        if path == f"/v1/databases/{DB_ID}/query":
            return httpx.Response(200, json={"results": self.query_results})
        if path == "/v1/pages":
            return httpx.Response(200, json={"id": "page-1", "url": "https://www.notion.so/page-1"})
        return httpx.Response(404, json={"message": f"unexpected {path}"})


def make_store(api: FakeNotionAPI) -> NotionStore:
    return NotionStore("secret", DB_ID, httpx.Client(transport=httpx.MockTransport(api.handler)))


def page(page_id: str, link: str) -> dict:
    return {"id": page_id, "url": f"https://www.notion.so/{page_id}", "properties": {"Link": {"type": "url", "url": link}}}


META = PaperMeta(
    PaperRef("acl", "2024.emnlp-main.1142"),
    "Flee the Flaw",
    ("Irfan Robbani", "Paul Reisert"),
    2024,
    "abstract",
)


def test_connect_with_complete_schema_creates_nothing():
    api = FakeNotionAPI()
    assert make_store(api).connect() == []
    assert [m for m, _, _ in api.requests] == ["GET"]
    assert api.headers[0]["Authorization"] == "Bearer secret"
    assert api.headers[0]["Notion-Version"] == NOTION_VERSION


def test_connect_creates_missing_wiki_and_summarized():
    props = {k: v for k, v in BASE_PROPERTIES.items() if k not in ("Wiki", "Summarized")}
    api = FakeNotionAPI(properties=props)
    notes = make_store(api).connect()
    assert len(notes) == 2
    patch = next(body for method, _, body in api.requests if method == "PATCH")
    assert [o["name"] for o in patch["properties"]["Wiki"]["select"]["options"]] == ["Pending", "Ingested", "Failed"]
    assert patch["properties"]["Summarized"] == {"checkbox": {}}


def test_connect_reports_missing_and_wrongly_typed_properties_without_overwriting():
    # Review Focus 5: an existing Wiki column of the wrong type must not be replaced.
    props = copy.deepcopy(BASE_PROPERTIES)
    del props["Year"]
    props["Link"] = {"type": "rich_text", "rich_text": {}}
    props["Wiki"] = {"type": "rich_text", "rich_text": {}}
    props["Category"] = {"type": "rich_text", "rich_text": {}}
    api = FakeNotionAPI(properties=props)
    with pytest.raises(NotionError) as err:
        make_store(api).connect()
    message = str(err.value)
    assert "Year" in message and "Link" in message and "Wiki" in message
    assert "Category" in message and "select or multi_select" in message
    assert all(method != "PATCH" for method, _, _ in api.requests)


def test_create_paper_uses_actual_names_and_option_capitalization():
    api = FakeNotionAPI()
    store = make_store(api)
    store.connect()
    created = store.create_paper(META, "argumentation")
    assert created.url == "https://www.notion.so/page-1"
    method, path, body = api.requests[-1]
    assert (method, path) == ("POST", "/v1/pages")
    assert body["parent"] == {"database_id": DB_ID}
    props = body["properties"]
    assert props["paper"]["title"][0]["text"]["content"] == "Flee the Flaw"
    assert props["Author"]["rich_text"][0]["text"]["content"] == "Irfan Robbani"
    assert props["Year"] == {"number": 2024}
    assert props["Link"] == {"url": "https://aclanthology.org/2024.emnlp-main.1142/"}
    assert props["Category"] == {"multi_select": [{"name": "Argumentation"}]}
    assert props["Wiki"] == {"select": {"name": "Pending"}}
    assert props["Summarized"] == {"checkbox": False}
    assert "" not in props and "Files & media" not in props


def test_create_paper_new_category_option_is_capitalized():
    # "Other" does not exist yet in the real database.
    api = FakeNotionAPI()
    store = make_store(api)
    store.connect()
    store.create_paper(META, "other")
    assert api.requests[-1][2]["properties"]["Category"] == {"multi_select": [{"name": "Other"}]}


def test_create_paper_with_single_select_category():
    props = copy.deepcopy(BASE_PROPERTIES)
    props["Category"] = {"type": "select", "select": {"options": [{"name": "Visual"}]}}
    api = FakeNotionAPI(properties=props)
    store = make_store(api)
    store.connect()
    store.create_paper(META, "visual")
    assert api.requests[-1][2]["properties"]["Category"] == {"select": {"name": "Visual"}}


def test_find_by_ref_matches_pdf_link_and_ignores_prefix_ids():
    # Review Focus 2: an older row stored the PDF link; another ID shares the prefix.
    api = FakeNotionAPI(
        query_results=[
            page("other", "https://aclanthology.org/2024.emnlp-main.11421/"),
            page("same", "https://aclanthology.org/2024.emnlp-main.1142.pdf"),
        ]
    )
    store = make_store(api)
    store.connect()
    found = store.find_by_ref(PaperRef("acl", "2024.emnlp-main.1142"))
    assert found is not None and found.id == "same"
    _, path, body = api.requests[-1]
    assert path == f"/v1/databases/{DB_ID}/query"
    assert body["filter"] == {"property": "Link", "url": {"contains": "2024.emnlp-main.1142"}}


def test_find_by_ref_matches_other_arxiv_version():
    api = FakeNotionAPI(query_results=[page("p", "https://arxiv.org/pdf/2411.12498v1")])
    store = make_store(api)
    store.connect()
    assert store.find_by_ref(PaperRef("arxiv", "2411.12498")).id == "p"


def test_find_by_ref_ignores_rows_with_empty_or_foreign_links():
    api = FakeNotionAPI(query_results=[page("a", None), page("b", "https://example.com/2411.12498")])
    store = make_store(api)
    store.connect()
    assert store.find_by_ref(PaperRef("arxiv", "2411.12498")) is None


def test_api_error_raises_notion_error_with_message():
    api = FakeNotionAPI(fail_status=401)
    with pytest.raises(NotionError, match="401.*API token is invalid"):
        make_store(api).connect()


def test_methods_require_connect():
    with pytest.raises(NotionError, match="connect"):
        make_store(FakeNotionAPI()).create_paper(META, "other")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notion_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.notion_store'`

- [ ] **Step 3: Implement**

`src/paperbot/notion_store.py`:
```python
from dataclasses import dataclass

import httpx

from paperbot.models import NotionError, PaperMeta, PaperRef, UnsupportedURL
from paperbot.sources.resolve import resolve_url

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# logical key -> (expected property name, accepted types)
SCHEMA: dict[str, tuple[str, tuple[str, ...]]] = {
    "paper": ("Paper", ("title",)),
    "author": ("Author", ("rich_text",)),
    "year": ("Year", ("number",)),
    "link": ("Link", ("url",)),
    "category": ("Category", ("select", "multi_select")),
    "wiki": ("Wiki", ("select",)),
    "summarized": ("Summarized", ("checkbox",)),
}
_CHOICE_TYPES = ("select", "multi_select")

# Properties the bot may add itself if they do not exist at all.
AUTO_CREATE: dict[str, dict] = {
    "wiki": {
        "select": {
            "options": [
                {"name": "Pending", "color": "yellow"},
                {"name": "Ingested", "color": "green"},
                {"name": "Failed", "color": "red"},
            ]
        }
    },
    "summarized": {"checkbox": {}},
}


@dataclass(frozen=True)
class NotionPage:
    id: str
    url: str


class NotionStore:
    def __init__(self, token: str, database_id: str, http: httpx.Client) -> None:
        self._db = database_id
        self._http = http
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._names: dict[str, str] = {}
        self._types: dict[str, str] = {}
        self._options: dict[str, dict[str, str]] = {}

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            response = self._http.request(method, f"{NOTION_API}{path}", headers=self._headers, json=body)
        except httpx.HTTPError as e:
            raise NotionError(f"Could not reach Notion: {e}") from e
        if response.status_code >= 400:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise NotionError(f"Notion API error {response.status_code}: {message}")
        return response.json()

    def _load(self, db: dict) -> tuple[set[str], list[str]]:
        """Record actual property names; return (missing keys, problem messages)."""
        by_lower = {name.lower(): (name, prop) for name, prop in db.get("properties", {}).items()}
        self._names.clear()
        self._types.clear()
        self._options.clear()
        missing: set[str] = set()
        problems: list[str] = []
        for key, (name, types) in SCHEMA.items():
            wanted = " or ".join(types)
            found = by_lower.get(name.lower())
            if found is None:
                missing.add(key)
                problems.append(f"- missing property '{name}' (type: {wanted})")
                continue
            actual, prop = found
            prop_type = prop.get("type")
            if prop_type not in types:
                problems.append(f"- property '{actual}' must be {wanted}, but is {prop_type}")
                continue
            self._names[key] = actual
            self._types[key] = prop_type
            if prop_type in _CHOICE_TYPES:
                options = prop.get(prop_type, {}).get("options", [])
                self._options[key] = {o["name"].lower(): o["name"] for o in options}
        return missing, problems

    def connect(self) -> list[str]:
        db = self._request("GET", f"/databases/{self._db}")
        missing, problems = self._load(db)
        to_create = {key: spec for key, spec in AUTO_CREATE.items() if key in missing}
        notes: list[str] = []
        if to_create:
            body = {"properties": {SCHEMA[key][0]: spec for key, spec in to_create.items()}}
            db = self._request("PATCH", f"/databases/{self._db}", body)
            notes = [f"Created Notion property '{SCHEMA[key][0]}'" for key in to_create]
            missing, problems = self._load(db)
        if problems:
            raise NotionError("Notion database schema problems:\n" + "\n".join(problems))
        return notes

    def _name(self, key: str) -> str:
        if not self._names:
            raise NotionError("NotionStore.connect() must be called first")
        return self._names[key]

    def _choice(self, key: str, value: str) -> dict:
        """select/multi_select value, reusing an existing option's spelling or capitalizing a new one."""
        name = self._options.get(key, {}).get(value.lower(), value[:1].upper() + value[1:])
        if self._types[key] == "multi_select":
            return {"multi_select": [{"name": name}]}
        return {"select": {"name": name}}

    def find_by_ref(self, ref: PaperRef) -> NotionPage | None:
        link_name = self._name("link")
        body = {"filter": {"property": link_name, "url": {"contains": ref.id}}, "page_size": 20}
        for result in self._request("POST", f"/databases/{self._db}/query", body).get("results", []):
            link = (result.get("properties", {}).get(link_name) or {}).get("url")
            if not link:
                continue
            try:
                if resolve_url(link) == ref:
                    return NotionPage(result["id"], result["url"])
            except UnsupportedURL:
                continue
        return None

    def create_paper(self, meta: PaperMeta, category: str) -> NotionPage:
        properties = {
            self._name("paper"): {"title": [{"text": {"content": meta.title[:2000]}}]},
            self._name("author"): {"rich_text": [{"text": {"content": meta.first_author[:2000]}}]},
            self._name("year"): {"number": meta.year},
            self._name("link"): {"url": meta.ref.abs_url},
            self._name("category"): self._choice("category", category),
            self._name("wiki"): self._choice("wiki", "Pending"),
            self._name("summarized"): {"checkbox": False},
        }
        created = self._request("POST", "/pages", {"parent": {"database_id": self._db}, "properties": properties})
        return NotionPage(created["id"], created["url"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notion_store.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/paperbot/notion_store.py tests/test_notion_store.py
git commit -m "feat: Notion store with schema check, dedupe lookup and row creation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Command parsing

**Files:**
- Create: `src/paperbot/commands.py`
- Test: `tests/test_commands.py`

**Interfaces:**
- Consumes: `CATEGORIES`, `find_urls` (Task 2).
- Produces:
  - `AddPapers(urls: tuple[str, ...])`, `UpdateWiki(category: str | None, raw: str)`, `Summarize(url: str | None)`; `Command = AddPapers | UpdateWiki | Summarize`.
  - `match_category(word: str) -> str | None` (fuzzy, cutoff 0.75).
  - `parse_message(text: str) -> Command | None`. Order: first word ≈ "summarize" → `Summarize`; `update [the] <word> wiki` → `UpdateWiki`; any URL → `AddPapers`; else `None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_commands.py`:
```python
import pytest

from paperbot.commands import AddPapers, Summarize, UpdateWiki, match_category, parse_message

NOTION = "https://app.notion.com/p/208048b5cde180678e68d1f18fff76f0?v=208048b5cde181f3bfba000c733f8d65&p=208048b5cde18169b21bed1c385ecde1&pm=s"


@pytest.mark.parametrize(
    "word,expected",
    [("argumentation", "argumentation"), ("argumenation", "argumentation"), ("Visual", "visual"),
     ("visul", "visual"), ("othr", "other"), ("biology", None)],
)
def test_match_category(word, expected):
    assert match_category(word) == expected


def test_links_become_add_papers():
    cmd = parse_message("https://arxiv.org/abs/2411.12498 and <https://aclanthology.org/2024.emnlp-main.1142/>")
    assert cmd == AddPapers(("https://arxiv.org/abs/2411.12498", "https://aclanthology.org/2024.emnlp-main.1142/"))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("update the argumentation wiki", UpdateWiki("argumentation", "argumentation")),
        ("Update the argumenation wiki please", UpdateWiki("argumentation", "argumenation")),
        ("update visual wiki", UpdateWiki("visual", "visual")),
        ("update the biology wiki", UpdateWiki(None, "biology")),
    ],
)
def test_update_wiki(text, expected):
    assert parse_message(text) == expected


@pytest.mark.parametrize("text", [f"summarize {NOTION}", f"Summarise {NOTION}", f"sumarize {NOTION}"])
def test_summarize(text):
    assert parse_message(text) == Summarize(NOTION)


def test_summarize_without_link():
    assert parse_message("summarize") == Summarize(None)


@pytest.mark.parametrize("text", ["hello", "", "what should I update today?"])
def test_chat_is_ignored(text):
    assert parse_message(text) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.commands'`

- [ ] **Step 3: Implement**

`src/paperbot/commands.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_commands.py -v`
Expected: all passed (18 tests)

- [ ] **Step 5: Commit**

```bash
git add src/paperbot/commands.py tests/test_commands.py
git commit -m "feat: parse Discord messages into commands" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Add-paper task

**Files:**
- Create: `src/paperbot/tasks/__init__.py` (empty), `src/paperbot/tasks/add_paper.py`
- Test: `tests/test_add_paper.py`

**Interfaces:**
- Consumes: `resolve_url`, `fetch_metadata`, `classify_paper`/`ChatJSON`, `safe_filename`, `download_pdf`, `NotionStore.find_by_ref`/`create_paper`, error classes.
- Produces:
  - `AddOutcome(ok: bool, line: str)` — `line` is Discord-ready text.
  - `AddPaperTask(notion, chat: ChatJSON, http: httpx.Client, wiki_root: Path, fetch=fetch_metadata, download=download_pdf)` with `run(url: str) -> AddOutcome` and `run_many(urls: Iterable[str]) -> list[AddOutcome]` (duplicates in one message removed, order kept; one failure never stops the others).

- [ ] **Step 1: Write the failing tests**

`tests/test_add_paper.py`:
```python
import json
from pathlib import Path

from paperbot.models import MetadataError, PaperMeta, PaperRef, PdfDownloadError
from paperbot.notion_store import NotionPage
from paperbot.tasks.add_paper import AddPaperTask

FLEE = PaperMeta(
    PaperRef("acl", "2024.emnlp-main.1142"),
    "Flee the Flaw: Annotating the Underlying Logic",
    ("Irfan Robbani",),
    2024,
    "fallacy templates",
)


class FakeNotion:
    def __init__(self, existing=None):
        self.pages: dict[PaperRef, NotionPage] = dict(existing or {})
        self.created: list[tuple[PaperMeta, str]] = []

    def find_by_ref(self, ref):
        return self.pages.get(ref)

    def create_paper(self, meta, category):
        self.created.append((meta, category))
        created = NotionPage(f"page-{len(self.created)}", f"https://www.notion.so/page-{len(self.created)}")
        self.pages[meta.ref] = created
        return created


def chat_returning(category):
    return lambda system, user: json.dumps({"category": category, "reason": "r"})


class Recorder:
    def __init__(self, error=None):
        self.calls: list[tuple[str, Path]] = []
        self.error = error

    def __call__(self, url, dest, http):
        self.calls.append((url, dest))
        if self.error:
            raise self.error
        return dest


def make_task(tmp_path, notion=None, chat=None, fetch=None, download=None):
    return AddPaperTask(
        notion=notion or FakeNotion(),
        chat=chat or chat_returning("argumentation"),
        http=None,
        wiki_root=tmp_path,
        fetch=fetch or (lambda ref, http: FLEE),
        download=download or Recorder(),
    )


def test_adds_paper_downloads_pdf_and_reports(tmp_path):
    notion, download = FakeNotion(), Recorder()
    task = make_task(tmp_path, notion=notion, download=download)
    outcome = task.run("https://aclanthology.org/2024.emnlp-main.1142.pdf")
    assert outcome.ok
    assert "Flee the Flaw" in outcome.line and "argumentation" in outcome.line
    assert "https://www.notion.so/page-1" in outcome.line
    assert notion.created == [(FLEE, "argumentation")]
    assert download.calls == [(
        "https://aclanthology.org/2024.emnlp-main.1142.pdf",
        tmp_path / "argumentation" / "raw" / "Flee the Flaw Annotating the Underlying Logic.pdf",
    )]


def test_existing_paper_is_not_added_again(tmp_path):
    existing = {FLEE.ref: NotionPage("old", "https://www.notion.so/old")}
    notion = FakeNotion(existing)

    def fetch(ref, http):
        raise AssertionError("must not fetch metadata for duplicates")

    outcome = make_task(tmp_path, notion=notion, fetch=fetch).run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert outcome.ok
    assert "Already added" in outcome.line and "https://www.notion.so/old" in outcome.line
    assert notion.created == []


def test_same_paper_twice_in_one_message(tmp_path):
    # Review Focus 2: abstract link and PDF link of the same paper.
    notion = FakeNotion()
    outcomes = make_task(tmp_path, notion=notion).run_many([
        "https://aclanthology.org/2024.emnlp-main.1142/",
        "https://aclanthology.org/2024.emnlp-main.1142.pdf",
    ])
    assert len(notion.created) == 1
    assert "Already added" in outcomes[1].line


def test_unsupported_and_notion_links(tmp_path):
    task = make_task(tmp_path)
    unsupported = task.run("https://example.com/paper.pdf")
    assert not unsupported.ok and "unsupported" in unsupported.line
    notion_link = task.run("https://app.notion.com/p/208048b5cde180678e68d1f18fff76f0")
    assert not notion_link.ok and "summarize" in notion_link.line


def test_pdf_failure_still_creates_row_with_warning(tmp_path):
    # Review Focus 4
    notion = FakeNotion()
    task = make_task(tmp_path, notion=notion, download=Recorder(PdfDownloadError("The PDF link did not return a PDF")))
    outcome = task.run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert outcome.ok
    assert len(notion.created) == 1
    assert "⚠️" in outcome.line and "did not return a PDF" in outcome.line


def test_guessed_category_is_flagged(tmp_path):
    outcome = make_task(tmp_path, chat=lambda s, u: "garbage").run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert outcome.ok and "`other`" in outcome.line
    assert "please check" in outcome.line


def test_metadata_error_reports_and_creates_nothing(tmp_path):
    notion = FakeNotion()

    def fetch(ref, http):
        raise MetadataError("2024.emnlp-main.1142 not found on ACL Anthology")

    outcome = make_task(tmp_path, notion=notion, fetch=fetch).run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert not outcome.ok and "not found" in outcome.line
    assert notion.created == []


def test_one_failure_does_not_stop_the_others(tmp_path):
    notion = FakeNotion()
    outcomes = make_task(tmp_path, notion=notion).run_many([
        "https://example.com/x",
        "https://aclanthology.org/2024.emnlp-main.1142/",
    ])
    assert [o.ok for o in outcomes] == [False, True]
    assert len(notion.created) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_add_paper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.tasks'`

- [ ] **Step 3: Implement**

`src/paperbot/tasks/__init__.py`: empty file.

`src/paperbot/tasks/add_paper.py`:
```python
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx

from paperbot.llm import ChatJSON, classify_paper
from paperbot.models import PaperbotError, PdfDownloadError, UnsupportedURL
from paperbot.pdf import download_pdf, safe_filename
from paperbot.sources import fetch_metadata, resolve_url

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddOutcome:
    ok: bool
    line: str


class AddPaperTask:
    def __init__(self, notion, chat: ChatJSON, http: httpx.Client, wiki_root: Path,
                 fetch=fetch_metadata, download=download_pdf) -> None:
        self.notion = notion
        self.chat = chat
        self.http = http
        self.wiki_root = wiki_root
        self.fetch = fetch
        self.download = download

    def run_many(self, urls: Iterable[str]) -> list[AddOutcome]:
        return [self.run(url) for url in dict.fromkeys(urls)]

    def run(self, url: str) -> AddOutcome:
        try:
            ref = resolve_url(url)
        except UnsupportedURL:
            if "notion." in url:
                return AddOutcome(False, f"❌ <{url}> is a Notion link. To summarize it, type `summarize {url}`")
            return AddOutcome(False, f"❌ <{url}>: unsupported source (only arXiv and ACL Anthology)")

        warnings: list[str] = []
        try:
            existing = self.notion.find_by_ref(ref)
            if existing:
                return AddOutcome(True, f"ℹ️ Already added: {existing.url}")
            meta = self.fetch(ref, self.http)
            classification = classify_paper(self.chat, meta.title, meta.abstract)
            if classification.guessed:
                warnings.append("Category was guessed, please check it in Notion")
            dest = self.wiki_root / classification.category / "raw" / safe_filename(meta.title)
            try:
                self.download(ref.pdf_url, dest, self.http)
            except PdfDownloadError as e:
                warnings.append(f"{e}. The PDF will be fetched again later.")
            created = self.notion.create_paper(meta, classification.category)
        except PaperbotError as e:
            log.warning("Add failed for %s: %s", url, e)
            return AddOutcome(False, f"❌ <{url}>: {e}")

        line = (
            f"✅ **{meta.title}** · {meta.first_author}, {meta.year} · `{classification.category}`\n"
            f"{created.url}"
        )
        for warning in warnings:
            line += f"\n⚠️ {warning}"
        return AddOutcome(True, line)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_add_paper.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/paperbot/tasks tests/test_add_paper.py
git commit -m "feat: add-paper task (dedupe, metadata, classify, PDF, Notion)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Dispatcher, Discord bot, entry point, README and smoke test

**Files:**
- Create: `src/paperbot/dispatcher.py`, `src/paperbot/discord_bot.py`, `src/paperbot/__main__.py`, `README.md`
- Test: `tests/test_dispatcher.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Reply(ok: bool, text: str)`; `chunk_message(text: str, limit: int = 2000) -> list[str]`.
  - `Dispatcher(add_task)` with `handle(cmd: Command) -> Reply` (Plans 2 and 3 add `summarize_task` / `update_task` here).
  - `PaperBot(channel_id: int, dispatcher: Dispatcher)` — a `discord.Client`.
  - Entry point: `uv run python -m paperbot`.

- [ ] **Step 1: Write the failing tests**

`tests/test_dispatcher.py`:
```python
from paperbot.commands import AddPapers, Summarize, UpdateWiki
from paperbot.dispatcher import Dispatcher, chunk_message
from paperbot.tasks.add_paper import AddOutcome


class FakeAddTask:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.received = None

    def run_many(self, urls):
        self.received = urls
        return self.outcomes


def test_add_papers_joins_outcomes():
    task = FakeAddTask([AddOutcome(True, "✅ one"), AddOutcome(False, "❌ two")])
    reply = Dispatcher(task).handle(AddPapers(("a", "b")))
    assert task.received == ("a", "b")
    assert reply.ok is False
    assert reply.text == "✅ one\n\n❌ two"


def test_add_papers_all_ok():
    reply = Dispatcher(FakeAddTask([AddOutcome(True, "✅ one")])).handle(AddPapers(("a",)))
    assert reply.ok is True


def test_unknown_category():
    reply = Dispatcher(FakeAddTask([])).handle(UpdateWiki(None, "biology"))
    assert not reply.ok
    assert "biology" in reply.text and "argumentation" in reply.text


def test_not_built_yet_commands():
    dispatcher = Dispatcher(FakeAddTask([]))
    assert "not built yet" in dispatcher.handle(UpdateWiki("visual", "visual")).text
    assert "not built yet" in dispatcher.handle(Summarize("https://app.notion.com/p/x")).text


def test_chunk_message_short_text():
    assert chunk_message("hello") == ["hello"]


def test_chunk_message_splits_on_paragraphs():
    paragraphs = ["a" * 900, "b" * 900, "c" * 900]
    chunks = chunk_message("\n\n".join(paragraphs))
    assert chunks == ["a" * 900 + "\n\n" + "b" * 900, "c" * 900]


def test_chunk_message_hard_splits_huge_paragraph():
    chunks = chunk_message("x" * 4500)
    assert [len(c) for c in chunks] == [2000, 2000, 500]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperbot.dispatcher'`

- [ ] **Step 3: Implement the dispatcher**

`src/paperbot/dispatcher.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dispatcher.py -v`
Expected: 7 passed

- [ ] **Step 5: Implement the Discord bot and entry point**

`src/paperbot/discord_bot.py`:
```python
import asyncio
import logging

import discord

from paperbot.commands import Command, parse_message
from paperbot.dispatcher import Dispatcher, Reply, chunk_message

log = logging.getLogger(__name__)

WAITING = "⏳"


class PaperBot(discord.Client):
    def __init__(self, channel_id: int, dispatcher: Dispatcher) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._channel_id = channel_id
        self._dispatcher = dispatcher
        self._jobs: asyncio.Queue[tuple[discord.Message, Command]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())

    async def on_ready(self) -> None:
        log.info("Logged in as %s; listening in channel %s", self.user, self._channel_id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.channel.id != self._channel_id:
            return
        cmd = parse_message(message.content)
        if cmd is None:
            return
        await message.add_reaction(WAITING)
        await self._jobs.put((message, cmd))

    async def _worker(self) -> None:
        while True:
            message, cmd = await self._jobs.get()
            try:
                reply = await asyncio.to_thread(self._dispatcher.handle, cmd)
            except Exception:
                log.exception("Job failed: %r", cmd)
                reply = Reply(False, "❌ Unexpected error. See logs/paperbot.log")
            try:
                for chunk in chunk_message(reply.text):
                    await message.reply(chunk, mention_author=False, suppress_embeds=True)
                await message.add_reaction("✅" if reply.ok else "❌")
                await message.remove_reaction(WAITING, self.user)
            except discord.DiscordException:
                log.exception("Could not reply in Discord")
            finally:
                self._jobs.task_done()
```

`src/paperbot/__main__.py`:
```python
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
```

- [ ] **Step 6: Write the README**

`README.md`:
````markdown
# paperbot

Discord bot that files research papers into Notion and a research wiki.
Design: `docs/superpowers/specs/2026-10-13-paperbot-design.md`.

## What works now

Paste an arXiv or ACL Anthology link (abstract page or PDF) in `#papers`.
The bot adds a row to the Notion paper database (Paper, Author, Year, Link,
Category, Wiki = Pending) and saves the PDF to `<WIKI_REPO_PATH>/<category>/raw/`.

## Setup

1. **Install**: `uv sync`
2. **Discord bot**
   - https://discord.com/developers/applications → New Application → Bot.
   - Bot page: Reset Token (this is `DISCORD_TOKEN`); enable **Message Content Intent**.
   - OAuth2 → URL Generator: scope `bot`; permissions *View Channels*, *Send Messages*,
     *Read Message History*, *Add Reactions*. Open the URL and add the bot to your server.
   - Create a `#papers` channel. Discord Settings → Advanced → Developer Mode on;
     right-click the channel → Copy Channel ID (`DISCORD_CHANNEL_ID`).
3. **Notion**
   - https://www.notion.so/my-integrations → New integration (internal) → copy the secret (`NOTION_TOKEN`).
   - Open the paper database → `•••` → Connections → add the integration.
   - Columns needed: Paper (title), Author (text), Year (number), Link (URL), Category (select or multi-select).
     The bot adds Wiki and Summarized itself if they are missing.
4. **DeepSeek**: create an API key at https://platform.deepseek.com (`DEEPSEEK_API_KEY`).
5. Copy `.env.example` to `.env` and fill it in.

## Run

```
uv run python -m paperbot
```

Logs go to `logs/paperbot.log`. Tests: `uv run pytest`.
````

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/paperbot/dispatcher.py src/paperbot/discord_bot.py src/paperbot/__main__.py README.md tests/test_dispatcher.py
git commit -m "feat: Discord bot, dispatcher and entry point" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Smoke test against a test Notion database (with the user)**

The user does the account steps in the README (Discord app, Notion integration, DeepSeek key). Then:

1. In Notion, duplicate the paper database (`•••` → Duplicate), connect the integration to the copy, and put the copy's ID in `.env` as `NOTION_DATABASE_ID`. Set `WIKI_REPO_PATH` to a scratch folder, e.g. `C:\Users\Irfan Robbani\Documents\paper-wiki-test`.
2. Run `uv run python -m paperbot`. Expected log: `Logged in as …` (plus `Created Notion property 'Wiki'` / `'Summarized'` the first time).
3. In `#papers`, paste `https://aclanthology.org/2024.emnlp-main.1142.pdf`. Expected: ⏳ then ✅; reply shows "Flee the Flaw…" · Irfan Robbani, 2024 · `argumentation` with a Notion link; the test database has the row with Wiki = Pending; `paper-wiki-test\argumentation\raw\Flee the Flaw Annotating the Underlying Logic of Fallacious Arguments Through Templates and Slot-filling.pdf` exists and opens.
4. Paste `https://arxiv.org/abs/2411.12498v1`. Expected: Morishita et al., 2024, `argumentation`.
5. Paste `https://aclanthology.org/2024.emnlp-main.1142/` again. Expected: "ℹ️ Already added".
6. Type `update the visual wiki`. Expected: "🚧 Wiki updates are not built yet."
7. Type `hello`. Expected: no reaction.

When all pass, switch `NOTION_DATABASE_ID` back to the real database.
