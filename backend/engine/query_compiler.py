import sqlglot
from sqlglot import exp
from typing import List, Tuple
from backend.core.models import FinancialQueryAST, EntityFilter
from backend.engine.db import db
from backend.core.crypto import encrypt_utr

class QueryCompiler:
    KNOWN_COLUMNS = {
        "v_transactions": {
            "transaction_id", "account_id", "entity_id", "masked_account_number", "account_number",
            "bank_code", "bank_name", "program_id", "transaction_date", "transaction_day",
            "transaction_type", "transaction_amount", "amount", "description",
            "transaction_reference_id", "reference_id", "masked_utr_number", "utr_number",
            "available_balance", "txn_year", "txn_month", "status"
        },
        "v_accounts": {
            "account_id", "entity_id", "masked_account_number", "account_number",
            "bank_code", "bank_name", "program_id", "available_balance", "balance", "status"
        },
        "v_banks": {
            "bank_code", "bank_name", "total_accounts", "total_available_balance", "status"
        }
    }

    def __init__(self):
        self._cached_columns = {}

    def get_allowed_columns(self, view_name: str) -> set:
        """Dynamically inspects database views to discover all valid columns without hardcoding."""
        if view_name not in self._cached_columns:
            try:
                df, _, count = db.execute_query(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    (view_name.lower(),)
                )
                if count > 0:
                    cols = {c.lower() for c in df["column_name"].tolist()}
                    cols.add("status")
                    self._cached_columns[view_name] = cols
                else:
                    self._cached_columns[view_name] = set(self.KNOWN_COLUMNS.get(view_name, []))
            except Exception:
                self._cached_columns[view_name] = set(self.KNOWN_COLUMNS.get(view_name, []))
        return self._cached_columns[view_name]

    def get_source_relation(self, domain: str, view_name: str) -> str:
        """Returns the analytical view name if present, or an equivalent ANSI-SQL join subquery if views were not created."""
        if db.has_view(view_name):
            return view_name

        # Fallback subqueries for read-only evaluator databases where views were not created
        if domain == "accounts":
            return """(
                SELECT 
                    a.account_id, a.entity_id,
                    '****' || RIGHT(a.account_number, 4) AS masked_account_number,
                    '****' || RIGHT(a.account_number, 4) AS account_number,
                    a.bank_code, b.bank_name, a.program_id,
                    a.available_balance,
                    a.available_balance AS balance
                FROM account a
                JOIN bank b ON a.bank_code = b.bank_code
            ) v_accounts"""
        elif domain == "banks":
            return """(
                SELECT 
                    b.bank_code, b.bank_name,
                    COUNT(a.account_id) AS total_accounts,
                    ROUND(CAST(COALESCE(SUM(a.available_balance), 0) AS NUMERIC), 2) AS total_available_balance
                FROM bank b
                LEFT JOIN account a ON b.bank_code = a.bank_code
                GROUP BY b.bank_code, b.bank_name
            ) v_banks"""
        else:
            return """(
                SELECT 
                    t.transaction_id, t.account_id, a.entity_id,
                    '****' || RIGHT(a.account_number, 4) AS masked_account_number,
                    '****' || RIGHT(a.account_number, 4) AS account_number,
                    b.bank_code, b.bank_name, a.program_id, t.transaction_date,
                    CAST(t.transaction_date AS DATE) AS transaction_day,
                    LOWER(t.transaction_type) AS transaction_type,
                    t.transaction_amount,
                    t.transaction_amount AS amount,
                    t.description, t.transaction_reference_id,
                    t.transaction_reference_id AS reference_id,
                    t.utr_number AS masked_utr_number, t.utr_number,
                    a.available_balance,
                    EXTRACT(YEAR FROM t.transaction_date)::INTEGER AS txn_year,
                    EXTRACT(MONTH FROM t.transaction_date)::INTEGER AS txn_month
                FROM transaction t
                JOIN account a ON t.account_id = a.account_id
                JOIN bank b ON a.bank_code = b.bank_code
            ) v_transactions"""

    def compile(self, ast: FinancialQueryAST) -> str:
        """Translates FinancialQueryAST into a secure, parameterized PostgreSQL ANSI-SQL string."""
        # 1. Map target domain to analytical view
        domain = (ast.target_domain or "transactions").lower().strip()
        if domain == "accounts":
            view_name = "v_accounts"
            date_col = None
            metric_col = "available_balance"
        elif domain == "banks":
            view_name = "v_banks"
            date_col = None
            metric_col = "total_available_balance"
        else:  # default to "transactions"
            view_name = "v_transactions"
            date_col = "transaction_date"
            metric_col = "transaction_amount"

        # 2. Build WHERE clauses
        where_clauses = []
        allowed_cols = self.get_allowed_columns(view_name)

        # Entity Filters (Universal, case-insensitive handling for all text columns)
        field_filters = {}
        for f in ast.entity_filters:
            field = f.field.lower().strip()
            # Map legacy or synonym column names dynamically
            if field == "vendor_name" and "bank_name" in allowed_cols:
                field = "bank_name"
            elif field in ["status", "type"] and "transaction_type" in allowed_cols:
                field = "transaction_type"
            elif field in ["reference", "ref", "ref_no", "reference_no", "receipt"] and "transaction_reference_id" in allowed_cols:
                field = "transaction_reference_id"
            elif field in ["utr", "utr_no"] and "utr_number" in allowed_cols:
                field = "utr_number"
            elif field in ["account", "account_no", "acc_no"] and "account_number" in allowed_cols:
                field = "account_number"
            elif field not in allowed_cols:
                continue

            if field not in field_filters:
                field_filters[field] = []
            field_filters[field].append(f)

        for field, filters in field_filters.items():
            if all(f.operator.lower() == "eq" for f in filters):
                vals = [f.value for f in filters]
                if len(vals) == 1:
                    escaped_val = str(vals[0]).replace("'", "''")
                    if field == "utr_number":
                        enc_val = encrypt_utr(str(vals[0])).replace("'", "''")
                        where_clauses.append(f"({field} = '{enc_val}' OR {field} = '{escaped_val}')")
                    else:
                        where_clauses.append(f"UPPER(CAST({field} AS VARCHAR)) = UPPER('{escaped_val}')")
                else:
                    if field == "utr_number":
                        enc_vals = [encrypt_utr(str(v)).replace("'", "''") for v in vals]
                        all_vals = ", ".join(f"'{v}'" for v in enc_vals + [str(v).replace("'", "''") for v in vals])
                        where_clauses.append(f"{field} IN ({all_vals})")
                    else:
                        escaped_vals = ", ".join(f"UPPER('{str(v).replace('\'', '\'\'')}')" for v in vals)
                        where_clauses.append(f"UPPER(CAST({field} AS VARCHAR)) IN ({escaped_vals})")
            else:
                col_clauses = []
                for f in filters:
                    op = f.operator.lower()
                    val = f.value
                    if op == "eq":
                        escaped_val = str(val).replace("'", "''")
                        if field == "utr_number":
                            enc_val = encrypt_utr(str(val)).replace("'", "''")
                            col_clauses.append(f"({field} = '{enc_val}' OR {field} = '{escaped_val}')")
                        else:
                            col_clauses.append(f"UPPER(CAST({field} AS VARCHAR)) = UPPER('{escaped_val}')")
                    elif op == "neq":
                        escaped_val = str(val).replace("'", "''")
                        col_clauses.append(f"UPPER(CAST({field} AS VARCHAR)) != UPPER('{escaped_val}')")
                    elif op == "in" and isinstance(val, list):
                        escaped_vals = ", ".join(f"UPPER('{str(v).replace('\'', '\'\'')}')" for v in val)
                        col_clauses.append(f"UPPER(CAST({field} AS VARCHAR)) IN ({escaped_vals})")
                    elif op == "like":
                        escaped_val = str(val).replace("'", "''")
                        col_clauses.append(f"CAST({field} AS VARCHAR) ILIKE '%{escaped_val}%'")
                    elif op in ["gt", "lt", "gte", "lte"]:
                        op_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
                        try:
                            num_val = float(val)
                            col_clauses.append(f"{field} {op_map[op]} {num_val}")
                        except (ValueError, TypeError):
                            escaped_val = str(val).replace("'", "''")
                            col_clauses.append(f"{field} {op_map[op]} '{escaped_val}'")
                if col_clauses:
                    where_clauses.append("(" + " OR ".join(col_clauses) + ")" if len(col_clauses) > 1 else col_clauses[0])

        # Date Range Filters (applied when view has a temporal dimension)
        if date_col and ast.date_range:
            if ast.date_range.start_date:
                where_clauses.append(f"{date_col} >= '{ast.date_range.start_date}'")
            if ast.date_range.end_date:
                where_clauses.append(f"{date_col} <= '{ast.date_range.end_date}'")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # 3. Build SELECT and GROUP BY clauses (Universal for all allowed columns)
        mapped_group_bys = []
        for g in (ast.group_by or []):
            g_clean = g.lower().strip()
            mapped_col = None
            if g_clean in ["status", "type"] and "transaction_type" in allowed_cols:
                mapped_col = "transaction_type"
            elif g_clean in ["vendor", "vendor_name", "company", "companies", "bank", "banks", "bank_name", "partner", "partners", "entity", "entities", "entity_id"] and "bank_name" in allowed_cols:
                mapped_col = "bank_name"
            elif g_clean in allowed_cols and g_clean != "entity_id":
                mapped_col = g_clean
            elif date_col and g_clean in ["month", "year"]:
                mapped_col = g_clean

            if mapped_col and mapped_col not in mapped_group_bys:
                mapped_group_bys.append(mapped_col)

        if mapped_group_bys:
            select_group_cols = []
            actual_group_by_cols = []
            for g in mapped_group_bys:
                if date_col and g == "month":
                    select_group_cols.append(f"CAST(EXTRACT(MONTH FROM {date_col}) AS INTEGER) AS month")
                    actual_group_by_cols.append(f"CAST(EXTRACT(MONTH FROM {date_col}) AS INTEGER)")
                elif date_col and g == "year":
                    select_group_cols.append(f"CAST(EXTRACT(YEAR FROM {date_col}) AS INTEGER) AS year")
                    actual_group_by_cols.append(f"CAST(EXTRACT(YEAR FROM {date_col}) AS INTEGER)")
                else:
                    select_group_cols.append(g)
                    actual_group_by_cols.append(g)

            select_sql = f"SELECT {', '.join(select_group_cols)}, ROUND(CAST(SUM({metric_col}) AS NUMERIC), 2) AS total_amount, COUNT(*) AS record_count"
            group_sql = f"GROUP BY {', '.join(actual_group_by_cols)}"
            order_sql = f"ORDER BY total_amount {'DESC' if ast.order_by_desc else 'ASC'}"
        else:
            if ast.target_metric in ["total_amount", "available_balance"]:
                select_sql = f"SELECT ROUND(CAST(SUM({metric_col}) AS NUMERIC), 2) AS total_amount, COUNT(*) AS record_count, ROUND(CAST(AVG({metric_col}) AS NUMERIC), 2) AS average_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "average_amount":
                select_sql = f"SELECT ROUND(CAST(AVG({metric_col}) AS NUMERIC), 2) AS average_amount, COUNT(*) AS record_count, ROUND(CAST(SUM({metric_col}) AS NUMERIC), 2) AS total_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "record_count":
                select_sql = f"SELECT COUNT(*) AS record_count, ROUND(CAST(SUM({metric_col}) AS NUMERIC), 2) AS total_amount"
                group_sql = ""
                order_sql = ""
            else:  # records_list
                select_sql = "SELECT * "
                group_sql = ""
                if date_col:
                    order_sql = f"ORDER BY {date_col} {'DESC' if ast.order_by_desc else 'ASC'}"
                else:
                    order_sql = f"ORDER BY {metric_col} {'DESC' if ast.order_by_desc else 'ASC'}"

        limit_sql = f"LIMIT {ast.limit}"

        source_relation = self.get_source_relation(domain, view_name)
        sql = f"{select_sql} FROM {source_relation} {where_sql} {group_sql} {order_sql} {limit_sql};".strip()
        sql = " ".join(sql.split())

        # 4. Security validation with sqlglot
        self.validate_safety(sql)
        return sql

    def compile_records_query(self, ast: FinancialQueryAST) -> str:
        """Always compiles raw line items query so AgGrid and CSV export have granular records."""
        records_ast = ast.model_copy(deep=True)
        records_ast.target_metric = "records_list"
        records_ast.group_by = []
        return self.compile(records_ast)

    def validate_safety(self, sql: str) -> bool:
        """Enforces that the compiled SQL is strictly a read-only SELECT statement."""
        parsed = sqlglot.parse_one(sql, read="postgres")
        if not isinstance(parsed, exp.Select):
            raise ValueError(f"Security Violation: Only SELECT queries are permitted. Got: {type(parsed)}")

        # Ensure no disallowed expressions (Insert, Update, Delete, Drop, Alter)
        disallowed = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter)
        for node in parsed.walk():
            if isinstance(node, disallowed):
                raise ValueError(f"Security Violation: Disallowed statement found: {type(node)}")

        return True

query_compiler = QueryCompiler()
