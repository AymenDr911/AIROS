# app/utils/document_storage.py
"""
Storage abstraction for generated documents.
Currently uses local disk. Designed so it can later be swapped for cloud storage
without changing business logic.
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import json
import streamlit as st


# Base folder (relative to project root)
BASE_DIR = Path(__file__).resolve().parent.parent / "generated"


def _job_dir(job_id: str) -> Path:
    path = BASE_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_document(
    job_id: str,
    doc_type: str,          # "cv" | "cover_letter" | "recruiter_email"
    content: str | dict,
    extension: str = "txt",
) -> str:
    """
    Save a generated document to disk.
    Returns the relative file path (string).
    """
    folder = _job_dir(job_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{doc_type}_{timestamp}.{extension}"
    file_path = folder / filename

    if isinstance(content, dict):
        file_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        file_path.write_text(str(content), encoding="utf-8")

    return str(file_path.relative_to(BASE_DIR.parent))


def get_documents_for_job(job_id: str) -> Dict[str, list]:
    """
    Return a dict of existing documents for a job:
    {
        "cv": [path1, path2, ...],
        "cover_letter": [...],
        "recruiter_email": [...]
    }
    """
    folder = _job_dir(job_id)
    result = {"cv": [], "cover_letter": [], "recruiter_email": []}

    if not folder.exists():
        return result

    for f in folder.iterdir():
        if not f.is_file():
            continue
        name = f.name.lower()
        if name.startswith("cv_"):
            result["cv"].append(str(f.relative_to(BASE_DIR.parent)))
        elif name.startswith("cover_letter_"):
            result["cover_letter"].append(str(f.relative_to(BASE_DIR.parent)))
        elif name.startswith("recruiter_email_"):
            result["recruiter_email"].append(str(f.relative_to(BASE_DIR.parent)))

    return result


def read_document(relative_path: str) -> Optional[str]:
    """Read a previously saved document."""
    full = Path(__file__).resolve().parent.parent / relative_path
    if full.exists():
        return full.read_text(encoding="utf-8")
    return None