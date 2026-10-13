import httpx
import pytest

from paperbot.models import PdfDownloadError
from paperbot.pdf import download_pdf, safe_filename

PDF_BYTES = b"%PDF-1.7\n fake pdf body"


# Review Focus 3
@pytest.mark.parametrize(
    "title,expected",
    [
        ("Flee the Flaw: Annotating the Underlying Logic", "Flee the Flaw Annotating the Underlying Logic.pdf"),
        ('What "Logic"? A/B <test> | x*y\\z',"What Logic A B test x y z.pdf"),
        ("Results so far...", "Results so far.pdf"),
        ("Line one\nline two\ttab", "Line one line two tab.pdf"),
        ("", "paper.pdf"),
        ("   ", "paper.pdf"),
        ("CON", "paper CON.pdf"),
        ("Camélia's Corpus", "Camélia's Corpus.pdf"),
    ],
)
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_safe_filename_truncates_long_titles():
    name = safe_filename("A" * 300)
    assert name == "A" * 150 + ".pdf"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_pdf_writes_file_and_creates_folders(tmp_path):
    dest = tmp_path / "argumentation" / "raw" / "Paper.pdf"
    result = download_pdf("https://arxiv.org/pdf/2411.12498", dest, _client(lambda r: httpx.Response(200, content=PDF_BYTES)))
    assert result == dest
    assert dest.read_bytes() == PDF_BYTES
    assert not dest.with_suffix(".part").exists()


def test_download_pdf_rejects_html_body(tmp_path):
    # Review Focus 4
    dest = tmp_path / "Paper.pdf"
    with pytest.raises(PdfDownloadError, match="did not return a PDF"):
        download_pdf("https://x/y.pdf", dest, _client(lambda r: httpx.Response(200, text="<html>slow down</html>")))
    assert not dest.exists()


def test_download_pdf_http_error(tmp_path):
    with pytest.raises(PdfDownloadError, match="404"):
        download_pdf("https://x/y.pdf", tmp_path / "P.pdf", _client(lambda r: httpx.Response(404)))


def test_download_pdf_network_error(tmp_path):
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(PdfDownloadError, match="boom"):
        download_pdf("https://x/y.pdf", tmp_path / "P.pdf", _client(handler))


def test_download_pdf_skips_existing_file(tmp_path):
    dest = tmp_path / "P.pdf"
    dest.write_bytes(PDF_BYTES)

    def handler(request):
        raise AssertionError("should not download again")

    assert download_pdf("https://x/y.pdf", dest, _client(handler)) == dest
