import sqlglot
from sqlglot import exp
from typing import List, Tuple
from backend.core.models import FinancialQueryAST, EntityFilter
from backend.engine.db import db

class QueryCompiler:
    def __init__(self):
        self._cached_columns = {}

    def get_allowed_columns(self, view_name: str) -> set:
        """Dynamically inspects database views to discover all valid columns without hardcoding."""
        if view_name not in self._cached_columns:
            try:
                cols = {r[0].lower() for r in db.con.execute(f"DESCRIBE {view_name}").fetchall()}
                cols.add("status")
                self._cached_columns[view_name] = cols
            except Exception:
                return set()
        return self._cached_columns[view_name]

    def compile(self, ast: FinancialQueryAST) -> str:
        """Translates FinancialQueryAST into a secure, parameterized DuckDB ANSI-SQL string."""
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
            elif field == "status" and "transaction_type" in allowed_cols:
                field = "transaction_type"
            elif field == "type" and "transaction_type" in allowed_cols:
                field = "transaction_type"
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
                    where_clauses.append(f"UPPER(CAST({field} AS VARCHAR)) = UPPER('{escaped_val}')")
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
                        col_clauses.append(f"{field} {op_map[op]} {float(val)}")
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
            if g_clean in ["status", "type"] and "transaction_type" in allowed_cols:
                mapped_group_bys.append("transaction_type")
            elif g_clean in ["vendor", "vendor_name"] and "bank_name" in allowed_cols:
                mapped_group_bys.append("bank_name")
            elif g_clean in allowed_cols or (date_col and g_clean in ["month", "year"]):
                mapped_group_bys.append(g_clean)

        if mapped_group_bys:
            group_cols = []
            for g in mapped_group_bys:
                if date_col and g == "month":
                    group_cols.append(f"EXTRACT(MONTH FROM {date_col}) AS month")
                elif date_col and g == "year":
                    group_cols.append(f"EXTRACT(YEAR FROM {date_col}) AS year")
                else:
                    group_cols.append(g)

            select_sql = f"SELECT {', '.join(group_cols)}, ROUND(SUM({metric_col}), 2) AS total_amount, COUNT(*) AS record_count"
            group_sql = f"GROUP BY {', '.join(group_cols)}"
            order_sql = f"ORDER BY total_amount {'DESC' if ast.order_by_desc else 'ASC'}"
        else:
            if ast.target_metric in ["total_amount", "available_balance"]:
                select_sql = f"SELECT ROUND(SUM({metric_col}), 2) AS total_amount, COUNT(*) AS record_count, ROUND(AVG({metric_col}), 2) AS average_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "average_amount":
                select_sql = f"SELECT ROUND(AVG({metric_col}), 2) AS average_amount, COUNT(*) AS record_count, ROUND(SUM({metric_col}), 2) AS total_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "record_count":
                select_sql = f"SELECT COUNT(*) AS record_count, ROUND(SUM({metric_col}), 2) AS total_amount"
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

        sql = f"{select_sql} FROM {view_name} {where_sql} {group_sql} {order_sql} {limit_sql};".strip()
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
        parsed = sqlglot.parse_one(sql, read="duckdb")
        if not isinstance(parsed, exp.Select):
            raise ValueError(f"Security Violation: Only SELECT queries are permitted. Got: {type(parsed)}")

        # Ensure no disallowed expressions (Insert, Update, Delete, Drop, Alter)
        disallowed = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter)
        for node in parsed.walk():
            if isinstance(node, disallowed):
                raise ValueError(f"Security Violation: Disallowed statement found: {type(node)}")

        return True

query_compiler = QueryCompiler()
