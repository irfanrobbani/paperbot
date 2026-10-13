import json
from pathlib import Path

from paperbot.models import MetadataError, PaperMeta, PaperRef, PdfDownloadError
from paperbot.notion_store import NotionPage
from paperbot.tasks.add_paper import AddPaperTask

FLEE = PaperMeta(
    PaperRef("acl", "2024.emnlp-main.1142"),
    "Flee the Flaw: Annotating the Underlying Logic",
    ("Irfan Robbani",),
    2024,
    "fallacy templates",
)


class FakeNotion:
    def __init__(self, existing=None):
        self.pages: dict[PaperRef, NotionPage] = dict(existing or {})
        self.created: list[tuple[PaperMeta, str]] = []

    def find_by_ref(self, ref):
        return self.pages.get(ref)

    def create_paper(self, meta, category):
        self.created.append((meta, category))
        created = NotionPage(f"page-{len(self.created)}", f"https://www.notion.so/page-{len(self.created)}")
        self.pages[meta.ref] = created
        return created


def chat_returning(category):
    return lambda system, user: json.dumps({"category": category, "reason": "r"})


class Recorder:
    def __init__(self, error=None):
        self.calls: list[tuple[str, Path]] = []
        self.error = error

    def __call__(self, url, dest, http):
        self.calls.append((url, dest))
        if self.error:
            raise self.error
        return dest


def make_task(tmp_path, notion=None, chat=None, fetch=None, download=None):
    return AddPaperTask(
        notion=notion or FakeNotion(),
        chat=chat or chat_returning("argumentation"),
        http=None,
        wiki_root=tmp_path,
        fetch=fetch or (lambda ref, http: FLEE),
        download=download or Recorder(),
    )


def test_adds_paper_downloads_pdf_and_reports(tmp_path):
    notion, download = FakeNotion(), Recorder()
    task = make_task(tmp_path, notion=notion, download=download)
    outcome = task.run("https://aclanthology.org/2024.emnlp-main.1142.pdf")
    assert outcome.ok
    assert "Flee the Flaw" in outcome.line and "argumentation" in outcome.line
    assert "https://www.notion.so/page-1" in outcome.line
    assert notion.created == [(FLEE, "argumentation")]
    assert download.calls == [(
        "https://aclanthology.org/2024.emnlp-main.1142.pdf",
        tmp_path / "argumentation" / "raw" / "Flee the Flaw Annotating the Underlying Logic.pdf",
    )]


def test_existing_paper_is_not_added_again(tmp_path):
    existing = {FLEE.ref: NotionPage("old", "https://www.notion.so/old")}
    notion = FakeNotion(existing)

    def fetch(ref, http):
        raise AssertionError("must not fetch metadata for duplicates")

    outcome = make_task(tmp_path, notion=notion, fetch=fetch).run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert outcome.ok
    assert "Already added" in outcome.line and "https://www.notion.so/old" in outcome.line
    assert notion.created == []


def test_same_paper_twice_in_one_message(tmp_path):
    # Review Focus 2: abstract link and PDF link of the same paper.
    notion = FakeNotion()
    outcomes = make_task(tmp_path, notion=notion).run_many([
        "https://aclanthology.org/2024.emnlp-main.1142/",
        "https://aclanthology.org/2024.emnlp-main.1142.pdf",
    ])
    assert len(notion.created) == 1
    assert "Already added" in outcomes[1].line


def test_unsupported_and_notion_links(tmp_path):
    task = make_task(tmp_path)
    unsupported = task.run("https://example.com/paper.pdf")
    assert not unsupported.ok and "unsupported" in unsupported.line
    notion_link = task.run("https://app.notion.com/p/208048b5cde180678e68d1f18fff76f0")
    assert not notion_link.ok and "summarize" in notion_link.line


def test_pdf_failure_still_creates_row_with_warning(tmp_path):
    # Review Focus 4
    notion = FakeNotion()
    task = make_task(tmp_path, notion=notion, download=Recorder(PdfDownloadError("The PDF link did not return a PDF")))
    outcome = task.run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert outcome.ok
    assert len(notion.created) == 1
    assert "⚠️" in outcome.line and "did not return a PDF" in outcome.line


def test_guessed_category_is_flagged(tmp_path):
    outcome = make_task(tmp_path, chat=lambda s, u: "garbage").run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert outcome.ok and "`other`" in outcome.line
    assert "please check" in outcome.line


def test_metadata_error_reports_and_creates_nothing(tmp_path):
    notion = FakeNotion()

    def fetch(ref, http):
        raise MetadataError("2024.emnlp-main.1142 not found on ACL Anthology")

    outcome = make_task(tmp_path, notion=notion, fetch=fetch).run("https://aclanthology.org/2024.emnlp-main.1142/")
    assert not outcome.ok and "not found" in outcome.line
    assert notion.created == []


def test_one_failure_does_not_stop_the_others(tmp_path):
    notion = FakeNotion()
    outcomes = make_task(tmp_path, notion=notion).run_many([
        "https://example.com/x",
        "https://aclanthology.org/2024.emnlp-main.1142/",
    ])
    assert [o.ok for o in outcomes] == [False, True]
    assert len(notion.created) == 1
