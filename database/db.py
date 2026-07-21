import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "airos.db")


def get_connection():
    """Returns a SQLite connection object with dict-like row access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes the AIROS SQLite database with modular, future-proof tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. USER PROFILE (Default single-user, ready for multi-user expansion)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            primary_target_roles TEXT, -- e.g. "Program Manager IT, ERP PM, BA, PMO"
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Insert default single-user profile if not present
    cursor.execute(
        """
        INSERT OR IGNORE INTO users (id, full_name, email, primary_target_roles)
        VALUES (1, 'Aymen Abdellaoui', 'aymen@example.com', 'IT Program Manager, ERP PM, BA, PMO, Project Controller')
    """
    )

    # 2. CV DOCUMENTS (Base Master CV + Tailored Persona Variants)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cvs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL,                  -- e.g. "Master CV v1" or "Tailored ERP PM"
            target_role TEXT,                     -- e.g. "ERP Project Manager"
            is_master BOOLEAN DEFAULT 0,          -- 1 = Base brutal CV, 0 = Tailored copy
            raw_text TEXT NOT NULL,               -- Full parsed text of the CV
            file_path TEXT,                       -- Local path to PDF/DOCX
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """
    )

    # 3. JOB OFFERS (Target job listings)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS job_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,                  -- e.g. "Senior ERP Project Manager"
            company_name TEXT NOT NULL,
            target_role_category TEXT,            -- Categorized as "ERP PM", "BA", "PMO", etc.
            location TEXT,
            description TEXT NOT NULL,            -- Full job description
            url TEXT,                             -- Job link
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # 4. ATS MATCH EVALUATIONS (Rich AI Match Analysis)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ats_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            cv_id INTEGER NOT NULL,
            match_score REAL NOT NULL,            -- e.g. 84.5
            matched_keywords TEXT,               -- Stored as JSON array: ["Agile", "Odoo", "PMP"]
            missing_keywords TEXT,               -- Stored as JSON array: ["SAP S/4HANA", "German B2"]
            fit_summary TEXT,                     -- AI narrative explaining fit
            recommendations TEXT,                 -- Suggestions to improve CV for this job
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES job_offers(id) ON DELETE CASCADE,
            FOREIGN KEY (cv_id) REFERENCES cvs(id) ON DELETE CASCADE
        )
    """
    )

    # 5. APPLICATION TRACKER (Lifecycle tracking)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            cv_id INTEGER,                        -- Tailored CV version submitted
            status TEXT DEFAULT 'Saved',          -- Saved, Analyzed, Applied, Screening, Interviewing, Offer, Rejected
            applied_date DATE,
            notes TEXT,                           -- Follow-up notes, contact info, feedback
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES job_offers(id) ON DELETE CASCADE,
            FOREIGN KEY (cv_id) REFERENCES cvs(id) ON DELETE SET NULL
        )
    """
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("AIROS Masterclass Database initialized successfully.")