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
