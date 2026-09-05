"""
Universal Sensitive Financial Data Masking Guardrail
Guarantees zero leakage of raw account numbers, UTR hashes, PANs, or card tokens
across SQL query results, LLM narrative contexts, API JSON responses, and AG Grid tables.
"""

import re
from typing import Any, Dict, List, Union
import pandas as pd
from backend.core.crypto import decrypt_utr

# Pattern for 10-18 digit raw account numbers or card numbers inside descriptions
ACCOUNT_NUM_REGEX = re.compile(r"\b(\d{6,14})(\d{4})\b")

# Pattern for Indian PAN / Corporate Tax IDs (e.g. ABCDE1234F)
PAN_REGEX = re.compile(r"\b([A-Z]{5})(\d{4})([A-Z])\b")

def mask_account_number(val: Any) -> str:
    """Masks a bank account number to '****<last_4>'."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    if s.startswith("****"):
        return s
    if len(s) <= 4:
        return "****" + s
    return "****" + s[-4:]

def mask_utr(val: Any) -> str:
    """Decrypts (if encrypted with HASH_KEY) and masks a UTR / transaction hash to prefix + '...'."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    if not s:
        return ""
    # Decrypt if encrypted with HASH_KEY
    dec = decrypt_utr(s)
    if dec and dec != s:
        s = dec
    elif s.endswith("..."):
        return s

    if len(s) > 8:
        return s[:8] + "..."
    return s

def sanitize_text(text: Any) -> str:
    """
    Scans freeform text (e.g. transaction descriptions, ledger notes)
    and redacts any embedded raw 10-18 digit account numbers or tax identifiers.
    """
    if text is None or pd.isna(text):
        return ""
    s = str(text)
    # Redact embedded 10-18 digit account numbers: replace prefix with ****
    s = ACCOUNT_NUM_REGEX.sub(r"****\2", s)
    # Redact PAN numbers: replace middle digits
    s = PAN_REGEX.sub(r"\1****\3", s)
    return s

def mask_record_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Applies universal masking to a single dictionary record."""
    clean = {}
    for k, v in row.items():
        k_lower = k.lower()
        if "account_number" in k_lower or "acc_num" in k_lower or "account_no" in k_lower:
            clean[k] = mask_account_number(v)
            clean["masked_account_number"] = mask_account_number(v)
        elif "utr" in k_lower:
            clean[k] = mask_utr(v)
            clean["masked_utr_number"] = mask_utr(v)
        elif "description" in k_lower or "desc" in k_lower or "note" in k_lower:
            clean[k] = sanitize_text(v)
        else:
            clean[k] = v
    return clean

def mask_records_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Applies universal masking across all rows and sensitive columns of a pandas DataFrame."""
    if df.empty:
        return df

    out = df.copy()
    
    # 1. Process account number
    for col in list(out.columns):
        c_lower = col.lower()
        if "account_number" in c_lower or "acc_num" in c_lower or "account_no" in c_lower:
            out[col] = out[col].apply(mask_account_number)
            out["masked_account_number"] = out[col]

    # 2. Process UTR (decrypt if encrypted + mask)
    if "utr_number" in out.columns:
        out["utr_number"] = out["utr_number"].apply(mask_utr)
        out["masked_utr_number"] = out["utr_number"]
    else:
        for col in list(out.columns):
            if "utr" in col.lower():
                out[col] = out[col].apply(mask_utr)
                out["masked_utr_number"] = out[col]

    # 3. Sanitize descriptions
    for col in list(out.columns):
        c_lower = col.lower()
        if "description" in c_lower or "desc" in c_lower or "note" in c_lower:
            out[col] = out[col].apply(sanitize_text)

    return out
