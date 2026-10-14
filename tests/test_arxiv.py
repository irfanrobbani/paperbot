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
