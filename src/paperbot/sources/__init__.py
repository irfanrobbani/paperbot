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
