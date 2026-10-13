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
