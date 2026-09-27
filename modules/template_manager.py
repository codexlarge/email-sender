"""
modules/template_manager.py
Template CRUD: list, create, preview, and select HTML email templates.
"""
import os
import re
import streamlit as st
import streamlit.components.v1 as components
from modules.email_sender import personalise_template

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def ensure_templates_dir() -> None:
    os.makedirs(TEMPLATES_DIR, exist_ok=True)


def list_templates() -> list[str]:
    """Return list of .html template filenames (without path)."""
    ensure_templates_dir()
    return sorted(
        f for f in os.listdir(TEMPLATES_DIR) if f.endswith(".html")
    )


def read_template(filename: str) -> str:
    """Read and return the content of a template file."""
    path = os.path.join(TEMPLATES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_template(name: str, html_content: str) -> str:
    """
    Save an HTML template to the templates directory.
    Returns the saved filename.
    """
    ensure_templates_dir()
    filename = name.strip() + ".html"
    path = os.path.join(TEMPLATES_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filename


def _valid_template_name(name: str) -> bool:
    """Only allow alphanumeric, dash, underscore characters."""
    return bool(re.match(r"^[a-zA-Z0-9_\-]+$", name.strip()))


# ─── Manual template tab ──────────────────────────────────────────────────────

def render_manual_template_tab(sample_row: dict = None) -> None:
    """Render the full manual template management UI.

    Args:
        sample_row: Optional dict of column -> value used to personalise
                    template previews. When None, raw placeholders are shown.
    """
    st.markdown("### 📂 Available Templates")
    templates = list_templates()

    if not templates:
        st.info("No templates yet. Create one below.")
    else:
        for tmpl in templates:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(
                    f'<span style="background:#1A1A2E;padding:6px 14px;border-radius:8px;'
                    f'border:1px solid #4F46E5;color:#E2E8F0;font-size:14px;">📄 {tmpl}</span>',
                    unsafe_allow_html=True,
                )
            with col2:
                if st.button("👁️ Preview", key=f"prev_{tmpl}"):
                    st.session_state[f"preview_open_{tmpl}"] = not st.session_state.get(
                        f"preview_open_{tmpl}", False
                    )

            if st.session_state.get(f"preview_open_{tmpl}", False):
                html_content = read_template(tmpl)
                preview_html = (
                    personalise_template(html_content, sample_row)
                    if sample_row else html_content
                )
                with st.expander(f"Preview: {tmpl}", expanded=True):
                    with st.container(height=420, border=True):
                        components.html(preview_html, height=360, scrolling=True)

    st.divider()
    st.markdown("### ✏️ Create New Template")

    with st.form("new_template_form", clear_on_submit=False):
        tmpl_name = st.text_input(
            "Template Name (no spaces, no special characters)",
            placeholder="e.g. promo_summer",
        )
        html_input = st.text_area(
            "HTML Content",
            height=300,
            placeholder="Paste your full HTML email here. Use {{column_name}} for personalisation.",
        )
        submitted = st.form_submit_button("💾 Save Template")

        if submitted:
            if not tmpl_name.strip():
                st.error("Template name cannot be empty.")
            elif not _valid_template_name(tmpl_name):
                st.error(
                    "Template name can only contain letters, numbers, hyphens, and underscores."
                )
            elif not html_input.strip():
                st.error("HTML content cannot be empty.")
            else:
                filename = save_template(tmpl_name, html_input)
                st.success(f"✅ Template saved as `{filename}`")
                st.rerun()

    if html_input if "html_input" not in dir() else False:
        pass  # placeholder guard — no-op


def render_template_selector(sample_row: dict = None) -> list:
    """
    Show a multiselect for choosing one or more templates.
    Returns the list of selected template filenames.

    Args:
        sample_row: Optional dict of column -> value used to personalise
                    template previews. When None, raw placeholders are shown.
    """
    templates = list_templates()
    if not templates:
        st.warning("⚠️ No templates available. Please create one first.")
        return []

    selected = st.multiselect(
        "Select one or more templates to use for sending:",
        options=templates,
        default=st.session_state.get("selected_templates", []),
        key="template_multiselect",
    )
    st.session_state["selected_templates"] = selected

    if selected:
        st.markdown("#### 👁️ Selected Template Previews")
        if sample_row:
            st.caption("🔍 Preview shows values from the first data row.")
        for tmpl in selected:
            with st.expander(f"Preview: {tmpl}"):
                html_content = read_template(tmpl)
                preview_html = (
                    personalise_template(html_content, sample_row)
                    if sample_row else html_content
                )
                with st.container(height=420, border=True):
                    components.html(preview_html, height=360, scrolling=True)

    return selected
