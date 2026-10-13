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
