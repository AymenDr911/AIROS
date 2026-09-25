"""AIROS Structured Document Model (CHG-026).

Semantic structure of the generated application documents, exactly as the
Document-Engine technical guide requires: the LLM produces CONTENT, this model
carries it in a document-shaped structure, and the deterministic renderer owns
every formatting decision (typography, spacing, pagination, hyperlink look).

HARD RULE (content preservation): nothing in this model rewrites, summarizes,
expands, invents, deletes, corrects or re-orders the approved content. The
builders (documents/builders.py) only MAP known fields into this structure;
missing facts are left OUT, never invented.

Supported node set (guide section 5): document, metadata, candidate, contact,
title, subtitle, section, subsection, experience, education, certification,
language, volunteering, paragraph, bullet, link, footer.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field


class Alignment(str, Enum):
    """Paragraph alignment (renderer maps it to WD_ALIGN_PARAGRAPH)."""

    LEFT = "left"
    CENTER = "center"
    JUSTIFY = "justify"


class Link(BaseModel):
    """A hyperlink rendered with the controlled (non-default-blue) style."""

    text: str
    url: str
    underline: bool = True


class Paragraph(BaseModel):
    """A plain paragraph. `inline_markdown` tells the renderer the text may
    carry **bold** / *italic* markers from the generator, which are converted
    to real run formatting (markup removal is formatting, not content change)."""

    text: str
    align: Alignment = Alignment.JUSTIFY
    bold: bool = False
    italic: bool = False
    size_key: str = "body"  # key into the document style sheet
    inline_markdown: bool = True
    keep_with_next: bool = False


class Bullet(BaseModel):
    """One list item; `label` is the optional bold lead-in ("Label: rest")."""

    text: str
    label: str = ""
    align: Alignment = Alignment.LEFT
    size_key: str = "body"


class ExperienceEntry(BaseModel):
    """One structured experience block: heading line (role/company/period)
    + optional description paragraphs + optional bullet list."""

    role: str = ""
    company: str = ""
    location: str = ""
    period: str = ""
    period_italic: bool = True
    paragraphs: List[Paragraph] = Field(default_factory=list)
    bullets: List[Bullet] = Field(default_factory=list)


class EducationEntry(BaseModel):
    """One education block: heading (degree/field) + metadata (institution/year)."""

    heading: str = ""
    metadata: str = ""


class Section(BaseModel):
    """An H1 document section. `kind` selects the deterministic layout."""

    heading: str
    kind: str  # "paragraphs" | "bullets" | "experience" | "education" | "entries"
    paragraphs: List[Paragraph] = Field(default_factory=list)
    bullets: List[Bullet] = Field(default_factory=list)
    experience: List[ExperienceEntry] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    entries: List["SimpleEntry"] = Field(default_factory=list)


class SimpleEntry(BaseModel):
    """A single line entry (certification, language, ...)."""

    text: str
    metadata: str = ""


class CandidateHeader(BaseModel):
    """CV header: Name -> professional title -> status line -> contact line."""

    name: str
    professional_title: str = ""
    status_line: str = ""
    contact_items: List[Union[str, Link]] = Field(default_factory=list)


class Footer(BaseModel):
    """Subtle footer: candidate name left, automatic "Page : X/Y" right."""

    left_text: str = ""
    page_numbering: bool = True


Section.model_rebuild()


class DocumentModel(BaseModel):
    """A complete document ready for the deterministic renderer."""

    doc_type: str  # "cv" | "cover_letter"
    candidate: CandidateHeader
    sections: List[Section] = Field(default_factory=list)
    footer: Footer = Field(default_factory=Footer)
    # --- cover letter specifics (hierarchy of guide section 7) ---
    contact_block: List[Union[str, Link]] = Field(default_factory=list)
    contact_block_lead: str = ""  # bold candidate name line
    date_line: str = ""
    location_line: str = ""
    subject: str = ""
    salutation: str = ""
    closing: str = ""
    signature: str = ""
    # --- provenance / QA metadata (never rendered as document content) ---
    metadata: dict = Field(default_factory=dict)
