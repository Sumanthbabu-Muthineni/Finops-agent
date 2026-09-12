"""
TBX FinOps Assistant - Anti-Hallucination Schema Validator Guardrail
Validates and auto-corrects LLM-generated AST queries against live MySQL database schema.
Uses RapidFuzz Levenshtein matching to heal near-miss column names, eliminates hallucinated
fields, and binds queries to real database tables and columns.
"""

from typing import Dict, Any, List, Optional, Set, Tuple
from rapidfuzz import process, fuzz
from backend.core.models import FinancialQueryAST, EntityFilter
from backend.engine.db import db

class SchemaValidator:
    def __init__(self):
        self._cached_table_columns: Dict[str, Set[str]] = {}

    def get_valid_columns_for_table(self, table_name: str) -> Set[str]:
        """Returns lowercase set of all valid column names for a given table or view, including joined tables."""
        table_clean = table_name.lower().strip()
        profile = db.get_schema_profile()
        cols = set()
        
        if table_clean in profile:
            cols.update(profile[table_clean].keys())
        else:
            # Check in live table introspection
            tables = db.get_tables_and_views()
            if table_clean in tables:
                try:
                    df, _, _ = db.execute_query(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND LOWER(table_name) = %s",
                        (table_clean,)
                    )
                    cols.update({str(c).lower() for c in df["column_name"].tolist()})
                except Exception:
                    pass

        # Also include columns from foreign key joined tables to support dynamic joins
        fks = db.get_foreign_keys()
        for fk in fks:
            if fk["from_table"] == table_clean:
                joined_table = fk["to_table"]
                if joined_table in profile:
                    cols.update(profile[joined_table].keys())
            elif fk["to_table"] == table_clean:
                joined_table = fk["from_table"]
                if joined_table in profile:
                    cols.update(profile[joined_table].keys())
                    
        return cols

    def resolve_target_table(self, requested_domain: str) -> str:
        """Resolves target table/view name, supporting domain aliases and fuzzy matching."""
        req = (requested_domain or "transactions").lower().strip()
        tables = db.get_tables_and_views()

        # 1. Exact match
        if req in tables:
            return req

        # 2. View vs Base Table preference
        # Prefer analytical views if available (e.g. 'v_transactions' for 'transactions')
        view_candidate = f"v_{req}"
        if view_candidate in tables:
            return view_candidate



        # 3. Fuzzy match against all available tables and views
        all_names = list(tables.keys())
        if all_names:
            match = process.extractOne(req, all_names, scorer=fuzz.token_set_ratio)
            if match and match[1] >= 70:
                return match[0]

        # Default fallback to first table or 'transactions'
        return all_names[0] if all_names else req

    def auto_detect_metric_column(self, table_name: str) -> Optional[str]:
        """Dynamically identifies the primary numeric column for aggregations in a table."""
        profile = db.get_schema_profile()
        cols = profile.get(table_name.lower(), {})

        # 1. Priority financial column names
        for priority_name in [
            "transaction_amount", "amount", "available_balance", "balance",
            "total_amount", "total_available_balance", "price", "total", "cost", "value"
        ]:
            if priority_name in cols:
                return priority_name

        # 2. First numeric/decimal column that is not an ID or year/month/code
        for c_name, info in cols.items():
            d_type = info.get("type", "")
            is_numeric = any(t in d_type for t in ["DECIMAL", "DOUBLE", "FLOAT", "NUMERIC", "INT", "BIGINT"])
            is_non_metric = any(k in c_name for k in ["id", "year", "month", "day", "code", "zip", "phone", "status"])
            if is_numeric and not is_non_metric:
                return c_name

        return None

    def auto_detect_date_column(self, table_name: str) -> Optional[str]:
        """Dynamically identifies the primary temporal column in a table."""
        profile = db.get_schema_profile()
        cols = profile.get(table_name.lower(), {})

        # Priority temporal column names
        for priority_name in ["transaction_date", "date", "created_at", "timestamp", "transaction_day", "posted_at"]:
            if priority_name in cols:
                return priority_name

        # Any DATE or DATETIME column
        for c_name, info in cols.items():
            d_type = info.get("type", "")
            if any(t in d_type for t in ["DATE", "DATETIME", "TIMESTAMP"]) or "date" in c_name:
                return c_name

        return None

    def resolve_column_name(self, raw_col: str, valid_columns: Set[str]) -> Optional[str]:
        """
        Heals and resolves near-miss or synonym column names against valid table columns.
        Uses fuzzy Levenshtein distance to prevent hallucination.
        """
        col = raw_col.lower().strip()
        if col in valid_columns:
            return col



        # Fuzzy string matching via RapidFuzz
        if valid_columns:
            match = process.extractOne(col, list(valid_columns), scorer=fuzz.token_set_ratio)
            if match and match[1] >= 75.0:
                return match[0]

        return None

    def validate_and_heal(self, ast: FinancialQueryAST) -> FinancialQueryAST:
        """
        Inspects, heals, and validates the entire AST against live MySQL schema.
        Prevents SQL injection, syntax crashes, and hallucinations.
        """
        healed_ast = ast.model_copy(deep=True)

        # 1. Resolve target table/view
        healed_table = self.resolve_target_table(healed_ast.target_domain)
        healed_ast.target_domain = healed_table
        valid_cols = self.get_valid_columns_for_table(healed_table)

        # 2. Resolve metric column
        if not healed_ast.metric_column or healed_ast.metric_column not in valid_cols:
            auto_metric = self.auto_detect_metric_column(healed_table)
            healed_ast.metric_column = auto_metric

        # 3. Resolve date column
        if not healed_ast.date_column or healed_ast.date_column not in valid_cols:
            auto_date = self.auto_detect_date_column(healed_table)
            healed_ast.date_column = auto_date

        # 4. Heal and validate entity filters
        validated_filters: List[EntityFilter] = []
        for f in healed_ast.entity_filters:
            resolved_col = self.resolve_column_name(f.field, valid_cols)
            if resolved_col:
                validated_filters.append(
                    EntityFilter(
                        field=resolved_col,
                        operator=f.operator,
                        value=f.value
                    )
                )
            else:
                # Discard unresolvable hallucinated column
                print(f"⚠️ Schema Validator: Dropped hallucinated filter field '{f.field}' for table '{healed_table}'")

        healed_ast.entity_filters = validated_filters

        # 5. Heal and validate group_by columns
        validated_group_bys: List[str] = []
        for g in (healed_ast.group_by or []):
            g_clean = g.lower().strip()
            # Special temporal groupings
            if g_clean in ["month", "year", "day"] and healed_ast.date_column:
                if g_clean not in validated_group_bys:
                    validated_group_bys.append(g_clean)
                continue

            resolved_col = self.resolve_column_name(g_clean, valid_cols)
            if resolved_col and resolved_col not in validated_group_bys:
                validated_group_bys.append(resolved_col)

        healed_ast.group_by = validated_group_bys

        return healed_ast

schema_validator = SchemaValidator()
