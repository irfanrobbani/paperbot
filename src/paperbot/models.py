from dataclasses import dataclass
from typing import Literal

CATEGORIES: tuple[str, ...] = ("visual", "argumentation", "other")


class PaperbotError(Exception):
    """Base error. Its message is shown to the user in Discord."""


class UnsupportedURL(PaperbotError):
    pass


class MetadataError(PaperbotError):
    pass


class PdfDownloadError(PaperbotError):
    pass


class NotionError(PaperbotError):
    pass


class ConfigError(PaperbotError):
    pass


@dataclass(frozen=True)
class PaperRef:
    source: Literal["arxiv", "acl"]
    id: str

    @property
    def abs_url(self) -> str:
        if self.source == "arxiv":
            return f"https://arxiv.org/abs/{self.id}"
        return f"https://aclanthology.org/{self.id}/"

    @property
    def pdf_url(self) -> str:
        if self.source == "arxiv":
            return f"https://arxiv.org/pdf/{self.id}"
        return f"https://aclanthology.org/{self.id}.pdf"


@dataclass(frozen=True)
class PaperMeta:
    ref: PaperRef
    title: str
    authors: tuple[str, ...]
    year: int
    abstract: str

    @property
    def first_author(self) -> str:
        return self.authors[0] if self.authors else ""
