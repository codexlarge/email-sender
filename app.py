"""
app.py
Main Streamlit entry point for the Bulk Email Sender application.
"""
import os
import io
import re
import time
import uuid
import json
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# ── Ensure folders exist ───────────────────────────────────────────────────────
os.makedirs("templates", exist_ok=True)
os.makedirs("database", exist_ok=True)
os.makedirs("history", exist_ok=True)

load_dotenv()

# ── Internal modules ───────────────────────────────────────────────────────────
from database.db import (
    init_db, log_send, get_history, get_campaign_stats, clear_history,
    new_campaign_id, save_progress, get_progress, clear_progress,
)
from modules.csv_handler import render_email_column_selector, validate_and_clean, render_metadata
from modules.template_manager import render_manual_template_tab, render_template_selector, read_template, list_templates
from modules.condition_engine import render_condition_builder, evaluate_conditions
from modules.email_sender import send_email_brevo, personalise_template, personalise_subject, EmailSendError, extract_and_strip_title
from modules.ai_generator import render_ai_template_tab, generate_ai_email, get_provider_badge, get_llm

# ── Init DB ────────────────────────────────────────────────────────────────────
init_db()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Bulk Email Sender",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
# LAYOUT & SCROLL DIAGNOSIS & FIX:
# Root Cause: Multiple unconstrained components (recipient details card, template badges,
#             height-constrained components.html iframes, progress indicators) stacked directly
#             inside expanders and main view, pushing action buttons off-screen and trapping mouse wheel.
# Fix 1: Wrap stacked preview elements & review details into native st.container(height=..., border=True).
# Fix 2: Enforce overflow-y: auto and max-height constraints on section[data-testid="stMain"].
# Fix 3: Ensure [data-testid="stMainBlockContainer"] has generous bottom padding (8rem).
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* ── Scroll & Layout fixes ───────────────────────────────────────────── */
  section[data-testid="stMain"] {
    overflow-y: auto !important;
    scroll-behavior: smooth;
  }
  [data-testid="stMainBlockContainer"] {
    padding-bottom: 8rem !important;
    max-width: 100% !important;
  }
  div[data-testid="stElementContainer"],
  div[data-testid="stVerticalBlock"],
  div[data-testid="stVerticalBlockBorderWrapper"] {
    max-width: 100%;
  }

  /* ── Design tokens ───────────────────────────────────────────────────────── */
  .step-bar { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
  .step-pill {
    padding: 6px 16px; border-radius: 20px; font-size: 13px; font-weight: 600;
    border: 1.5px solid #4F46E5; color: #A5B4FC; background: transparent;
    white-space: nowrap;
  }
  .step-pill.active  { background: #4F46E5; color: #fff; }
  .step-pill.done    { background: #1E3A1E; color: #6EE7B7; border-color: #6EE7B7; }
  .card {
    background: #1A1A2E; border: 1px solid #2D2D4E; border-radius: 12px;
    padding: 20px; margin-bottom: 16px;
  }
  div[data-testid="stMetricValue"] { font-size: 2rem; color: #A5B4FC; }
  .send-counter {
    font-size: 18px; font-weight: 600; padding: 14px 20px;
    background: #1A1A2E; border-radius: 10px; border: 1px solid #2D2D4E;
    margin: 10px 0;
  }
  .workflow-badge {
    display: inline-block; padding: 4px 14px; border-radius: 20px;
    font-size: 12px; font-weight: 700; margin-left: 8px;
    background: #4F46E5; color: #fff;
  }
  .resume-banner {
    background: #1A2E1A; border: 1px solid #6EE7B7; border-radius: 10px;
    padding: 14px 18px; margin-bottom: 14px; color: #6EE7B7;
  }
</style>
""", unsafe_allow_html=True)



# ── Session state defaults ─────────────────────────────────────────────────────
DEFAULTS = {
    "step": 1,
    "workflow": "csv",          # "csv" | "single"
    "df_raw": None,
    "df_clean": None,
    "email_col": None,
    "single_email": "",         # for single-email workflow
    "selected_templates": [],
    "condition_rules": [],
    "default_template": None,
    "template_mode": "manual",
    "campaign_desc": "",
    "brand_name": "",
    "style_desc": "professional, modern, clean",
    "send_mode": "manual",
    "subject": "",
    "stop_sending": False,
    "campaign_id": None,
    "manual_index": 0,
    "ai_generated_html": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Helpers ────────────────────────────────────────────────────────────────────

def set_step(n: int):
    st.session_state["step"] = n


def step_done(n: int) -> bool:
    return st.session_state["step"] > n


def is_single_workflow() -> bool:
    return st.session_state.get("workflow") == "single"


def get_sample_row() -> dict | None:
    """Return the first row of df_clean as a dict, or None."""
    df = st.session_state.get("df_clean")
    if df is not None and len(df) > 0:
        return df.iloc[0].to_dict()
    return None


def render_step_bar():
    if is_single_workflow():
        steps = [
            "1: Enter Email",
            "2: Choose Template",
            "3: Set Conditions",
            "4: Send Email",
        ]
    else:
        steps = [
            "1: Upload CSV",
            "2: Validate Data",
            "3: Choose Template",
            "4: Set Conditions",
            "5: Send Emails",
        ]
    html = '<div class="step-bar">'
    for i, label in enumerate(steps, 1):
        if st.session_state["step"] == i:
            cls = "active"
        elif st.session_state["step"] > i:
            cls = "done"
        else:
            cls = ""
        html += f'<div class="step-pill {cls}">{"✓ " if cls == "done" else ""}{label}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def guard(required_step: int, label: str) -> bool:
    if st.session_state["step"] < required_step:
        st.warning(f"⚠️ Please complete **Step {required_step - 1}** first.")
        return False
    return True


_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_single_email(email: str) -> bool:
    return bool(_EMAIL_REGEX.match(email.strip()))


def make_single_row_df(email: str) -> pd.DataFrame:
    """Create a minimal single-row DataFrame for the single-email workflow."""
    return pd.DataFrame([{"Email": email}])


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📧 Bulk Email Sender")
    st.divider()

    # ── File uploader ──────────────────────────────────────────────────────────
    st.markdown("### 📂 Upload CSV")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"], key="csv_uploader")
    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded)
            if st.session_state["df_raw"] is None or uploaded.name != st.session_state.get("last_file"):
                st.session_state["df_raw"] = df
                st.session_state["df_clean"] = None
                st.session_state["email_col"] = None
                # Only reset step if we were in CSV workflow
                if st.session_state.get("workflow") == "csv":
                    st.session_state["step"] = 1
                st.session_state["last_file"] = uploaded.name
                # Load any saved progress for this file
                st.session_state["csv_progress"] = get_progress(uploaded.name)
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")

    # ── AI Provider badge ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🤖 AI Provider")
    st.markdown(get_provider_badge())

    # ── Settings summary ───────────────────────────────────────────────────────
    st.divider()
    st.markdown("### ⚙️ Sender Config")
    sender_email = os.getenv("BREVO_SENDER_EMAIL", "—")
    sender_name = os.getenv("BREVO_SENDER_NAME", "—")
    api_url = os.getenv("BREVO_API_URL", "https://api.brevo.com/v3/smtp/email")
    st.markdown(f"**Name:** {sender_name}")
    st.markdown(f"**Email:** {sender_email}")
    st.markdown(f"**API Endpoint:** `{api_url}`")

    # ── Send History ───────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📜 Send History")
    history_rows = get_history(limit=100)
    if history_rows:
        hist_df = pd.DataFrame(history_rows)
        st.dataframe(hist_df[["sent_at", "recipient_email", "status", "template_used"]],
                     use_container_width=True, hide_index=True, height=220)

        csv_buf = io.StringIO()
        hist_df.to_csv(csv_buf, index=False)
        st.download_button(
            "📥 Export History CSV",
            data=csv_buf.getvalue(),
            file_name="send_history.csv",
            mime="text/csv",
        )

        confirm_clear = st.checkbox("Confirm clear history", key="confirm_clear")
        if st.button("🗑️ Clear History", key="clear_hist_btn"):
            if confirm_clear:
                clear_history()
                st.success("History cleared.")
                st.rerun()
            else:
                st.warning("Check the confirmation box first.")
    else:
        st.info("No send history yet.")


# ── Main area ──────────────────────────────────────────────────────────────────
st.markdown("# 📧 Bulk Email Sender")

# ── Workflow Selector ──────────────────────────────────────────────────────────
wf_col1, wf_col2 = st.columns([3, 1])
with wf_col1:
    wf_choice = st.radio(
        "**Choose Workflow:**",
        ["📂 CSV Bulk Send", "✉️ Single Email"],
        horizontal=True,
        key="workflow_radio",
    )
new_wf = "csv" if "CSV" in wf_choice else "single"

# Reset session when workflow changes to avoid cross-contamination
if new_wf != st.session_state.get("workflow"):
    st.session_state["workflow"] = new_wf
    st.session_state["step"] = 1
    st.session_state["df_clean"] = None
    st.session_state["selected_templates"] = []
    st.session_state["condition_rules"] = []
    st.session_state["default_template"] = None
    st.session_state["subject"] = ""
    st.session_state["manual_index"] = 0
    st.session_state["campaign_id"] = None
    st.rerun()

render_step_bar()
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# ─── SINGLE EMAIL WORKFLOW ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
if is_single_workflow():

    # ── Single Step 1: Enter Email ────────────────────────────────────────────
    with st.expander("✉️ Step 1: Enter Email Address",
                     expanded=(st.session_state["step"] == 1)):
        st.markdown("Enter the recipient's email address to get started.")
        single_email_input = st.text_input(
            "Recipient Email Address",
            value=st.session_state.get("single_email", ""),
            placeholder="e.g. john@example.com",
            key="single_email_input",
        )

        if st.button("✅ Validate & Proceed", key="single_step1_proceed"):
            email_val = single_email_input.strip()
            if not email_val:
                st.error("❌ Please enter an email address.")
            elif not validate_single_email(email_val):
                st.error(f"❌ **`{email_val}`** is not a valid email address.")
            else:
                st.session_state["single_email"] = email_val
                # Build a synthetic single-row DataFrame so all downstream
                # functions (conditions, personalise, send) work without changes.
                df_single = make_single_row_df(email_val)
                st.session_state["df_clean"] = df_single
                st.session_state["email_col"] = "Email"
                st.success(f"✅ Valid email: **{email_val}**")
                set_step(2)
                st.rerun()

    # ── Single Step 2: Choose Template (same as CSV Step 3) ───────────────────
    with st.expander("📄 Step 2: Choose Template",
                     expanded=(st.session_state["step"] == 2)):
        if not guard(2, "Step 2"):
            pass
        else:
            mode_col1, _ = st.columns(2)
            with mode_col1:
                template_mode = st.radio(
                    "Template source:",
                    ["📄 Manual Template", "🤖 AI Generated Template"],
                    horizontal=True,
                    key="single_template_mode_radio",
                )
            st.session_state["template_mode"] = (
                "manual" if "Manual" in template_mode else "ai"
            )

            tab_manual, tab_ai = st.tabs(["📄 Manual Template", "🤖 AI Generated Template"])

            # For single-email workflow there's no CSV row, so sample_row is None.
            with tab_manual:
                render_manual_template_tab(sample_row=None)
                render_template_selector(sample_row=None)

            with tab_ai:
                render_ai_template_tab()
                if st.session_state["template_mode"] == "ai":
                    st.markdown("---")
                    st.session_state["campaign_desc"] = st.text_area(
                        "Campaign description:",
                        value=st.session_state.get("campaign_desc", ""),
                        height=80,
                        key="single_send_campaign_desc",
                    )
                    st.session_state["brand_name"] = st.text_input(
                        "Brand name:",
                        value=st.session_state.get("brand_name", ""),
                        key="single_send_brand_name",
                    )
                    st.session_state["style_desc"] = st.text_input(
                        "Style description:",
                        value=st.session_state.get("style_desc", "professional, modern, clean"),
                        key="single_send_style_desc",
                    )

            if st.button("✅ Proceed to Conditions", key="single_step2_proceed"):
                if st.session_state["template_mode"] == "manual":
                    if not st.session_state.get("selected_templates"):
                        st.error("Please select at least one template before proceeding.")
                    else:
                        set_step(3)
                        st.rerun()
                else:
                    set_step(3)
                    st.rerun()

    # ── Single Step 3: Set Conditions ─────────────────────────────────────────
    with st.expander("🔀 Step 3: Set Conditions",
                     expanded=(st.session_state["step"] == 3)):
        if not guard(3, "Step 3"):
            pass
        else:
            df_clean = st.session_state.get("df_clean")
            if df_clean is not None:
                rules, default_template = render_condition_builder(df_clean)
                st.session_state["condition_rules"] = rules
                st.session_state["default_template"] = default_template
            else:
                st.warning("No data found. Please complete Step 1 first.")

            if st.button("✅ Proceed to Send Email", key="single_step3_proceed"):
                set_step(4)
                st.rerun()

    # ── Single Step 4: Send Email ──────────────────────────────────────────────
    with st.expander("🚀 Step 4: Send Email",
                     expanded=(st.session_state["step"] == 4)):
        if not guard(4, "Step 4"):
            pass
        else:
            df_send = st.session_state.get("df_clean")
            email_col = st.session_state.get("email_col")
            rules = st.session_state.get("condition_rules", [])
            default_tmpl = st.session_state.get("default_template")
            selected_tmpls = st.session_state.get("selected_templates", [])
            template_mode = st.session_state.get("template_mode", "manual")
            single_email = st.session_state.get("single_email", "")

            if not single_email:
                st.warning("Please complete Step 1 first.")
            else:
                row = {email_col: single_email}

                # ── Resolve template ───────────────────────────────────────────
                def resolve_single_template(row: dict) -> tuple:
                    """Resolve template for a single row, extract title, return
                    (tmpl_name, html_body, extracted_title)."""
                    if template_mode == "ai":
                        try:
                            html = generate_ai_email(
                                row=row,
                                campaign_description=st.session_state.get("campaign_desc", ""),
                                brand_name=st.session_state.get("brand_name", ""),
                                style_description=st.session_state.get("style_desc",
                                                                        "professional, modern, clean"),
                            )
                        except RuntimeError as e:
                            raise RuntimeError(str(e))
                        title, html_body = extract_and_strip_title(html)
                        return "AI Generated", html_body, title
                    else:
                        row_series = pd.Series(row)
                        if rules:
                            tmpl_name = evaluate_conditions(row_series, rules, default_tmpl)
                        else:
                            tmpl_name = selected_tmpls[0] if selected_tmpls else None
                        if not tmpl_name:
                            raise RuntimeError("No template resolved for this row.")
                        html = read_template(tmpl_name)
                        title, html_no_title = extract_and_strip_title(html)
                        html_body = personalise_template(html_no_title, row)
                        return tmpl_name, html_body, title

                # ── Subject input ──────────────────────────────────────────────
                st.markdown("#### ✉️ Email Subject")

                # Try to extract title hint from the first selected template
                title_hint = None
                if selected_tmpls:
                    try:
                        raw_html = read_template(selected_tmpls[0])
                        title_hint, _ = extract_and_strip_title(raw_html)
                    except Exception:
                        pass

                subject_default = st.session_state.get("subject") or title_hint or ""
                subject = st.text_input(
                    "Subject line:",
                    value=subject_default,
                    key="single_email_subject_input",
                )
                if title_hint and not st.session_state.get("subject"):
                    st.caption(f"📌 Subject auto-filled from template `<title>`: *{title_hint}*")
                st.session_state["subject"] = subject

                personalised_subject = personalise_subject(subject, row)

                # Fix: Bundle preview elements into a scrollable container to keep send buttons visible
                with st.container(height=520, border=True):
                    st.markdown(
                        f'<div class="card">'
                        f'<b>To:</b> {single_email}<br>'
                        f'<b>Subject:</b> {personalised_subject}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # Resolve preview
                    if st.session_state.get("single_html_preview") is None:
                        try:
                            tmpl_name, html_content, _ = resolve_single_template(row)
                            st.session_state["single_html_preview"] = html_content
                            st.session_state["single_tmpl_name"] = tmpl_name
                        except RuntimeError as e:
                            st.error(f"Template error: {e}")
                            html_content = ""
                            tmpl_name = "—"
                    else:
                        html_content = st.session_state["single_html_preview"]
                        tmpl_name = st.session_state.get("single_tmpl_name", "—")

                    st.markdown(f"**Template:** `{tmpl_name}`")
                    st.markdown("**Email Preview:**")
                    if html_content:
                        components.html(html_content, height=360, scrolling=True)

                send_col, reset_col = st.columns(2)
                with send_col:
                    if st.button("📤 Send Email", key="single_send_btn"):
                        if not st.session_state.get("campaign_id"):
                            st.session_state["campaign_id"] = new_campaign_id()
                        try:
                            final_html = st.session_state.get("single_html_preview", "")
                            send_email_brevo(single_email, single_email, personalised_subject, final_html)
                            log_send(
                                st.session_state["campaign_id"],
                                single_email, single_email, personalised_subject,
                                tmpl_name, "sent",
                            )
                            st.success(f"✅ Email sent to **{single_email}**!")
                            st.session_state["single_html_preview"] = None
                        except EmailSendError as e:
                            st.error(f"❌ Send failed: {e}")
                            log_send(
                                st.session_state["campaign_id"],
                                single_email, single_email, personalised_subject,
                                tmpl_name, "failed", str(e),
                            )

                with reset_col:
                    if st.button("🔄 Send to Another Email", key="single_reset_btn"):
                        st.session_state["step"] = 1
                        st.session_state["single_email"] = ""
                        st.session_state["single_html_preview"] = None
                        st.session_state["df_clean"] = None
                        st.session_state["campaign_id"] = None
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ─── CSV BULK SEND WORKFLOW ───────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
else:

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1 — Upload & Email Column
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📁 Step 1: Upload CSV & Select Email Column",
                     expanded=(st.session_state["step"] == 1)):
        if st.session_state["df_raw"] is None:
            st.info("👈 Upload a CSV file using the sidebar to get started.")
        else:
            df_raw = st.session_state["df_raw"]
            st.markdown(f"**Loaded file:** `{st.session_state.get('last_file', 'unknown')}` "
                        f"— {len(df_raw)} rows, {len(df_raw.columns)} columns")

            email_col = render_email_column_selector(df_raw)

            if email_col:
                st.session_state["email_col"] = email_col
                if st.button("✅ Confirm & Proceed to Validation", key="step1_proceed"):
                    set_step(2)
                    st.rerun()


    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2 — Data Validation & Metadata
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🔍 Step 2: Validate Data",
                     expanded=(st.session_state["step"] == 2)):
        if not guard(2, "Step 2"):
            pass
        else:
            if st.session_state["df_clean"] is None:
                with st.spinner("Running data validation…"):
                    df_clean = validate_and_clean(
                        st.session_state["df_raw"].copy(),
                        st.session_state["email_col"],
                    )
                    st.session_state["df_clean"] = df_clean
            else:
                df_clean = st.session_state["df_clean"]
                with st.expander("🔍 Validation Report (already run)", expanded=False):
                    st.dataframe(df_clean.head(5), use_container_width=True)

            render_metadata(st.session_state["df_clean"])

            if st.button("✅ Proceed to Template Selection", key="step2_proceed"):
                set_step(3)
                st.rerun()


    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3 — Template Management
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📄 Step 3: Choose Template",
                     expanded=(st.session_state["step"] == 3)):
        if not guard(3, "Step 3"):
            pass
        else:
            mode_col1, mode_col2 = st.columns(2)
            with mode_col1:
                template_mode = st.radio(
                    "Template source:",
                    ["📄 Manual Template", "🤖 AI Generated Template"],
                    horizontal=True,
                    key="template_mode_radio",
                )
            st.session_state["template_mode"] = (
                "manual" if "Manual" in template_mode else "ai"
            )

            # Fix 3: pass sample_row so previews show real CSV values
            sample_row = get_sample_row()

            tab_manual, tab_ai = st.tabs(["📄 Manual Template", "🤖 AI Generated Template"])

            with tab_manual:
                render_manual_template_tab(sample_row=sample_row)
                selected = render_template_selector(sample_row=sample_row)

            with tab_ai:
                render_ai_template_tab()
                if st.session_state["template_mode"] == "ai":
                    st.markdown("---")
                    st.markdown("**AI Sending Config**")
                    st.session_state["campaign_desc"] = st.text_area(
                        "Campaign description (used for per-row AI generation):",
                        value=st.session_state.get("campaign_desc", ""),
                        height=80,
                        key="send_campaign_desc",
                    )
                    st.session_state["brand_name"] = st.text_input(
                        "Brand name:",
                        value=st.session_state.get("brand_name", ""),
                        key="send_brand_name",
                    )
                    st.session_state["style_desc"] = st.text_input(
                        "Style description:",
                        value=st.session_state.get("style_desc", "professional, modern, clean"),
                        key="send_style_desc",
                    )

            if st.button("✅ Proceed to Conditions", key="step3_proceed"):
                if st.session_state["template_mode"] == "manual":
                    if not st.session_state.get("selected_templates"):
                        st.error("Please select at least one template before proceeding.")
                    else:
                        set_step(4)
                        st.rerun()
                else:
                    set_step(4)
                    st.rerun()


    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4 — Condition Engine
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🔀 Step 4: Set Conditions",
                     expanded=(st.session_state["step"] == 4)):
        if not guard(4, "Step 4"):
            pass
        else:
            df_clean = st.session_state.get("df_clean")
            if df_clean is not None:
                rules, default_template = render_condition_builder(df_clean)
                st.session_state["condition_rules"] = rules
                st.session_state["default_template"] = default_template
            else:
                st.warning("No cleaned data found. Please complete Step 2 first.")

            if st.button("✅ Proceed to Send Emails", key="step4_proceed"):
                set_step(5)
                st.rerun()


    # ══════════════════════════════════════════════════════════════════════════
    # STEP 5 — Send Emails
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🚀 Step 5: Send Emails",
                     expanded=(st.session_state["step"] == 5)):
        if not guard(5, "Step 5"):
            pass
        else:
            df_send = st.session_state.get("df_clean")
            email_col = st.session_state.get("email_col")
            rules = st.session_state.get("condition_rules", [])
            default_tmpl = st.session_state.get("default_template")
            selected_tmpls = st.session_state.get("selected_templates", [])
            template_mode = st.session_state.get("template_mode", "manual")

            if df_send is None or email_col is None:
                st.warning("Please complete the previous steps first.")
            else:
                # Subject input — pre-fill hint from first selected template's <title>
                st.markdown("#### ✉️ Email Subject")
                title_hint = None
                if selected_tmpls and template_mode == "manual":
                    try:
                        raw_html = read_template(selected_tmpls[0])
                        title_hint, _ = extract_and_strip_title(raw_html)
                    except Exception:
                        pass

                subject_default = st.session_state.get("subject") or title_hint or "Hello {{first_name}}!"
                subject = st.text_input(
                    "Subject line (supports {{column_name}} placeholders):",
                    value=subject_default,
                    key="email_subject_input",
                )
                if title_hint and not st.session_state.get("subject"):
                    st.caption(f"📌 Subject auto-filled from template `<title>`: *{title_hint}*")
                st.session_state["subject"] = subject

                # Send mode
                st.markdown("#### 📤 Send Mode")
                send_mode = st.radio(
                    "Choose Send Mode:",
                    ["🖐️ Manual Review", "🚀 Auto Send"],
                    horizontal=True,
                    key="send_mode_radio",
                )

                st.divider()

                # ── Helper: resolve template for a row ─────────────────────────
                def resolve_template_for_row(row: dict) -> tuple:
                    """Returns (template_name, html_body).
                    Extracts and strips <title> from HTML before returning.
                    """
                    if template_mode == "ai":
                        try:
                            html = generate_ai_email(
                                row=row,
                                campaign_description=st.session_state.get("campaign_desc", ""),
                                brand_name=st.session_state.get("brand_name", ""),
                                style_description=st.session_state.get("style_desc",
                                                                        "professional, modern, clean"),
                            )
                        except RuntimeError as e:
                            raise RuntimeError(str(e))
                        _, html_body = extract_and_strip_title(html)
                        return "AI Generated", html_body
                    else:
                        row_series = pd.Series(row)
                        if rules:
                            tmpl_name = evaluate_conditions(row_series, rules, default_tmpl)
                        else:
                            tmpl_name = selected_tmpls[0] if selected_tmpls else None

                        if not tmpl_name:
                            raise RuntimeError("No template resolved for this row.")

                        html = read_template(tmpl_name)
                        # Fix 4: strip <title> before personalising & sending
                        _, html_no_title = extract_and_strip_title(html)
                        html_body = personalise_template(html_no_title, row)
                        return tmpl_name, html_body


                # ══════════════════════════════════════════════════════════════
                # MANUAL REVIEW MODE
                # ══════════════════════════════════════════════════════════════
                if "Manual" in send_mode:
                    total = len(df_send)
                    current_file = st.session_state.get("last_file", "")

                    # Resume: initialise manual_index from saved progress
                    saved_progress = st.session_state.get("csv_progress")
                    if (saved_progress and
                            saved_progress.get("filename") == current_file and
                            st.session_state.get("manual_index", 0) == 0):
                        resume_row = saved_progress["last_sent_row"] + 1
                        if 0 < resume_row < total:
                            st.markdown(
                                f'<div class="resume-banner">▶️ Resuming from row '
                                f'<b>{resume_row + 1}</b> of <b>{total}</b> — '
                                f'{resume_row} email(s) already sent.</div>',
                                unsafe_allow_html=True,
                            )
                            rc1, rc2 = st.columns(2)
                            with rc1:
                                if st.button("▶️ Resume", key="manual_resume_btn"):
                                    st.session_state["manual_index"] = resume_row
                                    st.rerun()
                            with rc2:
                                if st.button("🔄 Start Fresh", key="manual_fresh_btn"):
                                    clear_progress(current_file)
                                    st.session_state["csv_progress"] = None
                                    st.session_state["manual_index"] = 0
                                    st.rerun()
                            st.stop()

                    idx = st.session_state.get("manual_index", 0)

                    if idx >= total:
                        st.success(
                            f"🎉 All {total} emails reviewed! Check the send history in the sidebar."
                        )
                        if st.button("🔄 Start Over", key="manual_restart"):
                            st.session_state["manual_index"] = 0
                            clear_progress(current_file)
                            st.session_state["csv_progress"] = None
                            st.rerun()
                    else:
                        stop_col, prog_col = st.columns([1, 3])
                        with stop_col:
                            if st.button("🛑 Stop Sending", key="manual_stop"):
                                st.session_state["manual_index"] = total
                                st.warning("Sending stopped by user.")
                                st.rerun()
                        with prog_col:
                            st.progress(idx / total, text=f"Email {idx + 1} of {total}")

                        row = df_send.iloc[idx].to_dict()
                        to_email = str(row.get(email_col, "")).strip()

                        name_col_candidates = [c for c in df_send.columns
                                               if any(k in c.lower() for k in ["name", "first", "full"])]
                        to_name = str(row.get(name_col_candidates[0], "")) if name_col_candidates else to_email

                        personalised_subject = personalise_subject(subject, row)

                        # Fix: Bundle recipient card, template badge, and iframe preview into a bounded scroll container
                        with st.container(height=520, border=True):
                            st.markdown(
                                f'<div class="card">'
                                f'<b>To:</b> {to_email}<br>'
                                f'<b>Name:</b> {to_name}<br>'
                                f'<b>Subject:</b> {personalised_subject}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                            # Resolve template (cached per index)
                            if st.session_state.get(f"manual_html_{idx}") is None:
                                try:
                                    tmpl_name, html_content = resolve_template_for_row(row)
                                    st.session_state[f"manual_html_{idx}"] = html_content
                                    st.session_state[f"manual_tmpl_{idx}"] = tmpl_name
                                except RuntimeError as e:
                                    st.error(f"Template error: {e}")
                                    if not st.session_state.get("campaign_id"):
                                        st.session_state["campaign_id"] = new_campaign_id()
                                    log_send(
                                        st.session_state["campaign_id"],
                                        to_email, to_name, personalised_subject,
                                        "error", "failed", str(e),
                                    )
                                    st.session_state["manual_index"] = idx + 1
                                    st.rerun()

                            html_content = st.session_state.get(f"manual_html_{idx}", "")
                            tmpl_name = st.session_state.get(f"manual_tmpl_{idx}", "—")

                            st.markdown(f"**Template:** `{tmpl_name}`")
                            st.markdown("**Email Preview:**")
                            components.html(html_content, height=360, scrolling=True)

                        send_col, skip_col = st.columns(2)
                        with send_col:
                            if st.button("📤 Send this Email", key=f"send_btn_{idx}"):
                                if not st.session_state.get("campaign_id"):
                                    st.session_state["campaign_id"] = new_campaign_id()
                                try:
                                    send_email_brevo(to_email, to_name, personalised_subject, html_content)
                                    log_send(
                                        st.session_state["campaign_id"],
                                        to_email, to_name, personalised_subject,
                                        tmpl_name, "sent",
                                    )
                                    # Fix 5: persist progress after each successful send
                                    save_progress(current_file, total, idx)
                                    st.toast(f"✅ Sent to {to_email}")
                                except EmailSendError as e:
                                    st.error(f"❌ Send failed: {e}")
                                    log_send(
                                        st.session_state["campaign_id"],
                                        to_email, to_name, personalised_subject,
                                        tmpl_name, "failed", str(e),
                                    )
                                st.session_state["manual_index"] = idx + 1
                                st.session_state.pop(f"manual_html_{idx}", None)
                                st.session_state.pop(f"manual_tmpl_{idx}", None)
                                st.rerun()

                        with skip_col:
                            if st.button("⏭️ Skip", key=f"skip_btn_{idx}"):
                                if not st.session_state.get("campaign_id"):
                                    st.session_state["campaign_id"] = new_campaign_id()
                                log_send(
                                    st.session_state["campaign_id"],
                                    to_email, to_name, personalised_subject,
                                    tmpl_name, "skipped",
                                )
                                st.session_state["manual_index"] = idx + 1
                                st.session_state.pop(f"manual_html_{idx}", None)
                                st.session_state.pop(f"manual_tmpl_{idx}", None)
                                st.rerun()

                # ══════════════════════════════════════════════════════════════
                # AUTO SEND MODE
                # ══════════════════════════════════════════════════════════════
                else:
                    total = len(df_send)
                    current_file = st.session_state.get("last_file", "")

                    if not st.session_state.get("auto_running", False):
                        # Fix 5: Check for saved progress and offer to resume
                        saved_progress = st.session_state.get("csv_progress")
                        if saved_progress and saved_progress.get("filename") == current_file:
                            resume_row = saved_progress["last_sent_row"] + 1
                            if 0 < resume_row < total:
                                st.markdown(
                                    f'<div class="resume-banner">▶️ Found saved progress for '
                                    f'<b>{current_file}</b>: '
                                    f'<b>{resume_row}</b> of <b>{total}</b> rows already sent '
                                    f'(last updated: {saved_progress.get("updated_at", "")[:19]}).'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )
                                rc1, rc2 = st.columns(2)
                                with rc1:
                                    if st.button("▶️ Resume Sending", key="auto_resume_btn"):
                                        st.session_state["auto_running"] = True
                                        st.session_state["stop_sending"] = False
                                        st.session_state["campaign_id"] = new_campaign_id()
                                        st.session_state["auto_start_row"] = resume_row
                                        st.session_state["auto_sent"] = 0
                                        st.session_state["auto_failed"] = 0
                                        st.rerun()
                                with rc2:
                                    if st.button("🔄 Start Fresh", key="auto_fresh_btn"):
                                        clear_progress(current_file)
                                        st.session_state["csv_progress"] = None
                                        st.rerun()
                            else:
                                # Progress is complete — offer restart
                                st.success("✅ All rows in this file were already sent.")
                                if st.button("🔄 Send Again from Beginning", key="auto_resend_btn"):
                                    clear_progress(current_file)
                                    st.session_state["csv_progress"] = None
                                    st.rerun()
                        else:
                            if st.button("🚀 Start Sending", key="auto_start_btn"):
                                st.session_state["auto_running"] = True
                                st.session_state["stop_sending"] = False
                                st.session_state["campaign_id"] = new_campaign_id()
                                st.session_state["auto_start_row"] = 0
                                st.session_state["auto_sent"] = 0
                                st.session_state["auto_failed"] = 0
                                st.rerun()
                    else:
                        campaign_id = st.session_state["campaign_id"]
                        start_row = st.session_state.get("auto_start_row", 0)

                        if st.button("🛑 Stop", key="auto_stop_btn"):
                            st.session_state["stop_sending"] = True

                        progress_bar = st.progress(0)
                        counter_slot = st.empty()
                        status_slot = st.empty()

                        sent = st.session_state.get("auto_sent", 0)
                        failed = st.session_state.get("auto_failed", 0)

                        name_col_candidates = [c for c in df_send.columns
                                               if any(k in c.lower() for k in ["name", "first", "full"])]

                        rows_to_send = list(df_send.iloc[start_row:].iterrows())
                        total_remaining = len(rows_to_send)

                        for rel_i, (abs_i, row_series) in enumerate(rows_to_send):
                            if st.session_state.get("stop_sending", False):
                                status_slot.warning("🛑 Sending stopped by user.")
                                break

                            row = row_series.to_dict()
                            to_email = str(row.get(email_col, "")).strip()
                            to_name = (
                                str(row.get(name_col_candidates[0], ""))
                                if name_col_candidates else to_email
                            )
                            personalised_subject = personalise_subject(subject, row)

                            progress_bar.progress(
                                (rel_i + 1) / max(total_remaining, 1),
                                text=f"Processing {start_row + rel_i + 1} / {total}"
                            )
                            counter_slot.markdown(
                                f'<div class="send-counter">'
                                f'✅ Sent: <b>{sent}</b> &nbsp;|&nbsp; '
                                f'❌ Failed: <b>{failed}</b> &nbsp;|&nbsp; '
                                f'📊 Total: <b>{total}</b>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                            try:
                                tmpl_name, html_content = resolve_template_for_row(row)
                                send_email_brevo(to_email, to_name, personalised_subject, html_content)
                                log_send(campaign_id, to_email, to_name,
                                         personalised_subject, tmpl_name, "sent")
                                # Fix 5: update progress after each successful send
                                save_progress(current_file, total, int(abs_i))
                                sent += 1
                            except (EmailSendError, RuntimeError) as e:
                                log_send(campaign_id, to_email, to_name,
                                         personalised_subject, "—", "failed", str(e))
                                failed += 1

                            st.session_state["auto_sent"] = sent
                            st.session_state["auto_failed"] = failed

                        progress_bar.progress(1.0, text="Complete")
                        counter_slot.markdown(
                            f'<div class="send-counter">'
                            f'✅ Sent: <b>{sent}</b> &nbsp;|&nbsp; '
                            f'❌ Failed: <b>{failed}</b> &nbsp;|&nbsp; '
                            f'📊 Total: <b>{total}</b>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                        if not st.session_state.get("stop_sending", False):
                            st.success("✅ All emails processed! Check history for details.")
                            # Clear progress when fully done
                            clear_progress(current_file)
                            st.session_state["csv_progress"] = None

                        stats = get_campaign_stats(campaign_id)
                        col1, col2, col3 = st.columns(3)
                        col1.metric("✅ Sent", stats.get("sent", 0))
                        col2.metric("❌ Failed", stats.get("failed", 0))
                        col3.metric("⏭️ Skipped", stats.get("skipped", 0))

                        if st.button("🔄 Send Another Campaign", key="auto_restart"):
                            st.session_state["auto_running"] = False
                            st.session_state["stop_sending"] = False
                            st.session_state["auto_sent"] = 0
                            st.session_state["auto_failed"] = 0
                            st.session_state["auto_start_row"] = 0
                            st.rerun()
