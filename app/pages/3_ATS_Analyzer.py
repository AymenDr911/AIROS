import importlib
import json
from pathlib import Path
import sqlite3
import streamlit as st

# Step A: Reload ATS module dynamically
import utils.ats
importlib.reload(utils.ats)

# Step B: Import required functions
from utils.ats import calculate_ats_gap, generate_tailored_cv
from utils.cv_manager import get_master_cv

# ==============================================================================
# 1. PAGE CONFIGURATION & NAVIGATION
# ==============================================================================
st.set_page_config(
    page_title="ATS Analyzer",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from utils.nav import render_sidebar
    render_sidebar()
except Exception as e:
    st.sidebar.error(f"Navigation error: {e}")


# ==============================================================================
# 2. HELPER FUNCTION: LOAD SAVED JOBS (ID + TITLE FORMATTING)
# ==============================================================================
def load_saved_jobs() -> dict:
    saved_jobs = {}

    project_root = Path(__file__).resolve().parent.parent
    possible_dbs = [
        project_root / "data" / "airos.db",
        project_root / "airos.db",
        project_root / "data" / "jobs.db",
        project_root / "jobs.db",
        Path("data/airos.db"),
        Path("data/jobs.db"),
        Path("airos.db"),
    ]

    for db_path in possible_dbs:
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                all_tables = [row[0] for row in cursor.fetchall()]

                job_tables = [
                    t
                    for t in all_tables
                    if ("job" in t.lower() or "offer" in t.lower())
                    and not any(x in t.lower() for x in ["cv", "resume", "master"])
                ]

                for table in job_tables:
                    cursor.execute(f"PRAGMA table_info({table})")
                    cols = [col[1].lower() for col in cursor.fetchall()]

                    id_col = next((c for c in cols if c == "id"), None)
                    title_col = next(
                        (c for c in cols if "title" in c or "role" in c or "position" in c),
                        None,
                    )
                    desc_col = next(
                        (
                            c
                            for c in cols
                            if "desc" in c
                            or "text" in c
                            or "details" in c
                            or "content" in c
                            or "requirements" in c
                        ),
                        None,
                    )
                    company_col = next(
                        (c for c in cols if "company" in c or "employer" in c), None
                    )

                    if title_col and desc_col:
                        select_cols = [id_col if id_col else "rowid", title_col, desc_col]
                        if company_col:
                            select_cols.append(company_col)

                        cursor.execute(f"SELECT {', '.join(select_cols)} FROM {table}")
                        rows = cursor.fetchall()

                        for row in rows:
                            job_id = row[0]
                            title = row[1]
                            desc = row[2]
                            company = (
                                row[3] if company_col and len(row) > 3 and row[3] else ""
                            )

                            if title and "master cv" in str(title).lower():
                                continue

                            label = f"[ID: {job_id}] {title} @ {company}" if company else f"[ID: {job_id}] {title}"

                            if desc:
                                saved_jobs[label] = str(desc)

                conn.close()
            except Exception:
                pass

    if "jobs" in st.session_state:
        session_jobs = st.session_state["jobs"]
        if isinstance(session_jobs, list):
            for idx, item in enumerate(session_jobs, 1):
                if isinstance(item, dict):
                    job_id = item.get("id", idx)
                    title = item.get("title") or item.get("role") or "Untitled Job"
                    if "master cv" in str(title).lower():
                        continue
                    company = item.get("company", "")
                    desc = (
                        item.get("description")
                        or item.get("job_description")
                        or item.get("text")
                        or ""
                    )
                    label = f"[ID: {job_id}] {title} @ {company}" if company else f"[ID: {job_id}] {title}"
                    if desc and label not in saved_jobs:
                        saved_jobs[label] = desc

    possible_files = [
        project_root / "data" / "jobs.json",
        project_root / "jobs.json",
        Path("data/jobs.json"),
    ]

    for file_path in possible_files:
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for idx, item in enumerate(data, 1):
                        if isinstance(item, dict):
                            job_id = item.get("id", idx)
                            title = item.get("title") or item.get("role") or "Untitled Position"
                            if "master cv" in str(title).lower():
                                continue
                            company = item.get("company", "")
                            desc = item.get("description") or item.get("text") or ""
                            label = f"[ID: {job_id}] {title} @ {company}" if company else f"[ID: {job_id}] {title}"
                            if desc and label not in saved_jobs:
                                saved_jobs[label] = desc
            except Exception:
                pass

    return saved_jobs


def redirect_to_jobs():
    try:
        st.switch_page("pages/2_Jobs.py")
    except Exception:
        try:
            st.switch_page("2_Jobs.py")
        except Exception as e:
            st.error(f"Unable to auto-redirect. Please navigate using the sidebar: {e}")


# ==============================================================================
# 3. LOAD MASTER CV FROM DISK
# ==============================================================================
cv_data = get_master_cv()

if cv_data and isinstance(cv_data, tuple):
    raw_cv_text, master_cv_json = cv_data
elif cv_data and isinstance(cv_data, dict):
    raw_cv_text = cv_data.get("raw_text", "") or cv_data.get("text", "")
    master_cv_json = cv_data
else:
    raw_cv_text, master_cv_json = "", {}
    st.info("ℹ️ No active CV found. Please select or upload a CV in the CV Manager.")


st.title("ATS Gap Analyzer & Match Engine")
st.caption("Deterministic match engine powered by local Master CV reuse.")

if not master_cv_json or (
    not master_cv_json.get("technical_skills")
    and not master_cv_json.get("mandatory_skills")
):
    st.error(
        "No active Master CV found. Please navigate to CV Manager first to save"
        " and parse your Master CV."
    )
    st.stop()

tech_count = len(master_cv_json.get("technical_skills", []))
exp_years = master_cv_json.get("experience_years", 0)
cert_count = len(master_cv_json.get("certifications", []))

st.info(
    f"Active Master CV Loaded: {tech_count} Technical Skills | {exp_years} Years"
    f" Experience | {cert_count} Certifications"
)

st.divider()

# ==============================================================================
# 4. TARGET JOB SELECTION & INPUT
# ==============================================================================
st.subheader("1. Target Job Description")

saved_jobs = load_saved_jobs()
job_text = ""

input_mode = st.radio(
    "Job Input Method:",
    ["Select from Saved Jobs", "Paste Custom Job Description"],
    horizontal=True,
)

if input_mode == "Select from Saved Jobs":
    if saved_jobs:
        search_query = st.text_input(
            "Search Saved Jobs:",
            placeholder="Filter by ID, Title, or Company...",
            key="job_filter_input",
        )

        all_titles = list(saved_jobs.keys())
        if search_query.strip():
            filtered_titles = [t for t in all_titles if search_query.lower() in t.lower()]
        else:
            filtered_titles = all_titles

        if filtered_titles:
            selected_title = st.selectbox(
                "Choose a saved job position:",
                options=filtered_titles,
                key="saved_job_combo",
            )
            default_text = saved_jobs.get(selected_title, "")

            job_text = st.text_area(
                "Job Description Text:",
                value=default_text,
                height=200,
                key=f"saved_jd_area_{selected_title}",
            )
        else:
            st.warning(f"No saved job offers found matching '{search_query}'.")
    else:
        st.info("No saved jobs found in system storage. You can redirect to the Jobs page to create one or paste below.")
        if st.button("Redirect to Jobs Page (2_Jobs.py)"):
            redirect_to_jobs()

        job_text = st.text_area(
            "Paste Job Description:",
            height=200,
            placeholder="Paste job posting text here...",
            key="fallback_jd_area",
        )
else:
    st.info("Working on a new job offer? You can analyze it directly or switch to the Jobs Manager page to save and track it.")
    col_nav, _ = st.columns([1, 3])
    with col_nav:
        if st.button("Go to Jobs Page (2_Jobs.py)", type="secondary"):
            redirect_to_jobs()

    job_text = st.text_area(
        "Paste Job Description:",
        height=200,
        placeholder="Paste job posting here (roles, requirements, qualifications)...",
        key="custom_jd_area",
    )

col_btn1, _ = st.columns([1, 4])
with col_btn1:
    analyze_clicked = st.button("Run ATS Analysis", type="primary")

# ==============================================================================
# 5. DETERMINISTIC MATCHING ENGINE & EXPLAINABILITY REPORT
# ==============================================================================
if analyze_clicked and job_text.strip():
    st.session_state["manual_approved"] = False
    st.session_state.pop("tailored_cv_output", None)

    with st.spinner("Extracting job requirements and running deterministic matching engine..."):
        results = calculate_ats_gap(master_cv_json, job_text)
        st.session_state["ats_results"] = results
        st.session_state["last_job_text"] = job_text

if "ats_results" in st.session_state and st.session_state["ats_results"]:
    results = st.session_state["ats_results"]
    sub_scores = results.get("sub_scores", {})
    hard_blockers = results.get("hard_blockers", [])
    score = results.get("ats_score", 0)

    st.divider()
    st.subheader("2. ATS Match Report & Assessment")

    if hard_blockers:
        st.warning("⚠️ CRITICAL HARD BLOCKERS DETECTED")
        for blocker in hard_blockers:
            st.markdown(f"- **{blocker}**")
    else:
        st.success("✅ NO HARD BLOCKERS DETECTED - All mandatory constraints satisfied.")

    st.write("")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label="Overall Match Score",
            value=f"{score}%",
            delta="Strong Fit" if score >= 80 else ("Moderate Risk" if score >= 75 else "Unfit Role"),
        )
    with col2:
        st.metric(label="Matched Tokens", value=f"{len(results.get('hits', []))} Items")
    with col3:
        st.metric(label="Missing Tokens / Gaps", value=f"{len(results.get('gaps', []))} Items")

    # ==============================================================================
    # 7-FACTOR WEIGHTED SUB-SCORES DISPLAY (FIXED PARSING & DISPLAY)
    # ==============================================================================
    st.markdown("### 7-Factor Weighted Sub-Scores")

    def parse_score(val) -> int:
        try:
            v = float(val)
            if 0.0 < v <= 1.0:
                return int(round(v * 100))
            return int(round(min(max(v, 0.0), 100.0)))
        except (ValueError, TypeError):
            return 0

    s_mand = parse_score(sub_scores.get("mandatory_skills", 0))
    s_tech = parse_score(sub_scores.get("technical_skills", 0))
    s_exp = parse_score(sub_scores.get("experience", 0))
    s_cert = parse_score(sub_scores.get("certifications", 0))
    s_kw = parse_score(sub_scores.get("keywords", 0))
    s_lang = parse_score(sub_scores.get("languages", 0))
    s_fmt = parse_score(sub_scores.get("formatting", 0))

    sub_col1, sub_col2 = st.columns(2)

    with sub_col1:
        st.markdown(f"**Mandatory Skills** *(Weight: 30%)* — **`{s_mand}%`**")
        st.progress(s_mand / 100.0)

        st.markdown(f"**Technical Skills** *(Weight: 25%)* — **`{s_tech}%`**")
        st.progress(s_tech / 100.0)

        st.markdown(f"**Experience Alignment** *(Weight: 15%)* — **`{s_exp}%`**")
        st.progress(s_exp / 100.0)

        st.markdown(f"**Certifications Match** *(Weight: 10%)* — **`{s_cert}%`**")
        st.progress(s_cert / 100.0)

    with sub_col2:
        st.markdown(f"**Keywords & Domain Terms** *(Weight: 10%)* — **`{s_kw}%`**")
        st.progress(s_kw / 100.0)

        st.markdown(f"**Language Requirements** *(Weight: 5%)* — **`{s_lang}%`**")
        st.progress(s_lang / 100.0)

        st.markdown(f"**ATS Formatting Compliance** *(Weight: 5%)* — **`{s_fmt}%`**")
        st.progress(s_fmt / 100.0)

    st.markdown("### Detailed Token Breakdown")
    col_hits, col_gaps = st.columns(2)

    with col_hits:
        with st.expander("Verified Matched Skills & Keywords", expanded=True):
            hits = results.get("hits", [])
            st.write(", ".join([f"`{h}`" for h in hits]) if hits else "No exact token matches found.")

    with col_gaps:
        with st.expander("Missing Target Skills & Keywords", expanded=True):
            gaps = results.get("gaps", [])
            st.write(", ".join([f"`{g}`" for g in gaps]) if gaps else "No skill gaps detected.")

    st.divider()

    # ==============================================================================
    # 6. DECISION ENGINE & AUTOMATED/MANUAL TAILORING WORKFLOW
    # ==============================================================================
    st.subheader("3. Tailoring Workflow Decision Engine")

    # Score >= 80% -> Automatic Tailoring
    if score >= 80:
        st.success(
            "🟢 **AUTOMATED TAILORING TRIGGERED** (Score ≥ 80%)\n\n"
            "Your profile is a strong match. Automatically customizing your Master CV."
        )

        if "tailored_cv_output" not in st.session_state:
            with st.spinner("Generating tailored CV..."):
                tailored_cv = generate_tailored_cv(
                    raw_cv_text or "",
                    st.session_state.get("last_job_text", ""),
                    results,
                )
                st.session_state["tailored_cv_output"] = tailored_cv

    # 75% <= Score < 80% -> Manual Approval Required
    elif 75 <= score < 80:
        st.warning(
            "🟡 **MANUAL APPROVAL REQUIRED** (75% ≤ Score < 80%)\n\n"
            "There is a **moderate-to-high risk of rejection** by the recruiter's ATS. "
            "Would you like to force tailoring anyway, or stop and search for a better job match?"
        )

        col_app1, col_app2 = st.columns(2)
        with col_app1:
            if st.button("Proceed with Tailoring (Manual Override)", type="primary"):
                st.session_state["manual_approved"] = True

        with col_app2:
            if st.button("Stop Process & Explore Other Jobs", type="secondary"):
                st.session_state["manual_approved"] = False
                st.info("Process stopped by user. Navigate to Jobs page to view other offers.")

        if st.session_state.get("manual_approved"):
            if "tailored_cv_output" not in st.session_state:
                with st.spinner("Generating tailored CV under manual override..."):
                    tailored_cv = generate_tailored_cv(
                        raw_cv_text or "",
                        st.session_state.get("last_job_text", ""),
                        results,
                    )
                    st.session_state["tailored_cv_output"] = tailored_cv

    # Score < 75% -> Process Suspended
    else:
        st.error(
            "🔴 **PROCESS SUSPENDED** (Score < 75%)\n\n"
            "Your Master CV profile does **not sufficiently fit** this job description. "
            "To save your time and prevent ATS rejection, tailoring is disabled for this role. "
            "We recommend stopping this application and focusing on job offers with higher profile alignment."
        )

    if "tailored_cv_output" in st.session_state:
        st.markdown("### Tailored CV Preview")
        st.text_area(
            "Tailored CV Text:",
            value=st.session_state["tailored_cv_output"],
            height=350,
        )
        st.download_button(
            label="Download Tailored CV (.txt)",
            data=st.session_state["tailored_cv_output"],
            file_name="Tailored_CV_AIROS.txt",
            mime="text/plain",
        )