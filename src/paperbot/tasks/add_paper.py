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
        outcomes = []
        for url in dict.fromkeys(urls):
            try:
                outcomes.append(self.run(url))
            except Exception:
                log.exception("Unexpected error adding %s", url)
                outcomes.append(AddOutcome(False, f"❌ <{url}>: Unexpected error. See logs/paperbot.log"))
        return outcomes

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
