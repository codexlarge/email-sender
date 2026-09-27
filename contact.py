"""
contact.py
----------
Converts a business-data source CSV into a standard contact CSV with columns:
    First Name | Last Name | Mobile Phone | E-mail Address

Source CSV expected headers (tab or comma separated):
    Business Name, Contact No, Email, Service Type, Website, Maps URL,
    Owner Name, Address, Rating, Reviews, City, State, Timestamp

Usage:
    python contact.py <path_to_source_file>

Output:
    contacts_output.csv  (written in the same directory as the source file)
"""

import sys
import os
import csv
import re
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_phone(raw: str) -> str:
    """
    Normalize a phone number to the format: +91 XXXXXXXXXX
    Strips spaces, dashes, dots, parentheses; keeps leading '+'.
    Returns empty string if no digits found.
    """
    if not raw:
        return ""

    raw = raw.strip()
    # Remove common separators except leading '+'
    digits_only = re.sub(r"[^\d+]", "", raw)

    if not digits_only or not any(c.isdigit() for c in digits_only):
        return ""

    # Preserve the original spacing style but strip separators:
    # Strategy: if '+' is present, find where the country code ends by looking
    # at the original string for the first separator after '+'.
    # E.g. "+91 9876543210", "+91-98765" → "+91 <digits>"
    cc_match = re.match(r"^(\+\d+)([\s\-.()])(.+)$", raw)
    if cc_match:
        cc = cc_match.group(1)                          # e.g. "+91"
        rest = re.sub(r"[^\d]", "", cc_match.group(3)) # subscriber digits
        return f"{cc} {rest}" if rest else cc

    # No separator after country code (e.g. "+919876543210") – try known lengths
    cc_nosep = re.match(r"^(\+\d{1,3})(\d{7,10})$", raw.replace(" ", ""))
    if cc_nosep:
        return f"{cc_nosep.group(1)} {cc_nosep.group(2)}"

    # No country code – prefix '+' if it looks like a valid mobile number
    if re.match(r"^\d{10,13}$", digits_only):
        return f"+{digits_only}"
    return digits_only


def clean_email(raw: str) -> str:
    """Basic email sanitisation. Returns empty string if invalid."""
    if not raw:
        return ""
    raw = raw.strip().lower()
    # Simple RFC-ish check
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", raw):
        return raw
    return ""


def split_name(full_name: str) -> tuple[str, str]:
    """
    Split a full name into (first_name, last_name).
    - Single token  → first=token, last=""
    - Multi-token   → first=first token, last=remaining tokens joined
    """
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def normalise_row(row: dict) -> dict:
    """Strip whitespace from all values in a row dict."""
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


def detect_delimiter(file_path: Path) -> str:
    """Sniff the delimiter of the CSV/TSV file."""
    with open(file_path, encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(4096)
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample, delimiters=",\t|;")
        return dialect.delimiter
    except csv.Error:
        # Fallback: count tabs vs commas
        return "\t" if sample.count("\t") >= sample.count(",") else ","


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

SOURCE_COL_MAP = {
    # canonical key  : possible column names in the source (case-insensitive)
    "business_name": ["business name", "businessname", "company", "company name"],
    "contact_no":    ["contact no", "contact number", "phone", "mobile", "mobile no",
                      "mobile number", "phone number"],
    "email":         ["email", "e-mail", "email address", "e-mail address"],
    "owner_name":    ["owner name", "owner", "contact person", "person name"],
}


def find_column(headers: list[str], candidates: list[str]) -> str | None:
    """Return the actual header string that matches any candidate (case-insensitive)."""
    headers_lower = {h.strip().lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in headers_lower:
            return headers_lower[candidate.lower()]
    return None


def resolve_columns(headers: list[str]) -> dict[str, str | None]:
    """Map canonical keys to actual column names found in the file."""
    return {key: find_column(headers, candidates)
            for key, candidates in SOURCE_COL_MAP.items()}


def convert(source_path: str) -> None:
    source = Path(source_path).resolve()

    if not source.exists():
        log.error("File not found: %s", source)
        sys.exit(1)

    if not source.is_file():
        log.error("Path is not a file: %s", source)
        sys.exit(1)

    delimiter = detect_delimiter(source)
    log.info("Detected delimiter: %r", delimiter)

    # output_path = source.parent / "contacts_output.csv"
    output_path = os.path.join(source.parent,'contact')
    if not os.path.exists(output_path):
        os.mkdir(output_path)
    output_path = os.path.join(output_path,'contact_output.csv')
    

    # -----------------------------------------------------------------------
    # Read source
    # -----------------------------------------------------------------------
    try:
        with open(source, encoding="utf-8-sig", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            if reader.fieldnames is None:
                log.error("Source file has no headers.")
                sys.exit(1)

            headers = list(reader.fieldnames)
            col = resolve_columns(headers)

            log.info("Column mapping: %s", col)

            missing = [k for k, v in col.items()
                       if k in ("contact_no", "email") and v is None]
            if missing:
                log.warning("Columns not found in source (will be empty): %s", missing)

            rows = [normalise_row(dict(r)) for r in reader]
    except Exception as exc:
        log.error("Failed to read source file: %s", exc)
        sys.exit(1)

    log.info("Total rows read: %d", len(rows))

    # -----------------------------------------------------------------------
    # Transform rows
    # -----------------------------------------------------------------------
    output_rows: list[dict] = []
    seen: set[tuple] = set()          # for duplicate detection
    skipped_no_identity = 0
    skipped_duplicate = 0

    for idx, row in enumerate(rows, start=2):  # start=2 → header is row 1

        # --- Name resolution ------------------------------------------------
        owner_raw = (row.get(col["owner_name"]) or "") if col["owner_name"] else ""
        business_raw = (row.get(col["business_name"]) or "") if col["business_name"] else ""

        name_source = owner_raw if owner_raw else business_raw

        if not name_source:
            log.warning("Row %d: No name (owner or business) – skipping.", idx)
            skipped_no_identity += 1
            continue

        first_name, last_name = split_name(name_source)

        # --- Contact fields -------------------------------------------------
        phone_raw  = (row.get(col["contact_no"]) or "") if col["contact_no"] else ""
        email_raw  = (row.get(col["email"])      or "") if col["email"]      else ""

        phone = clean_phone(phone_raw)
        email = clean_email(email_raw)

        # Skip rows without a phone number
        if not phone:
            log.warning(
                "Row %d (%s): No valid phone number – skipping.", idx, name_source
            )
            continue

        # --- Duplicate detection --------------------------------------------
        dedup_key = (first_name.lower(), last_name.lower(), phone, email)
        if dedup_key in seen:
            log.warning(
                "Row %d (%s): Duplicate contact – skipping.", idx, name_source
            )
            skipped_duplicate += 1
            continue
        seen.add(dedup_key)

        output_rows.append({
            "First Name":     first_name,
            "Last Name":      last_name,
            "Mobile Phone":   phone,
            "E-mail Address": email,
        })

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------
    output_fields = ["First Name", "Last Name", "Mobile Phone", "E-mail Address"]

    try:
        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=output_fields)
            writer.writeheader()
            writer.writerows(output_rows)
    except Exception as exc:
        log.error("Failed to write output file: %s", exc)
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    log.info("─" * 50)
    log.info("Done!")
    log.info("  Total rows processed : %d", len(rows))
    log.info("  Contacts written     : %d", len(output_rows))
    log.info("  Skipped (no name)    : %d", skipped_no_identity)
    log.info("  Skipped (duplicate)  : %d", skipped_duplicate)
    log.info("  Output file          : %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    source_path = input("Enter source CSV file path: ").strip().strip('"').strip("'")
    if not source_path:
        log.error("No path entered. Exiting.")
        sys.exit(1)
    convert(source_path)
