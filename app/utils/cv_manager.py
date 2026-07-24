import json
from pathlib import Path
import streamlit as st

try:
  from .ats import parse_cv
except ImportError:
  from utils.ats import parse_cv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
CV_TEXT_PATH = DATA_DIR / "master_cv.txt"
CV_JSON_PATH = DATA_DIR / "master_cv_parsed.json"


def _ensure_data_dir():
  DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_master_cv(raw_text: str, force_reparse: bool = False) -> dict:
  """Saves raw text and creates master_cv_parsed.json ONCE via Gemini."""
  _ensure_data_dir()
  if not raw_text or not raw_text.strip():
    return {}

  # 1. Always save raw text
  CV_TEXT_PATH.write_text(raw_text.strip(), encoding="utf-8")

  # 2. Return existing valid JSON if present and reparse not forced
  if not force_reparse and CV_JSON_PATH.exists():
    try:
      existing = json.loads(CV_JSON_PATH.read_text(encoding="utf-8"))
      if existing.get("technical_skills") or existing.get("mandatory_skills"):
        return existing
    except Exception:
      pass

  # 3. Request fresh parse from Gemini
  parsed_data = parse_cv(raw_text, force_refresh=True)

  # 4. ONLY save JSON if parsing returned valid populated fields
  if parsed_data and (
      parsed_data.get("technical_skills")
      or parsed_data.get("mandatory_skills")
  ):
    CV_JSON_PATH.write_text(
        json.dumps(parsed_data, indent=2), encoding="utf-8"
    )
    return parsed_data

  # If parse failed, delete stale empty file if present
  if CV_JSON_PATH.exists():
    CV_JSON_PATH.unlink()

  return {}
  
def get_master_cv() -> tuple[str | None, dict | None]:
  """Loads raw text and parsed JSON from disk without calling AI."""
  _ensure_data_dir()
  raw_text = None
  parsed_json = None

  if CV_TEXT_PATH.exists():
    raw_text = CV_TEXT_PATH.read_text(encoding="utf-8")

  if CV_JSON_PATH.exists():
    try:
      parsed_json = json.loads(CV_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
      parsed_json = None

  return raw_text, parsed_json