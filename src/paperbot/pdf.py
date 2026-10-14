import re
from pathlib import Path

import httpx

from paperbot.models import PdfDownloadError

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_filename(title: str, max_len: int = 150) -> str:
    """A Windows-safe PDF filename made from the paper title."""
    name = " ".join(_ILLEGAL.sub(" ", title).split())
    name = name[:max_len].rstrip(" .")
    if not name or name.upper() in _RESERVED:
        name = f"paper {name}".strip()
    return f"{name}.pdf"


def download_pdf(url: str, dest: Path, http: httpx.Client) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        response = http.get(url)
    except httpx.HTTPError as e:
        raise PdfDownloadError(f"Could not download PDF: {e}") from e
    if response.status_code != 200:
        raise PdfDownloadError(f"PDF download failed (HTTP {response.status_code})")
    if not response.content.startswith(b"%PDF"):
        raise PdfDownloadError("The PDF link did not return a PDF")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_suffix(".part")
        partial.write_bytes(response.content)
        partial.replace(dest)
    except OSError as e:
        raise PdfDownloadError(f"Could not save PDF to {dest.parent}: {e}") from e
    return dest
