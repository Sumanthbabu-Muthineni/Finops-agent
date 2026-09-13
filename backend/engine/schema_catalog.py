"""
TBX FinOps Assistant - Dynamic Schema & Column Knowledge Catalog
Provides dynamic schema awareness, zero-hardcoded column glossary,
fuzzy typo detection ("Did you mean..."), and semantic explanations
for all database tables and columns. Supports multi-tenant BYODB.
"""

from typing import Dict, Any, List, Optional, Tuple, Set
import re
from rapidfuzz import fuzz
from backend.engine.db import db

# Universal FinOps & Banking Column Glossary (Semantic standard references)
STANDARD_FINOPS_GLOSSARY: Dict[str, str] = {
    "utr_number": "Unique Transaction Reference (UTR) number—a unique tracking identifier assigned by banking payment networks (such as NEFT, RTGS, and IMPS in India) to validate and reconcile financial fund transfers between accounts.",
    "masked_utr_number": "Cryptographically masked or tokenized Unique Transaction Reference (UTR) ensuring audit compliance and PII protection while maintaining traceability.",
    "transaction_reference_id": "Bank or payment gateway reference identifier (e.g., REF...) generated during payment processing for reconciliation against bank statements.",
    "reference_id": "Alias for the transaction reference identifier used in accounting ledgers.",
    "transaction_id": "Unique primary key identifying an individual transaction ledger record.",
    "account_id": "Unique primary key identifying a corporate bank account across banking partners.",
    "account_number": "Bank account number associated with the corporate entity, displayed with masking (e.g. ****9012) for privacy.",
    "masked_account_number": "Masked representation of the bank account number displaying only the last 4 digits for security and compliance.",
    "available_balance": "Current cleared ledger balance in the bank account available for immediate operational disbursements and vendor settlements.",
    "balance": "Alias for the available ledger balance.",
    "bank_code": "Standard short identifier or IFSC prefix for the banking institution (e.g. HDFC, SBIN, ICIC, UTIB, CNRB).",
    "bank_name": "Full legal commercial name of the partner banking institution (e.g. STATE BANK OF INDIA, HDFC BANK LIMITED).",
    "transaction_date": "Timestamp indicating exactly when the financial transaction was posted to the bank ledger.",
    "transaction_day": "Calendar date (YYYY-MM-DD) of the transaction, useful for daily cash flow reconciliations.",
    "txn_year": "Calendar year extracted from transaction date for annual financial summaries.",
    "txn_month": "Calendar month extracted from transaction date for monthly financial statements.",
    "transaction_type": "Flow direction of the transaction—'debit' (outgoing outflow/payout) or 'credit' (incoming inflow/receipt).",
    "transaction_amount": "Exact numerical value of the financial transaction.",
    "amount": "Alias for the monetary transaction amount.",
    "description": "Transaction narration, payment memo, counterparty detail, or settlement description (e.g. NEFT/UPI/IMPS vendor settlements).",
    "entity_id": "Corporate entity or operating subsidiary identifier responsible for the financial account.",
    "program_id": "Corporate financing or disbursement program identifier governing the account."
}

class SchemaCatalog:
    """
    Dynamic Schema Inspector & Column Knowledge Engine.
    Zero hardcoded tables or columns. Inspects live database metadata per session.
    """

    def get_all_columns(self, session_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically extracts all columns across all tables and views in the active database.
        Returns mapping of column_name -> metadata dict.
        """
        profile = db.get_schema_profile(session_id)
        columns_map: Dict[str, Dict[str, Any]] = {}

        for table_name, cols in profile.items():
            for col_name, info in cols.items():
                col_clean = col_name.lower().strip()
                if col_clean not in columns_map:
                    columns_map[col_clean] = {
                        "name": col_clean,
                        "tables": [],
                        "types": set(),
                        "sample_values": [],
                        "description": STANDARD_FINOPS_GLOSSARY.get(
                            col_clean,
                            f"{col_clean.replace('_', ' ').title()} attribute stored in database table `{table_name}`."
                        )
                    }
                columns_map[col_clean]["tables"].append(table_name)
                columns_map[col_clean]["types"].add(info.get("type", "VARCHAR"))
                samples = info.get("sample_values", [])
                for s in samples:
                    if s not in columns_map[col_clean]["sample_values"] and len(columns_map[col_clean]["sample_values"]) < 5:
                        columns_map[col_clean]["sample_values"].append(s)

        # Convert types set to list
        for c in columns_map.values():
            c["types"] = list(c["types"])

        return columns_map

    def find_column_or_typo(self, term: str, session_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str], float]:
        """
        Searches for a column in the schema catalog.
        Returns:
            (exact_canonical_column, suggested_typo_column, similarity_score)
        """
        term_clean = term.lower().strip().replace("-", "_").replace(" ", "_")
        if not term_clean or len(term_clean) < 2 or len(term_clean.split("_")) > 3 or len(term_clean) > 30:
            return None, None, 0.0

        all_cols = self.get_all_columns(session_id)

        # 1. Exact match
        if term_clean in all_cols:
            return term_clean, None, 1.0

        # 2. Common abbreviations / aliases
        alias_map = {
            "utr": "utr_number",
            "otr": "utr_number",
            "otr_number": "utr_number",
            "utr_no": "utr_number",
            "utr_num": "utr_number",
            "ref": "transaction_reference_id",
            "ref_id": "transaction_reference_id",
            "reference": "transaction_reference_id",
            "reference_num": "transaction_reference_id",
            "acc": "account_number",
            "acc_no": "account_number",
            "acc_num": "account_number",
            "account_no": "account_number",
            "acct": "account_number",
            "txn": "transaction_id",
            "txn_date": "transaction_date",
            "tx_date": "transaction_date",
            "bal": "available_balance",
            "balance": "available_balance",
            "amt": "transaction_amount",
            "amount": "transaction_amount"
        }
        if term_clean in alias_map:
            target = alias_map[term_clean]
            if target in all_cols:
                return None, target, 0.95

        # 3. Fuzzy match against all schema columns
        best_match = None
        best_score = 0.0

        for col_name in all_cols.keys():
            score = fuzz.ratio(term_clean, col_name)
            # Extra boost if substring matches closely in length
            if term_clean in col_name and len(term_clean) >= 4:
                score = max(score, 82.0)
            if score > best_score:
                best_score = score
                best_match = col_name

        if best_score >= 70.0 and best_match:
            return None, best_match, best_score / 100.0

        return None, None, 0.0

    def detect_schema_inquiry(self, query: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Detects if the user query is asking about a database schema concept, table, or column definition.
        Examples:
            - "whats utr_number??"
            - "what is utr_number"
            - "what is otr_number"
            - "explain available_balance"
            - "what does transaction_reference_id mean"
            - "what columns are in transactions table"
        """
        q_lower = query.lower().strip()

        # Immediate exclusion: calculations, spend, totals, breakdowns, or multi-bank aggregations
        financial_indicators = [
            "total", "sum", "average", "how much", "how many", "across", "spend", "spent", "spending",
            "all banks", "all accounts", "for any", "who paid", "show me", "compare", "breakdown"
        ]
        if any(w in q_lower for w in financial_indicators):
            return None

        # Check for inquiry patterns
        inquiry_patterns = [
            r"^(?:what(?:'s|s|\s+is)|\?*\s*tell\s+me\s+about|explain|meaning\s+of|what\s+does|can\s+you\s+explain)\s+(?:the\s+)?([a-z0-9_\-\s]+?)(?:\?*|\s+mean\??|\s+in\s+db\??)$",
            r"^([a-z0-9_\-]+)\s*\?*$",  # e.g. "utr_number", "utr_number??", "otr_number", "otr_number?"
            r"^(?:about\s+)?([a-z0-9_\-\s]{2,30})\s*\?+$"
        ]

        target_candidate = None
        for pat in inquiry_patterns:
            m = re.search(pat, q_lower)
            if m:
                cand = m.group(1).strip()
                # Verify cand is actually a column, alias, or typo candidate
                exact, typo, sc = self.find_column_or_typo(cand, session_id)
                if exact or (typo and sc >= 0.70):
                    target_candidate = cand
                    break

        # Also check for explicit question about tables
        if any(w in q_lower for w in ["what tables", "show tables", "list tables", "what views", "schema structure"]):
            tables = db.get_tables_and_views(session_id)
            return {
                "type": "TABLE_LIST",
                "tables": tables,
                "narrative": self.explain_tables(session_id)
            }

        if not target_candidate:
            # Check if query is 1-3 words and matches a column/typo
            clean_tokens = [w for w in re.findall(r"\b[a-z0-9_]{2,30}\b", q_lower) if w not in ["what", "whats", "tell", "explain", "about", "show", "give", "please", "help", "the", "in", "db"]]
            if len(clean_tokens) <= 2:
                joined = "_".join(clean_tokens)
                exact, typo, sc = self.find_column_or_typo(joined, session_id)
                if exact or (typo and sc >= 0.70):
                    target_candidate = joined

        if not target_candidate:
            # Check if any single token in the query is a column or column typo in a short query
            tokens = re.findall(r"\b[a-z0-9_]{3,30}\b", q_lower)
            for token in tokens:
                if token in ["what", "whats", "tell", "explain", "about", "show", "give", "please", "help", "the", "for", "any", "two", "accounts"]:
                    continue
                exact, typo, score = self.find_column_or_typo(token, session_id)
                if exact or (typo and score >= 0.75):
                    # If the query is short and asking about meaning
                    if len(tokens) <= 5 and any(w in q_lower for w in ["what", "whats", "explain", "meaning", "mean", "?"]) and not any(w in q_lower for w in ["show", "list", "two", "records", "accounts"]):
                        target_candidate = token
                        break

        if not target_candidate:
            return None

        # Clean target candidate
        target_candidate = target_candidate.replace("?", "").replace("the ", "").strip()
        exact_col, typo_col, score = self.find_column_or_typo(target_candidate, session_id)

        all_cols = self.get_all_columns(session_id)
        tables = db.get_tables_and_views(session_id)

        # Case 1: Exact column match
        if exact_col and exact_col in all_cols:
            col_info = all_cols[exact_col]
            narrative = self.explain_column(exact_col, col_info)
            return {
                "type": "COLUMN_EXPLANATION",
                "column": exact_col,
                "is_typo": False,
                "narrative": narrative,
                "clarification_options": [
                    f"Show transactions with {exact_col}",
                    f"Count records with {exact_col}",
                    f"Sample values for {exact_col}"
                ]
            }

        # Case 2: Typo match (e.g. user asked "otr_number" -> matched "utr_number")
        if typo_col and typo_col in all_cols:
            col_info = all_cols[typo_col]
            narrative = self.explain_typo_column(target_candidate, typo_col, col_info)
            return {
                "type": "COLUMN_TYPO",
                "user_term": target_candidate,
                "suggested_column": typo_col,
                "is_typo": True,
                "narrative": narrative,
                "clarification_options": [
                    f"Yes, show {typo_col} records",
                    f"What is {typo_col}?",
                    "View all schema columns"
                ]
            }

        # Case 3: Table match (e.g. user asked "what is transaction table")
        target_tbl = target_candidate.replace(" table", "").replace(" view", "").strip()
        if target_tbl in tables:
            profile = db.get_schema_profile(session_id)
            cols = list(profile.get(target_tbl, {}).keys())
            narrative = f"### Table / View: `{target_tbl}`\n\n"
            narrative += f"In our database, `{target_tbl}` is a primary relational dataset containing **{len(cols)} columns**:\n\n"
            narrative += ", ".join(f"`{c}`" for c in cols) + ".\n\n"
            narrative += "You can ask for totals, averages, or filtered breakdowns from this table."
            return {
                "type": "TABLE_EXPLANATION",
                "table": target_tbl,
                "narrative": narrative,
                "clarification_options": [f"Show records from {target_tbl}", f"Count records in {target_tbl}"]
            }

        return None

    def explain_column(self, col_name: str, col_info: Dict[str, Any]) -> str:
        """Constructs a clear, professional narrative explaining the column."""
        tables_str = ", ".join(f"`{t}`" for t in col_info.get("tables", []))
        types_str = "/".join(col_info.get("types", ["VARCHAR"]))
        desc = col_info.get("description", "")
        samples = col_info.get("sample_values", [])

        narrative = f"### Column Definition: `{col_name}`\n\n"
        narrative += f"{desc}\n\n"
        narrative += f"**Database Metadata:**\n"
        narrative += f"- **Data Type**: `{types_str}`\n"
        narrative += f"- **Found in Tables/Views**: {tables_str}\n"

        if "mask" in col_name or "utr" in col_name or "account" in col_name:
            narrative += f"- **Security & Privacy**: Masked or tokenized in analytical views for enterprise compliance (PII protection).\n"

        if samples:
            samples_str = ", ".join(f"`{s}`" for s in samples[:3])
            narrative += f"- **Sample Format**: {samples_str}\n\n"
        else:
            narrative += "\n"

        narrative += "**Example queries you can ask:**\n"
        narrative += f"- *\"Show recent records with `{col_name}` for State Bank of India\"*\n"
        narrative += f"- *\"Show transactions with `{col_name}` for any two accounts\"*\n"

        return narrative

    def explain_typo_column(self, user_term: str, suggested_col: str, col_info: Dict[str, Any]) -> str:
        """Generates proactive 'Did you mean...' response for misspelled column names."""
        desc = col_info.get("description", "")
        narrative = f"Did you mean **`{suggested_col}`**?\n\n"
        narrative += f"Our database does not have a column named `{user_term}`, but **`{suggested_col}`** is an active column in the ledger.\n\n"
        narrative += f"**About `{suggested_col}`:**\n{desc}\n\n"
        narrative += f"Would you like me to show transactions and details using **`{suggested_col}`**?"
        return narrative

    def explain_tables(self, session_id: Optional[str] = None) -> str:
        """Explains all available tables and analytical views in the database."""
        profile = db.get_schema_profile(session_id)
        narrative = "### Database Schema Overview\n\n"
        narrative += "Here are the active tables and analytical views in your database:\n\n"
        for t_name, cols in profile.items():
            col_list = list(cols.keys())[:6]
            preview = ", ".join(f"`{c}`" for c in col_list)
            if len(cols) > 6:
                preview += f", ... (+{len(cols) - 6} more)"
            table_type = "Analytical View" if t_name.startswith("v_") else "Base Table"
            narrative += f"- **`{t_name}`** ({table_type}): Contains {len(cols)} columns ({preview})\n"
        narrative += "\nYou can ask questions about any column, check balances, or query transactions across these datasets."
        return narrative

    def get_schema_context_prompt(self, session_id: Optional[str] = None) -> str:
        """Builds a rich, compact schema cheat-sheet for LLM system prompts."""
        profile = db.get_schema_profile(session_id)
        lines = ["ACTIVE DATABASE TABLES & COLUMNS:"]
        for t_name, cols in profile.items():
            lines.append(f"Table/View `{t_name}`:")
            for c_name, c_info in cols.items():
                d_type = c_info.get("type", "VARCHAR")
                short_desc = STANDARD_FINOPS_GLOSSARY.get(c_name, c_name.replace("_", " "))
                lines.append(f"  * `{c_name}` ({d_type}): {short_desc}")
        return "\n".join(lines)

schema_catalog = SchemaCatalog()
