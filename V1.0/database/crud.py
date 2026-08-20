import sqlite3
from database.db import get_connection, init_db


def ensure_db_ready():
    """Ensures database tables exist before executing queries."""
    try:
        init_db()
    except Exception:
        pass


# ==========================================
# 1. MASTER CV OPERATIONS
# ==========================================

def save_master_cv(title: str, target_role: str, raw_text: str):
    """Saves or updates the baseline Master CV."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO master_cv (title, target_role, raw_text)
        VALUES (?, ?, ?)
    """, (title, target_role, raw_text))
    conn.commit()
    cv_id = cursor.lastrowid
    conn.close()
    return cv_id

def get_latest_master_cv():
    """Fetches the most recent Master CV."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM master_cv ORDER BY id DESC LIMIT 1")
        cv = cursor.fetchone()
    except sqlite3.OperationalError:
        cv = None
    finally:
        conn.close()
    return cv

# Aliases for backward compatibility
get_master_cv = get_latest_master_cv


# ==========================================
# 2. JOBS OPERATIONS
# ==========================================

def add_job_offer(title: str, company: str, role_category: str = "", location: str = "", 
                  work_type: str = "", url: str = "", description: str = "", questions: str = ""):
    """Inserts a new job posting into the database."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO jobs (title, company, role_category, location, work_type, url, description, questions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, company, role_category, location, work_type, url, description, questions))
    conn.commit()
    job_id = cursor.lastrowid
    conn.close()
    return job_id

# Alias for general calls
add_job = add_job_offer

def get_all_jobs():
    """Retrieves all saved job postings, auto-seeding a sample job if empty."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        jobs = cursor.fetchall()

        # If the table exists but has 0 records, seed a starter job on the fly
        if not jobs:
            cursor.execute("""
                INSERT INTO jobs (title, company, role_category, location, work_type, url, description, questions)
                VALUES (
                    'Senior IT Program Manager', 
                    'IPACT Consult', 
                    'Program Management', 
                    'Tunis / Hybrid', 
                    'Full-time', 
                    'https://example.com', 
                    'Leading cross-functional software delivery teams, managing ERP implementations, backlog refinement, and sprint planning.',
                    'What is your experience with ERP systems?'
                )
            """)
            conn.commit()
            cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            jobs = cursor.fetchall()

    except sqlite3.OperationalError:
        jobs = []
    finally:
        conn.close()
    return jobs
    
def get_job_by_id(job_id: int):
    """Retrieves a single job posting by ID."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job = cursor.fetchone()
    except sqlite3.OperationalError:
        job = None
    finally:
        conn.close()
    return job

def delete_job(job_id: int):
    """Deletes a job posting and cascades deletion."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


# ==========================================
# 3. CUSTOM CVS OPERATIONS
# ==========================================

def save_custom_cv(master_cv_id: int, job_id: int, tailored_text: str, ats_score: float):
    """Stores a tailored CV variant linked to Master CV and Job ID."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO custom_cvs (master_cv_id, job_id, tailored_text, ats_score)
        VALUES (?, ?, ?, ?)
    """, (master_cv_id, job_id, tailored_text, ats_score))
    conn.commit()
    custom_cv_id = cursor.lastrowid
    conn.close()
    return custom_cv_id

def get_custom_cvs_for_job(job_id: int):
    """Fetches custom CV variants generated for a specific job."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM custom_cvs WHERE job_id = ? ORDER BY created_at DESC", (job_id,))
        cvs = cursor.fetchall()
    except sqlite3.OperationalError:
        cvs = []
    finally:
        conn.close()
    return cvs

def get_custom_cv_by_id(custom_cv_id: int):
    """Fetches a specific custom CV by ID."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM custom_cvs WHERE id = ?", (custom_cv_id,))
        cv = cursor.fetchone()
    except sqlite3.OperationalError:
        cv = None
    finally:
        conn.close()
    return cv


# ==========================================
# 4. APPLICATIONS TRACKING OPERATIONS
# ==========================================

def add_application(job_id: int, cv_id: int, method: str, status: str = "Applied", notes: str = ""):
    """Links Job posting and Custom CV into an Application record."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO applications (job_id, cv_id, method, status, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (job_id, cv_id, method, status, notes))
    conn.commit()
    app_id = cursor.lastrowid
    conn.close()
    return app_id

def get_all_applications():
    """Fetches applications joined with Job details and ATS scores."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 
                a.id as application_id,
                a.applied_at,
                a.method,
                a.status,
                a.notes,
                j.title as job_title,
                j.company,
                c.ats_score
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            JOIN custom_cvs c ON a.cv_id = c.id
            ORDER BY a.applied_at DESC
        """)
        apps = cursor.fetchall()
    except sqlite3.OperationalError:
        apps = []
    finally:
        conn.close()
    return apps

def update_application_status(app_id: int, status: str):
    """Updates application pipeline status."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


# ==========================================
# 5. DASHBOARD METRICS
# ==========================================

def get_dashboard_metrics():
    """Calculates live metrics for the Home dashboard safely."""
    ensure_db_ready()
    conn = get_connection()
    cursor = conn.cursor()

    app_count = 0
    interview_count = 0
    avg_score = 0.0

    # 1. Total Applications Count
    try:
        cursor.execute("SELECT COUNT(*) FROM applications")
        app_row = cursor.fetchone()
        app_count = app_row[0] if app_row else 0
    except sqlite3.OperationalError:
        app_count = 0

    # 2. Interviews / Screenings Count
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM applications 
            WHERE status LIKE '%Interview%' OR status LIKE '%Screening%'
        """)
        int_row = cursor.fetchone()
        interview_count = int_row[0] if int_row else 0
    except sqlite3.OperationalError:
        interview_count = 0

    # 3. Average ATS Score
    try:
        cursor.execute("SELECT COALESCE(AVG(ats_score), 0.0) FROM custom_cvs")
        score_row = cursor.fetchone()
        avg_score = score_row[0] if score_row and score_row[0] is not None else 0.0
    except sqlite3.OperationalError:
        avg_score = 0.0

    conn.close()

    return {
        "applications": app_count,
        "interviews": interview_count,
        "avg_ats_score": round(avg_score, 1)
    }