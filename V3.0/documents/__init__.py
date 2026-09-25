"""AIROS Document Engine - professional DOCX/PDF rendering (CHG-026).

Pipeline (guide section 3):
    AI content (ai/documents.py) -> structured document model (documents/models.py,
    built by documents/builders.py) -> schema validation (documents/validation.py)
    -> deterministic DOCX renderer (documents/docx_renderer.py)
    -> LibreOffice headless PDF (documents/pdf_renderer.py) -> content-integrity QA.

The renderer NEVER rewrites, invents, deletes or re-orders approved content,
and a formatting/conversion failure never triggers a content regeneration.
"""

from documents.docx_renderer import DocumentRenderError, render_document, render_document_to_file
from documents.models import DocumentModel
from documents.pdf_renderer import (
    PdfConversionError,
    convert_docx_to_pdf,
    libreoffice_available,
    soffice_path,
)
from documents.validation import (
    check_content_integrity,
    validate_document_model,
    validate_rendered_document,
)

__all__ = [
    "DocumentModel",
    "DocumentRenderError",
    "PdfConversionError",
    "check_content_integrity",
    "convert_docx_to_pdf",
    "libreoffice_available",
    "render_document",
    "render_document_to_file",
    "soffice_path",
    "validate_document_model",
    "validate_rendered_document",
]
