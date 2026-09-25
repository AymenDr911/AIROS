"""AIROS Document Builders (CHG-026).

Map the Document Engine's generated output (ai/documents.py) plus the caller's
OWN profile facts into the structured document model (documents/models.py).

HARD RULE - CONTENT PRESERVATION (guide section 9):
- the builder NEVER rewrites, summarizes, expands, invents, deletes, corrects
  or re-orders approved content;
- every rendered word comes from (a) the generated document payload, or (b) a
  factual profile/JD field (name, email, phone, linkedin, location, job title,
  job id / country for the letter subject and destination line);
- facts that are NOT available are simply left OUT of the layout - never
  invented to make the document look fuller.

Defensive normalisation everywhere: the Gemini schema pins only a few keys
(summary, skills, full_text, ...), so experience/education items are read
tolerantly over their known key aliases and anything unrecognised is still
rendered (as plain text) rather than dropped - content loss is a bug, not a
graceful degradation.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from documents.models import (
    Alignment,
    Bullet,
    CandidateHeader,
    DocumentModel,
    EducationEntry,
    ExperienceEntry,
    Footer,
    Link,
    Paragraph,
    Section,
    SimpleEntry,
)

# -----------------------------------------------------------------------------
# tiny defensive readers (never raise, never invent)
# -----------------------------------------------------------------------------
def _s(value: Any) -> str:
    """Any scalar -> stripped string ('' for None / containers)."""
    if value is None or isinstance(value, (dict, list, tuple)):
        return ""
    return str(value).strip()


def _lst(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _first(*values: Any) -> str:
    """First non-empty string among aliases."""
    for value in values:
        text = _s(value)
        if text:
            return text
    return ""


def _join_items(items: Iterable[Any]) -> str:
    """['Python', 'Docker'] -> 'Python, Docker' (facts joined, never reworded)."""
    parts = [_s(item) for item in items if _s(item)]
    return ", ".join(parts)


def _split_paragraphs(text: str) -> List[str]:
    """A generated text block -> paragraphs (blank-line separated)."""
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return []
    blocks = [block.strip() for block in raw.split("\n\n") if block.strip()]
    if len(blocks) > 1:
        return blocks
    lines = [line.strip() for line in raw.split("\n") if line.strip()]
    return ["\n".join(lines)] if lines else []


def _labelled(text: str) -> Tuple[str, str]:
    """"Agile, Scrum: led teams" -> ("Agile, Scrum", "led teams") - the bold
    lead-in the reference CV uses for competency bullets. Only splits on the
    FIRST ':' and only when the lead-in is short (< 60 chars) so real sentences
    are never mangled."""
    if ":" in text:
        head, rest = text.split(":", 1)
        if 0 < len(head.strip()) < 60:
            return head.strip(), rest.strip()
    return "", text.strip()


def _identity(profile: Dict[str, Any]) -> Dict[str, Any]:
    identity = profile.get("identity") if isinstance(profile, dict) else {}
    return identity if isinstance(identity, dict) else {}


def _candidate_name(identity: Dict[str, Any]) -> str:
    name = _first(identity.get("full_name"))
    if name:
        return name
    first, last = _s(identity.get("first_name")), _s(identity.get("last_name"))
    return f"{first} {last}".strip()


def _professional_title(profile: Dict[str, Any]) -> str:
    """FACT from the profile: the title of the most recent experience entry.
    Never invented; empty when the profile has no experience titles."""
    for entry in _lst(profile.get("experience")):
        if isinstance(entry, dict):
            title = _first(entry.get("title"), entry.get("role"), entry.get("position"))
            if title:
                return title
    return ""


def _status_line(identity: Dict[str, Any]) -> str:
    """Factual status items only: location / city+country / driving licence."""
    parts: List[str] = []
    location = _first(identity.get("location"))
    if not location:
        city, country = _s(identity.get("city")), _s(identity.get("country"))
        location = ", ".join(part for part in (city, country) if part)
    if location:
        parts.append(location)
    license_flag = identity.get("has_driver_license")
    if license_flag in (True, "true", "True", "yes", "Yes", 1, "1"):
        parts.append("Driving Licence (B)")
    return " | ".join(parts)


def _contact_items(identity: Dict[str, Any]) -> List[Union[str, Link]]:
    items: List[Union[str, Link]] = []
    email = _s(identity.get("email"))
    if email:
        items.append(Link(text=email, url=f"mailto:{email}"))
    phone = _first(identity.get("phone"), identity.get("whatsapp"))
    if phone:
        items.append(phone)
    linkedin = _first(identity.get("linkedin"))
    if linkedin:
        url = linkedin if linkedin.startswith("http") else f"https://{linkedin}"
        items.append(Link(text=url, url=url))
    return items


def _experience_entries(experience: List[Any]) -> List[ExperienceEntry]:
    entries: List[ExperienceEntry] = []
    for raw in experience:
        if not isinstance(raw, dict):
            text = _s(raw)
            if text:  # unstructured item: keep the text verbatim
                entries.append(ExperienceEntry(role=text))
            continue
        role = _first(raw.get("title"), raw.get("role"), raw.get("position"))
        company = _first(raw.get("company"), raw.get("employer"), raw.get("organisation"))
        location = _first(raw.get("location"), raw.get("city"), raw.get("country"))
        period = _first(raw.get("period"))
        if not period:
            start, end = _s(raw.get("start_date")), _s(raw.get("end_date"))
            if start and end:
                period = f"{start} – {end}"
            else:
                period = start or end
        paragraphs = [
            Paragraph(text=block)
            for block in _split_paragraphs(_first(raw.get("description"), raw.get("summary")))
        ]
        bullets = [
            Bullet(text=_s(item))
            for key in ("achievements", "bullets", "highlights")
            for item in _lst(raw.get(key))
            if _s(item)
        ]
        if not (role or company or paragraphs or bullets):
            text = _s(raw)
            if text:
                entries.append(ExperienceEntry(role=text))
            continue
        entries.append(ExperienceEntry(
            role=role, company=company, location=location, period=period,
            paragraphs=paragraphs, bullets=bullets,
        ))
    return entries
def build_cv_document(
    generated_cv: Dict[str, Any],
    profile: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> DocumentModel:
    """Generated CV payload + profile facts -> structured CV document.

    Section order mirrors the reference CV: Summary, Core Competencies &
    Technical Skills, Professional Experience, Education, Certifications,
    Languages. Sections with no content are omitted (never padded with
    invented text).
    """
    identity = _identity(profile)
    cv = generated_cv if isinstance(generated_cv, dict) else {}
    sections: List[Section] = []

    summary = _split_paragraphs(_s(cv.get("summary")))
    if summary:
        sections.append(Section(
            heading="Summary", kind="paragraphs",
            paragraphs=[Paragraph(text=block) for block in summary],
        ))

    skills = cv.get("skills") if isinstance(cv.get("skills"), dict) else {}
    competency_bullets: List[Bullet] = []
    for key, label in (
        ("technical", "Technical"),
        ("methodologies", "Methodologies & Management"),
        ("tools", "Tools"),
    ):
        joined = _join_items(_lst(skills.get(key)))
        if joined:
            competency_bullets.append(Bullet(label=label, text=joined))
    if competency_bullets:
        sections.append(Section(
            heading="Core Competencies & Technical Skills",
            kind="bullets", bullets=competency_bullets,
        ))

    experience = _experience_entries(_lst(cv.get("experience")))
    if experience:
        sections.append(Section(
            heading="Professional Experience", kind="experience", experience=experience,
        ))

    education_items: List[EducationEntry] = []
    for raw in _lst(cv.get("education")):
        if isinstance(raw, dict):
            heading = _first(
                raw.get("degree"), raw.get("field_of_study"), raw.get("field"), raw.get("title")
            )
            metadata = ", ".join(
                part for part in (
                    _first(raw.get("institution"), raw.get("school")),
                    _first(raw.get("year"), raw.get("graduation_year")),
                ) if part
            )
        else:
            heading, metadata = _s(raw), ""
        if heading or metadata:
            education_items.append(EducationEntry(heading=heading, metadata=metadata))
    if education_items:
        sections.append(Section(
            heading="Education", kind="education", education=education_items,
        ))

    cert_entries = [
        SimpleEntry(
            text=_s(item.get("name")) if isinstance(item, dict) else _s(item),
            metadata=", ".join(
                part for part in (
                    _s(item.get("issuer")) if isinstance(item, dict) else "",
                    _s(item.get("year")) if isinstance(item, dict) else "",
                ) if part
            ),
        )
        for item in _lst(cv.get("certifications"))
        if (_s(item.get("name")) if isinstance(item, dict) else _s(item))
    ]
    if cert_entries:
        sections.append(Section(heading="Certifications", kind="entries", entries=cert_entries))

    language_entries = [
        SimpleEntry(text=_labelled_lang(item)) for item in _lst(cv.get("languages"))
        if _labelled_lang(item)
    ]
    if language_entries:
        sections.append(Section(heading="Languages", kind="entries", entries=language_entries))

    return DocumentModel(
        doc_type="cv",
        candidate=CandidateHeader(
            name=_candidate_name(identity),
            professional_title=_professional_title(profile),
            status_line=_status_line(identity),
            contact_items=_contact_items(identity),
        ),
        footer=Footer(left_text=_candidate_name(identity), page_numbering=True),
        sections=sections,
        metadata=dict(meta or {}),
    )


def _labelled_lang(item: Any) -> str:
    """{language, level} / 'German (C1)' / 'German' -> 'German — C1'."""
    if isinstance(item, dict):
        name, level = _s(item.get("language")), _first(item.get("level"))
        return f"{name} — {level}" if name and level else name
    return _s(item)
def build_cover_letter_document(
    generated_cover_letter: Dict[str, Any],
    profile: Dict[str, Any],
    job: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> DocumentModel:
    """Generated cover letter + profile/JD facts -> structured cover letter.

    Hierarchy (guide section 7): Candidate Name -> Contact -> Date -> Location
    -> Subject -> Salutation -> Paragraphs -> Closing -> Signature -> Footer.

    - date: TODAY (system date) - a letter metadata fact, not generated content;
    - location/destination: the JD's country when known, else the profile
      location; omitted when neither exists;
    - subject: assembled deterministically from JD facts ("Application –
      {job title} (Job ID {job_id})") - never written by the LLM;
    - body wording comes verbatim from the generated opening/body/closing.
    """
    identity = _identity(profile)
    job = job if isinstance(job, dict) else {}
    letter = generated_cover_letter if isinstance(generated_cover_letter, dict) else {}
    parsed_job = job.get("job_json") if isinstance(job.get("job_json"), dict) else {}

    name = _candidate_name(identity)
    contact_block: List[Union[str, Link]] = []
    email = _s(identity.get("email"))
    if email:
        contact_block.append(Link(text=email, url=f"mailto:{email}"))
    linkedin = _first(identity.get("linkedin"))
    if linkedin:
        url = linkedin if linkedin.startswith("http") else f"https://{linkedin}"
        contact_block.append(Link(text=f"LinkedIn: {url}", url=url))
    whatsapp = _s(identity.get("whatsapp"))
    if whatsapp:
        contact_block.append(f"WhatsApp: {whatsapp}")

    job_title = _first(
        parsed_job.get("job_title"), job.get("title"),
        _professional_title(profile),
    )
    job_id = _first(job.get("job_id"), parsed_job.get("job_id"))
    subject_parts = ["Application"]
    if job_title:
        subject_parts.append(f"– {job_title}")
    subject = " ".join(subject_parts)
    if job_id:
        subject += f" (Job ID {job_id})"

    location_line = _first(parsed_job.get("country"), job.get("country"))
    if not location_line:
        location_line = _first(identity.get("location"), identity.get("country"))

    body_blocks = _split_paragraphs(_first(letter.get("body")))
    opening_blocks = _split_paragraphs(_first(letter.get("opening")))
    paragraphs = [Paragraph(text=block) for block in (opening_blocks + body_blocks)]

    today = date.today().strftime("%d %B %Y")

    return DocumentModel(
        doc_type="cover_letter",
        candidate=CandidateHeader(name=name),
        contact_block_lead=name,
        contact_block=contact_block,
        date_line=today,
        location_line=location_line,
        subject=subject,
        salutation=_first(letter.get("greeting"), "Dear Hiring Team,"),
        sections=[Section(
            heading="", kind="paragraphs",
            paragraphs=paragraphs,
        )] if paragraphs else [],
        closing=_first(letter.get("closing"), "Kind regards,"),
        signature=name,
        footer=Footer(left_text=name, page_numbering=True),
        metadata=dict(meta or {}),
    )
# __END__



