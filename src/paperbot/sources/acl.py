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
