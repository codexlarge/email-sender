"""
modules/csv_handler.py
CSV loading, email column detection, data validation, and metadata display.
"""
import re
import pandas as pd
import streamlit as st


# ─── Email column detection ────────────────────────────────────────────────────

def detect_email_columns(df: pd.DataFrame) -> list[str]:
    """Return all column names that contain the word 'email' (case-insensitive)."""
    return [c for c in df.columns if "email" in c.lower()]


def render_email_column_selector(df: pd.DataFrame) -> str | None:
    """
    Detect email columns, ask user to choose if multiple exist.
    Returns the chosen column name or None if none found.
    """
    email_cols = detect_email_columns(df)
    if len(email_cols) == 0:
        st.error("❌ No email column found in the CSV. Please upload a file with an email column.")
        return None
    elif len(email_cols) == 1:
        st.info(f"📧 Using email column: **`{email_cols[0]}`**")
        return email_cols[0]
    else:
        chosen = st.selectbox(
            "Multiple email columns detected. Select the one to use:",
            options=email_cols,
            key="email_col_selector",
        )
        return chosen


# ─── Data validation & cleaning ───────────────────────────────────────────────

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_and_clean(df: pd.DataFrame, email_col: str) -> pd.DataFrame:
    """
    Run all validation checks, remove bad rows, display a report, and
    return the cleaned DataFrame.
    """
    report = {}
    original_len = len(df)

    # 1. Duplicate rows
    dup_rows = df.duplicated().sum()
    df = df.drop_duplicates()
    report["Duplicate rows"] = {"found": dup_rows, "removed": dup_rows}

    # 2. Duplicate columns
    dup_cols_found = df.columns[df.columns.duplicated()].tolist()
    df = df.loc[:, ~df.columns.duplicated()]
    report["Duplicate columns"] = {
        "found": len(dup_cols_found),
        "removed": len(dup_cols_found),
    }

    # 3. Null / empty emails
    null_mask = df[email_col].isna() | (df[email_col].astype(str).str.strip() == "")
    null_count = null_mask.sum()
    df = df[~null_mask].copy()
    report["Null emails"] = {"found": null_count, "removed": null_count}

    # 4. Duplicate emails (case-insensitive)
    df["__email_lower__"] = df[email_col].str.lower().str.strip()
    dup_email_count = df.duplicated(subset="__email_lower__").sum()
    df = df.drop_duplicates(subset="__email_lower__")
    df.drop(columns=["__email_lower__"], inplace=True)
    report["Duplicate emails"] = {"found": dup_email_count, "removed": dup_email_count}

    # 5. Invalid email format
    invalid_mask = ~df[email_col].astype(str).apply(
        lambda x: bool(_EMAIL_REGEX.match(x.strip()))
    )
    invalid_count = invalid_mask.sum()
    df = df[~invalid_mask].copy()
    report["Invalid emails"] = {"found": invalid_count, "removed": invalid_count}

    df = df.reset_index(drop=True)

    # ── Display report ─────────────────────────────────────────────────────────
    with st.expander("🔍 Validation Report", expanded=True):
        rows = []
        for check, data in report.items():
            rows.append(
                {"Check": check, "Found": data["found"], "Removed": data["removed"]}
            )
        report_df = pd.DataFrame(rows)
        st.dataframe(report_df, use_container_width=True, hide_index=True)

        if dup_cols_found:
            st.warning(f"Duplicate columns removed: `{'`, `'.join(dup_cols_found)}`")

        st.success(
            f"✅ Data cleaned. Ready to use **{len(df)}** rows "
            f"(removed {original_len - len(df)} total)."
        )

    return df


# ─── Metadata display ─────────────────────────────────────────────────────────

def render_metadata(df: pd.DataFrame) -> None:
    """Show column count, row count, dtypes, and value counts in an expander."""
    with st.expander("📊 Dataset Metadata", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Rows", len(df))
        with col2:
            st.metric("Total Columns", len(df.columns))

        st.markdown("#### 🏷️ Columns")
        badge_html = " ".join(
            f'<span style="display:inline-block;background:#4F46E5;color:#fff;'
            f'border-radius:12px;padding:2px 10px;margin:3px;font-size:13px;">{c}</span>'
            for c in df.columns
        )
        st.markdown(badge_html, unsafe_allow_html=True)

        st.markdown("#### 🗂️ Data Types")
        dtype_df = pd.DataFrame(
            {"Column Name": df.columns, "Data Type": [str(dt) for dt in df.dtypes]}
        )
        st.dataframe(dtype_df, use_container_width=True, hide_index=True)

        st.markdown("#### 📈 Value Counts (top 10 per column)")
        for col in df.columns:
            vc = df[col].value_counts()
            total_unique = len(vc)
            vc_top = vc.head(10).reset_index()
            vc_top.columns = ["Value", "Count"]
            with st.expander(f"`{col}` — {total_unique} unique values"):
                st.dataframe(vc_top, use_container_width=True, hide_index=True)
                if total_unique > 10:
                    st.caption(f"... and {total_unique - 10} more unique values.")
