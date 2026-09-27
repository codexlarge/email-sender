"""
modules/condition_engine.py
Condition builder UI and evaluator for template routing.
"""
import pandas as pd
import streamlit as st

from modules.template_manager import list_templates


# ─── Operator sets by column type ─────────────────────────────────────────────

TEXT_OPS = ["==", "!=", "starts with", "ends with", "contains", "is empty", "is not empty"]
NUM_OPS  = ["==", "!=", ">", ">=", "<", "<=", "is empty", "is not empty"]


def _infer_type(series: pd.Series) -> str:
    """Return 'numeric' or 'text' based on series dtype."""
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    return "text"


# ─── Condition Builder UI ──────────────────────────────────────────────────────

def render_condition_builder(df: pd.DataFrame) -> tuple[list[dict], str | None]:
    """
    Render the condition builder UI.
    Returns (rules, default_template).
    rules is a list of dicts with keys: column, operator, value, template.
    """
    st.markdown("### 🔀 Condition Rules *(Optional)*")
    st.info(
        "Available variables: "
        + ", ".join(f"`{c}`" for c in df.columns)
    )

    templates = list_templates()
    if not templates:
        st.warning("No templates available. Please create templates first.")
        return [], None

    # Initialise rules list in session state
    if "condition_rules" not in st.session_state:
        st.session_state["condition_rules"] = []

    col_add, col_clear = st.columns([1, 1])
    with col_add:
        if st.button("➕ Add Condition Rule", key="add_rule_btn"):
            st.session_state["condition_rules"].append(
                {"column": df.columns[0], "operator": "==", "value": "", "template": templates[0]}
            )
    with col_clear:
        if st.button("🗑️ Clear All Rules", key="clear_rules_btn"):
            st.session_state["condition_rules"] = []

    rules_to_delete = []
    rules = st.session_state["condition_rules"]

    if rules:
        with st.container(height=380, border=True):
            for i, rule in enumerate(rules):
                with st.container():
                    st.markdown(
                        f'<div style="background:#1A1A2E;border:1px solid #4F46E5;'
                        f'border-radius:10px;padding:14px;margin-bottom:10px;">'
                        f'<b style="color:#A5B4FC;">Rule {i + 1}</b></div>',
                        unsafe_allow_html=True,
                    )
                    r1, r2, r3, r4, r5 = st.columns([2, 2, 2, 2, 1])

                    with r1:
                        col_name = st.selectbox(
                            "Column", df.columns.tolist(), key=f"rule_col_{i}",
                            index=df.columns.tolist().index(rule["column"])
                            if rule["column"] in df.columns else 0,
                        )
                        rules[i]["column"] = col_name

                    col_type = _infer_type(df[col_name])
                    op_list = NUM_OPS if col_type == "numeric" else TEXT_OPS

                    with r2:
                        op_idx = op_list.index(rule["operator"]) if rule["operator"] in op_list else 0
                        operator = st.selectbox("Operator", op_list, index=op_idx, key=f"rule_op_{i}")
                        rules[i]["operator"] = operator

                    with r3:
                        if operator not in ("is empty", "is not empty"):
                            top_vals = df[col_name].dropna().astype(str).value_counts().head(20).index.tolist()
                            value = st.selectbox(
                                "Value",
                                options=["(type custom)"] + top_vals,
                                key=f"rule_val_select_{i}",
                            )
                            if value == "(type custom)":
                                value = st.text_input("Custom value", key=f"rule_val_custom_{i}",
                                                      value=rule.get("value", ""))
                            rules[i]["value"] = value
                        else:
                            rules[i]["value"] = ""
                            st.write("")  # spacer

                    with r4:
                        tmpl_idx = templates.index(rule["template"]) if rule["template"] in templates else 0
                        tmpl = st.selectbox("Use template", templates, index=tmpl_idx, key=f"rule_tmpl_{i}")
                        rules[i]["template"] = tmpl

                    with r5:
                        st.write("")
                        if st.button("🗑️", key=f"rule_del_{i}"):
                            rules_to_delete.append(i)

    for idx in reversed(rules_to_delete):
        rules.pop(idx)
    st.session_state["condition_rules"] = rules

    # Default template
    default_template = None
    if rules:
        st.markdown("#### 🔁 Default Template *(when no rule matches)*")
        default_template = st.selectbox(
            "If no conditions match, use template:",
            templates,
            key="default_template_selector",
        )

    return rules, default_template


# ─── Condition Evaluator ───────────────────────────────────────────────────────

def evaluate_conditions(
    row: pd.Series,
    rules: list[dict],
    default_template: str,
) -> str:
    """
    Evaluate rules top-to-bottom. Return the template name of the first
    matching rule, or default_template if none match.
    """
    for rule in rules:
        col = rule["column"]
        op = rule["operator"]
        val = rule.get("value", "")

        if col not in row.index:
            continue

        cell = row[col]

        try:
            if op == "is empty":
                match = pd.isna(cell) or str(cell).strip() == ""
            elif op == "is not empty":
                match = not (pd.isna(cell) or str(cell).strip() == "")
            elif op == "==":
                try:
                    match = float(str(cell).replace(",", "")) == float(val)
                except (ValueError, TypeError):
                    match = str(cell).strip().lower() == val.strip().lower()
            elif op == "!=":
                try:
                    match = float(str(cell).replace(",", "")) != float(val)
                except (ValueError, TypeError):
                    match = str(cell).strip().lower() != val.strip().lower()
            elif op == ">":
                match = float(str(cell).replace(",", "")) > float(val)
            elif op == ">=":
                match = float(str(cell).replace(",", "")) >= float(val)
            elif op == "<":
                match = float(str(cell).replace(",", "")) < float(val)
            elif op == "<=":
                match = float(str(cell).replace(",", "")) <= float(val)
            elif op == "starts with":
                match = str(cell).lower().startswith(val.lower())
            elif op == "ends with":
                match = str(cell).lower().endswith(val.lower())
            elif op == "contains":
                match = val.lower() in str(cell).lower()
            else:
                match = False
        except Exception:
            match = False

        if match:
            return rule["template"]

    return default_template
