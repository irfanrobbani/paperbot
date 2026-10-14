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
