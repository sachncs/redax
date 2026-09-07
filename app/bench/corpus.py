"""Corpus data model for RedactionBench.

The benchmark ships a 200-document corpus across 11 categories drawn from
publicly available sources. We model the corpus as a list of `Document`s with a
fixed set of `Category` and `Structure` enums mirroring Tables 4-6 of the
paper.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class Structure(enum.StrEnum):
    """Whether the document is prose-heavy or follows a structured format."""

    UNSTRUCTURED = "unstructured"
    STRUCTURED = "structured"


class Category(enum.StrEnum):
    """The 11 taxonomic categories from RedactionBench Table 4.

    Seven are unstructured (academic, emails, financial, government, legal,
    medical, operations) and four are structured (code, files, logs, terminal).
    """

    ACADEMIC = "academic"
    EMAILS = "emails"
    FINANCIAL = "financial"
    GOVERNMENT = "government"
    LEGAL = "legal"
    MEDICAL = "medical"
    OPERATIONS = "operations"
    CODE = "code"
    FILES = "files"
    LOGS = "logs"
    TERMINAL = "terminal"


CATEGORY_TO_STRUCTURE: dict[Category, Structure] = {
    Category.ACADEMIC: Structure.UNSTRUCTURED,
    Category.EMAILS: Structure.UNSTRUCTURED,
    Category.FINANCIAL: Structure.UNSTRUCTURED,
    Category.GOVERNMENT: Structure.UNSTRUCTURED,
    Category.LEGAL: Structure.UNSTRUCTURED,
    Category.MEDICAL: Structure.UNSTRUCTURED,
    Category.OPERATIONS: Structure.UNSTRUCTURED,
    Category.CODE: Structure.STRUCTURED,
    Category.FILES: Structure.STRUCTURED,
    Category.LOGS: Structure.STRUCTURED,
    Category.TERMINAL: Structure.STRUCTURED,
}


def structure_of(category: Category) -> Structure:
    """Return the structure classification for a given category."""
    return CATEGORY_TO_STRUCTURE[category]


@dataclass(frozen=True)
class Document:
    """A single benchmark document.

    `id` is the canonical RedactionBench document identifier, `text` is the
    raw document body, `category` is one of the 11 fixed categories,
    `genre` is the free-text document class (e.g. "drivers_license"), and
    `source` is "real" or "synthetic" per Table 4.
    """

    id: str
    text: str
    category: Category
    genre: str
    source: str

    @property
    def structure(self) -> Structure:
        """Return the Structure enum mapped from this Document's category."""
        return structure_of(self.category)


def load_corpus(path: Path) -> list[Document]:
    """Load a JSONL corpus file into a list of `Document`s.

    Each line must be a JSON object with keys: id, text, category, genre,
    source. The `category` must be a member of `Category`.
    """
    documents: list[Document] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        documents.append(
            Document(
                id=str(obj["id"]),
                text=str(obj["text"]),
                category=Category(obj["category"]),
                genre=str(obj.get("genre", "")),
                source=str(obj.get("source", "synthetic")),
            )
        )
    return documents


def write_corpus(documents: Iterable[Document], path: Path) -> None:
    """Write a corpus to JSONL. Used by fixture-generation scripts and tests."""
    with path.open("w", encoding="utf-8") as fh:
        for doc in documents:
            fh.write(
                json.dumps(
                    {
                        "id": doc.id,
                        "text": doc.text,
                        "category": doc.category.value,
                        "genre": doc.genre,
                        "source": doc.source,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
