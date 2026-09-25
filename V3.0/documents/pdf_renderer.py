"""AIROS PDF Renderer (CHG-026).

DOCX -> PDF via LibreOffice headless (guide section 3: the preferred, free and
local conversion path; no paid service, no second LLM call).

The converter is probed, never assumed: when LibreOffice is not installed the
caller gets a clean, actionable error (and the DOCX remains available) - a
formatting/conversion failure NEVER triggers a content regeneration (guide
section 10); the generated text content stays untouched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

CONVERT_TIMEOUT_S = 120

# well-known LibreOffice locations (macOS app bundle + common PATH installs)
_SOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/local/bin/soffice",
    "/opt/homebrew/bin/soffice",
    "/usr/bin/soffice",
    "/snap/bin/soffice",
)


class PdfConversionError(Exception):
    """DOCX -> PDF conversion failed. Content is untouched; report, don't retry."""


def soffice_path() -> Optional[str]:
    """Absolute soffice binary path, or None when LibreOffice is absent."""
    override = os.getenv("AIROS_SOFFICE_PATH", "").strip()
    if override:
        return override if Path(override).exists() else None
    for candidate in _SOFFICE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return found


def libreoffice_available() -> bool:
    """True when a headless LibreOffice conversion is possible right now."""
    return soffice_path() is not None


def convert_docx_to_pdf(docx_path: Path, out_dir: Optional[Path] = None) -> Path:
    """Convert one DOCX to PDF next to it (or in out_dir); returns the PDF path.

    Raises PdfConversionError when LibreOffice is missing, times out or fails -
    with an actionable message. The source DOCX is never modified.
    """
    source = Path(docx_path)
    if not source.exists():
        raise PdfConversionError(f"DOCX not found: {source}")
    binary = soffice_path()
    if not binary:
        raise PdfConversionError(
            "PDF conversion requires LibreOffice headless on the server "
            "(free, open-source). Install LibreOffice (or set AIROS_SOFFICE_PATH) "
            "and retry - the DOCX document remains available in the meantime."
        )
    target_dir = Path(out_dir) if out_dir else source.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    command = [
        binary, "--headless", "--norestore", "--nolockcheck",
        "--convert-to", "pdf", "--outdir", str(target_dir), str(source),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command, capture_output=True, text=True, timeout=CONVERT_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfConversionError(
            f"LibreOffice PDF conversion timed out after {CONVERT_TIMEOUT_S}s."
        ) from exc
    expected = target_dir / (source.stem + ".pdf")
    if completed.returncode != 0 or not expected.exists():
        detail = (completed.stderr or completed.stdout or "").strip()[-400:]
        raise PdfConversionError(
            f"LibreOffice PDF conversion failed (exit {completed.returncode}). {detail}"
        )
    return expected
