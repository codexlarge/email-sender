"""
modules/ai_generator.py
LangChain-powered AI email template generation.
Supports Groq (default), Google Gemini, and HuggingFace.
"""
import os
import json
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator
from langchain_core.messages import SystemMessage, HumanMessage

from modules.template_manager import save_template, list_templates

load_dotenv()


# ─── Pydantic validator ────────────────────────────────────────────────────────

class AIEmailOutput(BaseModel):
    html_content: str

    @field_validator("html_content")
    @classmethod
    def must_be_valid_html(cls, v: str) -> str:
        v = v.strip()
        # Strip markdown code fences if the model wrapped it
        if v.startswith("```"):
            lines = v.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            v = "\n".join(lines).strip()
        lower = v.lower()
        has_html_tag = any(tag in lower for tag in ["<html", "<body", "<table", "<p", "<div"])
        if not has_html_tag:
            raise ValueError("Response does not appear to be valid HTML.")
        if len(v) < 50:
            raise ValueError("HTML content is too short to be a valid email.")
        return v


# ─── LLM Factory ──────────────────────────────────────────────────────────────

def get_llm():
    """
    Returns the correct LangChain chat model based on AI_PROVIDER in .env.
    Priority: groq → google → huggingface
    """
    provider = os.getenv("AI_PROVIDER", "groq").lower().strip()

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY is not set in .env. "
                "Get a free key at https://console.groq.com"
            )
        from langchain_groq import ChatGroq
        return ChatGroq(
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", "llama3-70b-8192"),
            temperature=0.7,
        )

    elif provider == "google":
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY is not set in .env. "
                "Get a key at https://aistudio.google.com"
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            google_api_key=api_key,
            model=os.getenv("GOOGLE_MODEL", "gemini-1.5-flash"),
            temperature=0.7,
        )

    elif provider == "huggingface":
        api_token = os.getenv("HUGGINGFACE_API_TOKEN", "")
        if not api_token:
            raise ValueError(
                "HUGGINGFACE_API_TOKEN is not set in .env. "
                "Get a token at https://huggingface.co/settings/tokens"
            )
        from langchain_huggingface import HuggingFaceEndpoint
        return HuggingFaceEndpoint(
            repo_id=os.getenv("HUGGINGFACE_MODEL", "mistralai/Mistral-7B-Instruct-v0.3"),
            huggingfacehub_api_token=api_token,
            temperature=0.7,
            max_new_tokens=2048,
        )

    else:
        raise ValueError(
            f"Unknown AI_PROVIDER '{provider}'. "
            "Must be 'groq', 'google', or 'huggingface'."
        )


def get_provider_badge() -> str:
    """Return sidebar badge info for the active provider."""
    provider = os.getenv("AI_PROVIDER", "groq").lower().strip()
    if provider == "groq":
        model = os.getenv("GROQ_MODEL", "llama3-70b-8192")
        return f"🟢 **Groq** — `{model}`"
    elif provider == "google":
        model = os.getenv("GOOGLE_MODEL", "gemini-1.5-flash")
        return f"🔵 **Google Gemini** — `{model}`"
    elif provider == "huggingface":
        model = os.getenv("HUGGINGFACE_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
        return f"🟠 **HuggingFace** — `{model}`"
    return f"❓ Unknown provider: `{provider}`"


# ─── Core generation function ──────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert email copywriter. Generate a complete, professional HTML email based on the following information.
Style guide: {style_description}

CRITICAL FORMATTING RULES — YOU MUST FOLLOW ALL OF THESE:
1. Use ONLY inline CSS (style="..." attributes directly on HTML elements).
2. Do NOT use <style> blocks, CSS classes, or external stylesheets.
3. Email clients (Gmail, Outlook) strip all <style> tags — inline only.
4. Use table-based layouts for maximum email client compatibility.
5. Output ONLY the raw HTML. No markdown, no code fences, no explanations.
6. The HTML must start with <!DOCTYPE html> and be a complete valid document.
"""

_HUMAN_PROMPT_TEMPLATE = """\
Recipient data:
{row_json}

Campaign description: {campaign_description}
Sender/Brand: {brand_name}

Generate a personalised HTML email for this specific recipient.
Remember: inline CSS only. Table-based layout. Complete HTML document.
"""


def generate_ai_email(
    row: dict,
    campaign_description: str,
    brand_name: str,
    style_description: str = "professional, modern, clean",
    max_retries: int = 3,
) -> str:
    """
    Generate a personalised HTML email for a single recipient using LangChain.
    Validates with Pydantic. Retries up to max_retries times.
    Returns validated html_content string.
    Raises RuntimeError if all attempts fail.
    """
    llm = get_llm()

    system_msg = SystemMessage(
        content=_SYSTEM_PROMPT_TEMPLATE.format(style_description=style_description)
    )
    human_msg = HumanMessage(
        content=_HUMAN_PROMPT_TEMPLATE.format(
            row_json=json.dumps(row, ensure_ascii=False, default=str),
            campaign_description=campaign_description,
            brand_name=brand_name,
        )
    )

    last_error = None
    for attempt in range(max_retries):
        try:
            response = llm.invoke([system_msg, human_msg])
            raw = response.content if hasattr(response, "content") else str(response)
            validated = AIEmailOutput(html_content=raw)
            return validated.html_content
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        f"AI generation failed after {max_retries} attempts. Last error: {last_error}"
    )


# ─── AI Template Tab UI ───────────────────────────────────────────────────────

def render_ai_template_tab() -> None:
    """Render the AI template generation UI tab."""
    st.markdown("### 🤖 Generate Email Template with AI")

    # Show active provider info
    st.info(f"Active AI Provider: {get_provider_badge()}")

    # Check provider is configured
    try:
        _ = get_llm()
        provider_ok = True
    except ValueError as e:
        st.error(f"⚠️ AI Provider not configured: {e}")
        provider_ok = False

    if not provider_ok:
        st.stop()

    campaign_desc = st.text_area(
        "📝 Describe your email campaign:",
        height=120,
        placeholder=(
            "e.g. A promotional email for a 20% discount on our SaaS product. "
            "Professional tone, indigo color scheme, include a CTA button."
        ),
        key="ai_campaign_desc",
    )

    col1, col2 = st.columns(2)
    with col1:
        brand_name = st.text_input(
            "🏷️ Sender / Brand Name:",
            placeholder="e.g. Acme Corp",
            key="ai_brand_name",
        )
    with col2:
        style_desc = st.text_input(
            "🎨 Style description:",
            value="professional, modern, clean, indigo color scheme",
            key="ai_style_desc",
        )

    if st.button("✨ Generate Template with AI", key="ai_generate_btn"):
        if not campaign_desc.strip():
            st.error("Please enter a campaign description.")
        elif not brand_name.strip():
            st.error("Please enter a sender/brand name.")
        else:
            with st.spinner("🤖 Generating your email template…"):
                try:
                    html_out = generate_ai_email(
                        row={"first_name": "John", "email": "john@example.com"},
                        campaign_description=campaign_desc,
                        brand_name=brand_name,
                        style_description=style_desc,
                    )
                    st.session_state["ai_generated_html"] = html_out
                    st.success("✅ Template generated!")
                except RuntimeError as e:
                    st.error(f"❌ Generation failed: {e}")

    if st.session_state.get("ai_generated_html"):
        html_out = st.session_state["ai_generated_html"]

        tab_code, tab_preview = st.tabs(["📄 HTML Code", "👁️ Preview"])
        with tab_code:
            st.code(html_out, language="html")
        with tab_preview:
            with st.container(height=520, border=True):
                components.html(html_out, height=450, scrolling=True)

        st.divider()
        st.markdown("#### 💾 Save this AI Template")
        save_col1, save_col2 = st.columns([2, 1])
        with save_col1:
            ai_save_name = st.text_input(
                "Template name to save as:",
                placeholder="e.g. ai_promo_summer",
                key="ai_save_name",
            )
        with save_col2:
            st.write("")
            if st.button("💾 Save Template", key="ai_save_btn"):
                if not ai_save_name.strip():
                    st.error("Please enter a template name.")
                else:
                    filename = save_template(ai_save_name.strip(), html_out)
                    st.success(f"✅ Saved as `{filename}`")
                    st.session_state["ai_generated_html"] = None
                    st.rerun()
