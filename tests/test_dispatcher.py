from paperbot.commands import AddPapers, Summarize, UpdateWiki
from paperbot.dispatcher import Dispatcher, chunk_message
from paperbot.tasks.add_paper import AddOutcome


class FakeAddTask:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.received = None

    def run_many(self, urls):
        self.received = urls
        return self.outcomes


def test_add_papers_joins_outcomes():
    task = FakeAddTask([AddOutcome(True, "✅ one"), AddOutcome(False, "❌ two")])
    reply = Dispatcher(task).handle(AddPapers(("a", "b")))
    assert task.received == ("a", "b")
    assert reply.ok is False
    assert reply.text == "✅ one\n\n❌ two"


def test_add_papers_all_ok():
    reply = Dispatcher(FakeAddTask([AddOutcome(True, "✅ one")])).handle(AddPapers(("a",)))
    assert reply.ok is True


def test_unknown_category():
    reply = Dispatcher(FakeAddTask([])).handle(UpdateWiki(None, "biology"))
    assert not reply.ok
    assert "biology" in reply.text and "argumentation" in reply.text


def test_not_built_yet_commands():
    dispatcher = Dispatcher(FakeAddTask([]))
    assert "not built yet" in dispatcher.handle(UpdateWiki("visual", "visual")).text
    assert "not built yet" in dispatcher.handle(Summarize("https://app.notion.com/p/x")).text


def test_chunk_message_short_text():
    assert chunk_message("hello") == ["hello"]


def test_chunk_message_splits_on_paragraphs():
    paragraphs = ["a" * 900, "b" * 900, "c" * 900]
    chunks = chunk_message("\n\n".join(paragraphs))
    assert chunks == ["a" * 900 + "\n\n" + "b" * 900, "c" * 900]


def test_chunk_message_hard_splits_huge_paragraph():
    chunks = chunk_message("x" * 4500)
    assert [len(c) for c in chunks] == [2000, 2000, 500]
