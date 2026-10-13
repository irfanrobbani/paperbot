import pytest

from paperbot.commands import AddPapers, Summarize, UpdateWiki, match_category, parse_message

NOTION = "https://app.notion.com/p/208048b5cde180678e68d1f18fff76f0?v=208048b5cde181f3bfba000c733f8d65&p=208048b5cde18169b21bed1c385ecde1&pm=s"


@pytest.mark.parametrize(
    "word,expected",
    [("argumentation", "argumentation"), ("argumenation", "argumentation"), ("Visual", "visual"),
     ("visul", "visual"), ("othr", "other"), ("biology", None)],
)
def test_match_category(word, expected):
    assert match_category(word) == expected


def test_links_become_add_papers():
    cmd = parse_message("https://arxiv.org/abs/2411.12498 and <https://aclanthology.org/2024.emnlp-main.1142/>")
    assert cmd == AddPapers(("https://arxiv.org/abs/2411.12498", "https://aclanthology.org/2024.emnlp-main.1142/"))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("update the argumentation wiki", UpdateWiki("argumentation", "argumentation")),
        ("Update the argumenation wiki please", UpdateWiki("argumentation", "argumenation")),
        ("update visual wiki", UpdateWiki("visual", "visual")),
        ("update the biology wiki", UpdateWiki(None, "biology")),
    ],
)
def test_update_wiki(text, expected):
    assert parse_message(text) == expected


@pytest.mark.parametrize("text", [f"summarize {NOTION}", f"Summarise {NOTION}", f"sumarize {NOTION}"])
def test_summarize(text):
    assert parse_message(text) == Summarize(NOTION)


def test_summarize_without_link():
    assert parse_message("summarize") == Summarize(None)


@pytest.mark.parametrize("text", ["hello", "", "what should I update today?"])
def test_chat_is_ignored(text):
    assert parse_message(text) is None
