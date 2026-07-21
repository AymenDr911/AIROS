import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "airos.db")

def get_connection():
    """Establish database connection with Foreign Key support and Row access enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row  # Enables column access by name (e.g., row['title'])
    return conn

def init_db():
    """Initialize relational database tables for AIROS."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Master CV Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS master_cv (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            target_role TEXT,
            raw_text TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Jobs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            role_category TEXT,
            location TEXT,
            work_type TEXT,
            url TEXT,
            description TEXT NOT NULL,
            questions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Custom CVs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_cvs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_cv_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            tailored_text TEXT NOT NULL,
            ats_score REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (master_cv_id) REFERENCES master_cv (id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        );
    """)

    # 4. Applications Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            cv_id INTEGER NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            method TEXT NOT NULL,
            status TEXT DEFAULT 'Applied',
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE,
            FOREIGN KEY (cv_id) REFERENCES custom_cvs (id) ON DELETE CASCADE
        );
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("✅ Database schema successfully initialized!")