import json
import sqlite3
from database.db import get_connection, init_db


# --- USER & CV MANAGEMENT ---
def save_master_cv(
    title: str,
    raw_text: str,
    target_role: str = "General Master",
    file_path: str = None,
):
    """Saves or updates the raw master CV (is_master=1)."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check if a master CV already exists
    cursor.execute("SELECT id FROM cvs WHERE user_id = 1 AND is_master = 1")
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            """
            UPDATE cvs
            SET title = ?, raw_text = ?, target_role = ?, file_path = ?, created_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """,
            (title, raw_text, target_role, file_path, existing["id"]),
        )
        cv_id = existing["id"]
    else:
        cursor.execute(
            """
            INSERT INTO cvs (user_id, title, target_role, is_master, raw_text, file_path)
            VALUES (1, ?, ?, 1, ?, ?)
        """,
            (title, target_role, raw_text, file_path),
        )
        cv_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return cv_id


def get_master_cv():
    """Retrieves the master raw CV for User 1."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cvs WHERE user_id = 1 AND is_master = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# --- JOB OFFERS ---
def add_job_offer(
    title: str,
    company_name: str,
    description: str,
    target_role_category: str = None,
    location: str = None,
    url: str = None,
):
    """Inserts a target job offer."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO job_offers (title, company_name, target_role_category, location, description, url)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            title,
            company_name,
            target_role_category,
            location,
            description,
            url,
        ),
    )
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id


def get_all_jobs():
    """Returns all saved job offers."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM job_offers ORDER BY created_at DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- ATS EVALUATIONS ---
def save_ats_evaluation(
    job_id: int,
    cv_id: int,
    match_score: float,
    matched_keywords: list,
    missing_keywords: list,
    fit_summary: str,
    recommendations: str,
):
    """Stores AI ATS evaluation metrics."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO ats_evaluations 
        (job_id, cv_id, match_score, matched_keywords, missing_keywords, fit_summary, recommendations)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            job_id,
            cv_id,
            match_score,
            json.dumps(matched_keywords),
            json.dumps(missing_keywords),
            fit_summary,
            recommendations,
        ),
    )
    conn.commit()
    conn.close()


# --- DASHBOARD METRICS ---
def get_dashboard_metrics():
    """Fetches high-level metrics for the Home dashboard."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM applications")
    apps_count = cursor.fetchone()["count"]

    cursor.execute(
        "SELECT COUNT(*) as count FROM applications WHERE status = 'Interviewing'"
    )
    interviews_count = cursor.fetchone()["count"]

    cursor.execute("SELECT AVG(match_score) as avg_score FROM ats_evaluations")
    avg_score_row = cursor.fetchone()["avg_score"]
    avg_ats = round(avg_score_row, 1) if avg_score_row else 0.0

    conn.close()
    return {
        "applications": apps_count,
        "interviews": interviews_count,
        "avg_ats": avg_ats,
    }
    