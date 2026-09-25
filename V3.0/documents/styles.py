"""AIROS Document Style Sheet (CHG-026).

Every formatting decision lives HERE and only here - the renderer reads this
module and never hard-codes typography. The values are MEASURED from the
user-approved reference baseline (guide section 2):

- CV:            3-page A4 reference - Calibri, name 22 pt bold centered,
                 professional title 12 pt centered, H1 sections 12 pt bold,
                 experience heading 10 pt bold with ITALIC period, body 10 pt
                 justified, "-" list items, footer ~8 pt grey with "Page : X/Y".
- Cover letter:  1-page A4 reference - Arial 11 pt, bold contact block lead,
                 bold date/subject/salutation, justified body, same footer
                 family.

Where the guide's "approximate" pt ranges differ from the reference, the
reference wins (it IS the visual baseline the documents must match).

Margins (measured from the reference text bounding boxes):
left/right 72 pt (2.54 cm), top ~2.7 cm, footer sits ~1 cm above the paper edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --- hyperlinks ---------------------------------------------------------------
# Measured from the reference: email #0563C1 (Word default) / LinkedIn #1155CC.
# The reference mixes two blues; AIROS uses ONE controlled, calmer blue (the
# LinkedIn one) instead of the Word default style, per guide section 8
# ("do not use the default bright-blue hyperlink appearance").
LINK_COLOR_HEX = "1155CC"
LINK_UNDERLINE = True

# --- footer -------------------------------------------------------------------
FOOTER_COLOR_HEX = "595959"
FOOTER_SEPARATOR = "Page : "  # reference wording: "Page : 1/3"


@dataclass(frozen=True)
class TextStyle:
    font: str
    size_pt: float
    bold: bool = False
    italic: bool = False
    color_hex: str = "000000"
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0
    line_spacing: float = 1.15


@dataclass(frozen=True)
class DocStyle:
    """Complete deterministic style sheet for one document family."""

    doc_type: str
    base_font: str
    name: TextStyle
    subtitle: TextStyle
    status: TextStyle
    section_heading: TextStyle
    entry_heading: TextStyle
    entry_meta: TextStyle
    body: TextStyle
    footer: TextStyle
    bullet_char: str = "-"
    bullet_indent_cm: float = 0.63  # reference: one indent level (~0.63 cm)
    space_after_entry_pt: float = 8.0
    keep_heading_with_next: bool = True
    extra: dict = field(default_factory=dict)


CV = DocStyle(
    doc_type="cv",
    base_font="Calibri",
    name=TextStyle(font="Calibri", size_pt=22.0, bold=True, space_after_pt=2.0),
    subtitle=TextStyle(font="Calibri", size_pt=12.0, space_after_pt=6.0),
    status=TextStyle(font="Calibri", size_pt=10.0, space_after_pt=2.0),
    section_heading=TextStyle(font="Calibri", size_pt=12.0, bold=True, space_before_pt=12.0, space_after_pt=6.0),
    entry_heading=TextStyle(font="Calibri", size_pt=10.0, bold=True, space_before_pt=6.0, space_after_pt=3.0),
    entry_meta=TextStyle(font="Calibri", size_pt=10.0, italic=True),
    body=TextStyle(font="Calibri", size_pt=10.0, space_after_pt=6.0, line_spacing=1.15),
    footer=TextStyle(font="Calibri", size_pt=8.0, color_hex=FOOTER_COLOR_HEX),
    bullet_char="-",
)

COVER_LETTER = DocStyle(
    doc_type="cover_letter",
    base_font="Arial",
    name=TextStyle(font="Arial", size_pt=11.0, bold=True, space_after_pt=2.0),
    subtitle=TextStyle(font="Arial", size_pt=11.0, space_after_pt=2.0),
    status=TextStyle(font="Arial", size_pt=11.0, space_after_pt=2.0),
    section_heading=TextStyle(font="Arial", size_pt=11.0, bold=True, space_before_pt=10.0, space_after_pt=4.0),
    entry_heading=TextStyle(font="Arial", size_pt=11.0, bold=True, space_before_pt=8.0, space_after_pt=3.0),
    entry_meta=TextStyle(font="Arial", size_pt=11.0),
    body=TextStyle(font="Arial", size_pt=11.0, space_after_pt=8.0, line_spacing=1.15),
    footer=TextStyle(font="Arial", size_pt=8.0, color_hex=FOOTER_COLOR_HEX),
    bullet_char="-",
)

STYLES = {"cv": CV, "cover_letter": COVER_LETTER}


def style_for(doc_type: str) -> DocStyle:
    """Style sheet for a document type (KeyError = programming error)."""
    return STYLES[doc_type]


# --- page geometry (measured) -------------------------------------------------
PAGE_WIDTH_CM = 21.0   # A4
PAGE_HEIGHT_CM = 29.7  # A4
MARGIN_LEFT_CM = 2.54  # 72 pt, as measured
MARGIN_RIGHT_CM = 2.54
MARGIN_TOP_CM = 2.7    # ~77 pt, as measured
MARGIN_BOTTOM_CM = 1.6
FOOTER_DISTANCE_CM = 1.0  # footer baseline ~37 pt from the paper edge
