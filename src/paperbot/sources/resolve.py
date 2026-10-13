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
