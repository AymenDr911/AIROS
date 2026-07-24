import docx
from pypdf import PdfReader
import streamlit as st

# 1. Page configuration
st.set_page_config(
    page_title="Master CV Manager",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. Render Navigation Sidebar (MATCHING FUNCTION NAME)
try:
  from utils.nav import render_sidebar

  render_sidebar()
except Exception as e:
  st.sidebar.error(f"Nav render error: {e}")

# 3. Local imports
from utils.cv_manager import get_master_cv, save_master_cv



# ==============================================================================
# 4. STORED DATA LOADING
# ==============================================================================
raw_text, parsed_json = get_master_cv()

st.title("📄 Master CV Knowledge Base")

# ==============================================================================
# 5. INPUT OPTIONS
# ==============================================================================
st.subheader("1. Update Master CV")
active_tab = st.radio(
    "Select Input Method:",
    ["📋 Paste Text", "📁 Upload File (PDF/DOCX/TXT)"],
    horizontal=True,
)

input_text = ""

if active_tab == "📋 Paste Text":
  input_text = st.text_area(
      "Paste your CV text here:",
      value=raw_text or "",
      height=250,
      key="pasted_cv_input",
  )

else:
  uploaded_file = st.file_uploader(
      "Upload Master CV File", type=["pdf", "docx", "txt"]
  )
  if uploaded_file:
    ext = uploaded_file.name.split(".")[-1].lower()
    if ext == "pdf":
      reader = PdfReader(uploaded_file)
      input_text = "\n".join(
          [p.extract_text() for p in reader.pages if p.extract_text()]
      )
    elif ext == "docx":
      doc = docx.Document(uploaded_file)
      input_text = "\n".join(
          [p.text for p in doc.paragraphs if p.text.strip()]
      )
    elif ext == "txt":
      input_text = uploaded_file.read().decode("utf-8")

# ==============================================================================
# 6. SAVE & PARSE ACTION
# ==============================================================================
if st.button("💾 Save & Parse Master CV", type="primary"):
  if input_text and input_text.strip():
    with st.spinner("Calling Gemini API to extract CV metadata..."):
      parsed_json = save_master_cv(input_text, force_reparse=True)

      if parsed_json and (
          parsed_json.get("technical_skills")
          or parsed_json.get("mandatory_skills")
      ):
        st.success("Master CV parsed and saved successfully to disk!")
      else:
        st.error(
            "Gemini returned an empty result. Please check the API error"
            " messages above."
        )

      st.rerun()
  else:
    st.warning("Please provide CV text or upload a file first.")

st.divider()

# ==============================================================================
# 7. KNOWLEDGE BASE VIEW
# ==============================================================================
st.subheader("2. Stored Knowledge Base")

if parsed_json and (
    parsed_json.get("technical_skills") or parsed_json.get("mandatory_skills")
):
  st.success(
      "✓ Active Master CV JSON loaded from disk (0 API Calls required for ATS"
      " runs)."
  )

  with st.expander("📊 View Structured CV (JSON)", expanded=True):
    st.json(parsed_json)

  with st.expander("📝 View Raw Text"):
    st.text_area(
        "Raw Text",
        value=raw_text or "",
        height=150,
        disabled=True,
        key="raw_view",
    )
else:
  st.info(
      "No valid Master CV parsed yet. Upload/Paste your CV above and click"
      " 'Save & Parse'."
  )