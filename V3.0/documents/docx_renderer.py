"""AIROS Deterministic DOCX Renderer (CHG-026).

Renders a structured DocumentModel (documents/models.py) into a professional
A4 DOCX with python-docx. EVERY formatting decision comes from
documents/styles.py - nothing is hard-coded here and nothing is asked from the
LLM (guide sections 3/4: the LLM = content, the renderer = typography/layout).

Key properties:
- real DOCX structures: true list paragraphs ("-" bullet numbering), real
  w:hyperlink elements, PAGE/NUMPAGES fields in the footer;
- controlled hyperlink look (calmer blue, no Word "Hyperlink" default style);
- pagination hygiene: keep_with_next on headings/entry headings, widow control,
  NO arbitrary page breaks, NO content deletion;
- inline **bold** / *italic* markup from the generator is converted to real run
  formatting (markup removal is formatting, not a content change).
"""

from __future__ import annotations

import io
import re
from typing import Iterable, List, Optional, Sequence, Union

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Cm, Pt, RGBColor

from documents.models import (
    Alignment,
    Bullet,
    DocumentModel,
    ExperienceEntry,
    Footer,
    Link,
    Paragraph,
    Section,
)
from documents.styles import (
    FOOTER_SEPARATOR,
    LINK_COLOR_HEX,
    LINK_UNDERLINE,
    FOOTER_DISTANCE_CM,
    MARGIN_BOTTOM_CM,
    MARGIN_LEFT_CM,
    MARGIN_RIGHT_CM,
    MARGIN_TOP_CM,
    PAGE_HEIGHT_CM,
    PAGE_WIDTH_CM,
    DocStyle,
    style_for,
)

_ALIGN = {
    Alignment.LEFT: WD_ALIGN_PARAGRAPH.LEFT,
    Alignment.CENTER: WD_ALIGN_PARAGRAPH.CENTER,
    Alignment.JUSTIFY: WD_ALIGN_PARAGRAPH.JUSTIFY,
}

# Inline markup: **bold**, *italic*, `code` (converted to run formatting).
_MD_TOKEN = re.compile(r"(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)")


class DocumentRenderError(Exception):
    """A rendering failure. NEVER triggers a content regeneration (guide 10):
    the caller reports it and the generated text remains available."""


# -----------------------------------------------------------------------------
# low-level helpers
# -----------------------------------------------------------------------------
def _style_run(run, style: DocStyle, *, size_key: str = "body", bold: Optional[bool] = None,
               italic: Optional[bool] = None, color_hex: Optional[str] = None) -> None:
    text_style = getattr(style, size_key)
    run.font.name = text_style.font or style.base_font
    run.font.size = Pt(text_style.size_pt)
    run.font.bold = text_style.bold if bold is None else bold
    run.font.italic = text_style.italic if italic is None else italic
    run.font.color.rgb = RGBColor.from_string(color_hex or text_style.color_hex)
    # East-Asian font parity so nothing falls back to a theme font
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:cs"):
        r_fonts.set(qn(attribute), run.font.name)


def _add_runs_with_inline_markup(paragraph, text: str, style: DocStyle, *,
                                 size_key: str = "body", base_bold: bool = False,
                                 base_italic: bool = False) -> None:
    """Split `**bold**` / `*italic*` / `code` markup into real runs."""
    for part in _MD_TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            _style_run(run, style, size_key=size_key, bold=True, italic=base_italic)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            _style_run(run, style, size_key=size_key, bold=base_bold, italic=True)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            _style_run(run, style, size_key=size_key, bold=base_bold, italic=base_italic)
        else:
            run = paragraph.add_run(part)
            _style_run(run, style, size_key=size_key, bold=base_bold, italic=base_italic)


def _add_hyperlink(paragraph, text: str, url: str, style: DocStyle, size_key: str = "body") -> None:
    """A REAL w:hyperlink with the controlled link colour (guide section 8)."""
    part = paragraph.part
    relationship_id = part.relate_to(url, RT.HYPERLINK, is_external=True)
    element = OxmlElement("w:hyperlink")
    element.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    r_fonts = OxmlElement("w:rFonts")
    text_style = getattr(style, size_key)
    font_name = text_style.font or style.base_font
    for attribute in ("w:ascii", "w:hAnsi", "w:cs"):
        r_fonts.set(qn(attribute), font_name)
    r_pr.append(r_fonts)
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), str(int(text_style.size_pt * 2)))
    r_pr.append(size)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), LINK_COLOR_HEX)
    r_pr.append(color)
    if LINK_UNDERLINE:
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        r_pr.append(underline)
    run.append(r_pr)
    text_element = OxmlElement("w:t")
    text_element.set(qn("xml:space"), "preserve")
    text_element.text = text
    run.append(text_element)
    element.append(run)
    paragraph._p.append(element)
def _setup_page(document, style: DocStyle) -> None:
    """A4 + the measured margins + footer distance (styles.py geometry)."""
    section = document.sections[0]
    section.page_width = Cm(PAGE_WIDTH_CM)
    section.page_height = Cm(PAGE_HEIGHT_CM)
    section.left_margin = Cm(MARGIN_LEFT_CM)
    section.right_margin = Cm(MARGIN_RIGHT_CM)
    section.top_margin = Cm(MARGIN_TOP_CM)
    section.bottom_margin = Cm(MARGIN_BOTTOM_CM)
    section.footer_distance = Cm(FOOTER_DISTANCE_CM)
    # Base style: so empty spacing paragraphs inherit the document family too.
    normal = document.styles["Normal"]
    normal.font.name = style.base_font
    normal.font.size = Pt(style.body.size_pt)
    normal.paragraph_format.widow_control = True


def _next_ids(numbering) -> tuple[int, int]:
    """Next free (abstractNumId, numId) in the template numbering part."""
    abstract_ids = [
        int(el.get(qn("w:abstractNumId")))
        for el in numbering.findall(qn("w:abstractNum"))
    ]
    num_ids = [int(el.get(qn("w:numId"))) for el in numbering.findall(qn("w:num"))]
    return (max(abstract_ids, default=-1) + 1, max(num_ids, default=0) + 1)


def _ensure_dash_numbering(document) -> int:
    """Register a TRUE list numbering whose glyph is "-" (the reference CV's
    list look). Returns the numId to reference from each list paragraph."""
    numbering = document.part.numbering_part.element
    abstract_id, num_id = _next_ids(numbering)

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    level.append(start)
    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "bullet")
    level.append(num_fmt)
    level_text = OxmlElement("w:lvlText")
    level_text.set(qn("w:val"), "-")
    level.append(level_text)
    level_jc = OxmlElement("w:lvlJc")
    level_jc.set(qn("w:val"), "left")
    level.append(level_jc)
    level_p_pr = OxmlElement("w:pPr")
    indent = OxmlElement("w:ind")
    indent.set(qn("w:left"), str(int(style_for("cv").bullet_indent_cm * 567)))
    indent.set(qn("w:hanging"), str(int(style_for("cv").bullet_indent_cm * 567)))
    level_p_pr.append(indent)
    level.append(level_p_pr)
    abstract.append(level)

    # schema order: every w:abstractNum BEFORE the first w:num
    first_num = numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num.append(abstract_ref)
    numbering.append(num)
    return num_id


def _apply_num_pr(paragraph, num_id: int) -> None:
    """Reference the list numbering from a paragraph (schema-safe position)."""
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_id_el = OxmlElement("w:numId")
    num_id_el.set(qn("w:val"), str(num_id))
    num_pr.append(ilvl)
    num_pr.append(num_id_el)
    # w:numPr belongs BEFORE spacing/ind/jc/rPr - insert before the first of them
    anchor = None
    for tag in ("w:spacing", "w:ind", "w:jc", "w:rPr"):
        anchor = p_pr.find(qn(tag))
        if anchor is not None:
            break
    if anchor is not None:
        anchor.addprevious(num_pr)
    else:
        p_pr.append(num_pr)


def _add_field(paragraph, code: str, style: DocStyle) -> None:
    """A Word field (PAGE / NUMPAGES) computed by the renderer/viewer."""
    run = paragraph.add_run()
    _style_run(run, style, size_key="footer")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = f" {code} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction, separate, end):
        run._r.append(element)


def _add_footer(document, footer: Footer, style: DocStyle) -> None:
    """Candidate name left, automatic "Page : X/Y" right, thin rule on top."""
    if not (footer.left_text or footer.page_numbering):
        return
    section = document.sections[0]
    footer_para = section.footer.paragraphs[0]
    for run in list(footer_para.runs):
        run._r.getparent().remove(run._r)
    # thin rule above the footer line (reference look)
    p_pr = footer_para._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), "4")
    top.set(qn("w:space"), "4")
    top.set(qn("w:color"), "A6A6A6")
    p_bdr.append(top)
    p_pr.append(p_bdr)
    # right-aligned tab stop at the content width
    footer_para.paragraph_format.tab_stops.add_tab_stop(
        Cm(PAGE_WIDTH_CM - MARGIN_LEFT_CM - MARGIN_RIGHT_CM), WD_TAB_ALIGNMENT.RIGHT
    )
    if footer.left_text:
        run = footer_para.add_run(footer.left_text)
        _style_run(run, style, size_key="footer")
    if footer.page_numbering:
        run = footer_para.add_run("\t" + FOOTER_SEPARATOR)
        _style_run(run, style, size_key="footer")
        _add_field(footer_para, "PAGE", style)
        slash = footer_para.add_run("/")
        _style_run(slash, style, size_key="footer")
        _add_field(footer_para, "NUMPAGES", style)
_ALIGN_OF = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
             "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


def _add_body_paragraph(document, text: str, style: DocStyle, *, size_key: str = "body",
                        align: Optional[Alignment] = None, bold: bool = False,
                        keep_with_next: bool = False, space_before_pt: float = 0.0) -> None:
    paragraph = document.add_paragraph()
    text_style = getattr(style, size_key)
    paragraph.alignment = _ALIGN_OF[(align or Alignment.JUSTIFY).value]
    paragraph.paragraph_format.space_after = Pt(text_style.space_after_pt)
    paragraph.paragraph_format.space_before = Pt(space_before_pt)
    paragraph.paragraph_format.line_spacing = text_style.line_spacing
    paragraph.paragraph_format.keep_together = True
    if keep_with_next:
        paragraph.paragraph_format.keep_with_next = True
    _add_runs_with_inline_markup(paragraph, text, style, size_key=size_key, base_bold=bold)


def _add_heading(document, text: str, style: DocStyle) -> None:
    """H1 section heading (left aligned, bold, kept with its content)."""
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_before = Pt(style.section_heading.space_before_pt)
    paragraph.paragraph_format.space_after = Pt(style.section_heading.space_after_pt)
    paragraph.paragraph_format.keep_with_next = style.keep_heading_with_next
    run = paragraph.add_run(text)
    _style_run(run, style, size_key="section_heading")


def _add_list_item(document, bullet: Bullet, style: DocStyle, num_id: int) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_after = Pt(2.0)
    paragraph.paragraph_format.line_spacing = style.body.line_spacing
    paragraph.paragraph_format.keep_together = True
    _apply_num_pr(paragraph, num_id)
    if bullet.label:
        label_run = paragraph.add_run(f"{bullet.label}: ")
        _style_run(label_run, style, size_key=bullet.size_key, bold=True)
    _add_runs_with_inline_markup(paragraph, bullet.text, style, size_key=bullet.size_key)


def _add_contact_paragraph(document, items: Sequence[Union[str, Link]], style: DocStyle,
                           align: Alignment = Alignment.CENTER, size_key: str = "status") -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = _ALIGN_OF[align.value]
    paragraph.paragraph_format.space_after = Pt(getattr(style, size_key).space_after_pt)
    paragraph.paragraph_format.keep_together = True
    for index, item in enumerate(items):
        if index > 0:
            separator = paragraph.add_run(" | ")
            _style_run(separator, style, size_key=size_key)
        if isinstance(item, Link):
            _add_hyperlink(paragraph, item.text, item.url, style, size_key=size_key)
        else:
            run = paragraph.add_run(str(item))
            _style_run(run, style, size_key=size_key)


def _render_experience_entry(document, entry: ExperienceEntry, style: DocStyle, num_id: int) -> None:
    """Reference look: bold role | bold company (location) | italic period."""
    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    heading.paragraph_format.space_before = Pt(style.entry_heading.space_before_pt)
    heading.paragraph_format.space_after = Pt(style.entry_heading.space_after_pt)
    heading.paragraph_format.keep_with_next = True
    heading.paragraph_format.keep_together = True
    if entry.role:
        run = heading.add_run(entry.role)
        _style_run(run, style, size_key="entry_heading")
    if entry.company:
        if entry.role:
            run = heading.add_run(" | ")
            _style_run(run, style, size_key="entry_heading")
        run = heading.add_run(entry.company)
        _style_run(run, style, size_key="entry_heading")
        if entry.location:
            run = heading.add_run(f" ({entry.location})")
            _style_run(run, style, size_key="entry_heading")
    if entry.period:
        if entry.role or entry.company:
            run = heading.add_run(" | ")
            _style_run(run, style, size_key="entry_heading")
        run = heading.add_run(entry.period)
        _style_run(run, style, size_key="entry_meta", italic=entry.period_italic)
    for paragraph in entry.paragraphs:
        _add_body_paragraph(document, paragraph.text, style, align=paragraph.align)
    for bullet in entry.bullets:
        _add_list_item(document, bullet, style, num_id)
def _render_cv(document, model: DocumentModel, style: DocStyle, num_id: int) -> None:
    """CV hierarchy (guide section 6): Name -> title -> status -> contact ->
    H1 sections. Centered header like the reference."""
    header = model.candidate
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(style.name.space_after_pt)
    run = paragraph.add_run(header.name)
    _style_run(run, style, size_key="name")
    if header.professional_title:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(style.subtitle.space_after_pt)
        run = paragraph.add_run(header.professional_title)
        _style_run(run, style, size_key="subtitle")
    if header.status_line:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(style.status.space_after_pt)
        run = paragraph.add_run(header.status_line)
        _style_run(run, style, size_key="status")
    if header.contact_items:
        _add_contact_paragraph(document, header.contact_items, style,
                               align=Alignment.CENTER, size_key="status")

    for section in model.sections:
        if section.heading:
            _add_heading(document, section.heading, style)
        if section.kind == "paragraphs":
            for paragraph in section.paragraphs:
                _add_body_paragraph(document, paragraph.text, style, align=paragraph.align)
        elif section.kind == "bullets":
            for bullet in section.bullets:
                _add_list_item(document, bullet, style, num_id)
        elif section.kind == "experience":
            for entry in section.experience:
                _render_experience_entry(document, entry, style, num_id)
        elif section.kind == "education":
            for item in section.education:
                heading = document.add_paragraph()
                heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
                heading.paragraph_format.space_after = Pt(2.0)
                heading.paragraph_format.keep_together = True
                run = heading.add_run(item.heading)
                _style_run(run, style, size_key="entry_heading")
                if item.metadata:
                    meta = document.add_paragraph()
                    meta.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    meta.paragraph_format.space_after = Pt(4.0)
                    run = meta.add_run(item.metadata)
                    _style_run(run, style, size_key="entry_meta")
        elif section.kind == "entries":
            for item in section.entries:
                line = item.text + (f" — {item.metadata}" if item.metadata else "")
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                paragraph.paragraph_format.space_after = Pt(2.0)
                paragraph.paragraph_format.keep_together = True
                _add_runs_with_inline_markup(paragraph, line, style)
def _render_cover_letter(document, model: DocumentModel, style: DocStyle) -> None:
    """Cover letter hierarchy (guide section 7): contact block -> date ->
    location -> subject -> salutation -> paragraphs -> closing -> signature."""
    if model.contact_block_lead:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(2.0)
        run = paragraph.add_run(model.contact_block_lead)
        _style_run(run, style, size_key="name")
    for item in model.contact_block:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(1.0)
        if isinstance(item, Link):
            _add_hyperlink(paragraph, item.text, item.url, style, size_key="body")
        else:
            run = paragraph.add_run(str(item))
            _style_run(run, style, size_key="body")
    if model.date_line:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_before = Pt(10.0)
        paragraph.paragraph_format.space_after = Pt(6.0)
        run = paragraph.add_run(model.date_line)
        _style_run(run, style, size_key="entry_heading")
    if model.location_line:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(6.0)
        run = paragraph.add_run(model.location_line)
        _style_run(run, style, size_key="body")
    if model.subject:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(6.0)
        run = paragraph.add_run(f"Subject : {model.subject}")
        _style_run(run, style, size_key="entry_heading")
    if model.salutation:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(6.0)
        run = paragraph.add_run(model.salutation)
        _style_run(run, style, size_key="entry_heading")
    for section in model.sections:
        for paragraph in section.paragraphs:
            _add_body_paragraph(document, paragraph.text, style, align=Alignment.JUSTIFY)
    if model.closing:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_before = Pt(10.0)
        paragraph.paragraph_format.space_after = Pt(2.0)
        run = paragraph.add_run(model.closing)
        _style_run(run, style, size_key="body")
    if model.signature:
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = paragraph.add_run(model.signature)
        _style_run(run, style, size_key="entry_heading")
def render_document(model: DocumentModel) -> bytes:
    """Render a structured DocumentModel to DOCX bytes (deterministic)."""
    if model.doc_type not in ("cv", "cover_letter"):
        raise DocumentRenderError(f"Unsupported document type: {model.doc_type!r}")
    style = style_for(model.doc_type)
    document = Document()
    _setup_page(document, style)
    num_id = _ensure_dash_numbering(document)
    if model.doc_type == "cv":
        _render_cv(document, model, style, num_id)
    else:
        _render_cover_letter(document, model, style)
    _add_footer(document, model.footer, style)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def render_document_to_file(model: DocumentModel, path) -> str:
    """Render straight to a file path; returns the path as a string."""
    path.write_bytes(render_document(model))
    return str(path)





