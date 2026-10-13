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
