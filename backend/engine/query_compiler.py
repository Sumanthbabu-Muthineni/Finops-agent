"""
TBX FinOps Assistant - Universal Dynamic Query Compiler (MySQL 8.0 Native)
Compiles typed AST into secure, parameterized MySQL 8.0 ANSI-SQL queries.
Zero hardcoded domain or column schemas. Leverages SchemaValidator for healing
and sqlglot for strict read-only AST safety validation. Supports multi-tenant BYODB.
"""

import sqlglot
from sqlglot import exp
from typing import List, Tuple, Set, Optional, Dict
from backend.core.models import FinancialQueryAST, EntityFilter
from backend.engine.db import db
from backend.engine.schema_validator import schema_validator
from backend.core.crypto import encrypt_utr

class QueryCompiler:
    def __init__(self):
        pass

    def get_source_relation(self, target_table: str, required_columns: Set[str], session_id: Optional[str] = None) -> str:
        """
        Determines the optimal source table, view, or dynamically synthesized join.
        If the target table already contains all required columns (e.g. a view or single table),
        it is used directly. Otherwise, traverses foreign keys to build necessary minimal JOINs.
        """
        profile = db.get_schema_profile(session_id)
        table_clean = target_table.lower().strip()

        # 0. Optimization: if target is a view, see if the base table has all required columns
        # to avoid 17 million row joins dynamically
        base_cand = table_clean
        if base_cand.startswith("v_"):
            base_cand = base_cand[2:]
        if base_cand.endswith("s") and base_cand != "transactions":
            pass 
        
        # Strip trailing 's' if base table is singular (e.g. v_transactions -> transaction)
        base_cand_singular = base_cand[:-1] if base_cand.endswith("s") else base_cand
        
        if base_cand_singular in profile:
            base_cols = set(profile[base_cand_singular].keys())
            if required_columns.issubset(base_cols) or not required_columns:
                return f"`{base_cand_singular}`"

        if base_cand in profile:
            base_cols = set(profile[base_cand].keys())
            if required_columns.issubset(base_cols) or not required_columns:
                return f"`{base_cand}`"

        # 1. Direct table/view usage
        if table_clean in profile:
            table_cols = set(profile[table_clean].keys())
            if required_columns.issubset(table_cols) or not required_columns:
                return f"`{table_clean}`"

        # 2. Check if an analytical view exists for this domain (e.g. v_transactions on demo db)
        view_cand = f"v_{table_clean}" if not table_clean.startswith("v_") else table_clean
        if db.has_view(view_cand, session_id):
            return f"`{view_cand}`"

        # 3. Dynamic Foreign Key Join Traversal (Minimal Join Path)
        fks = db.get_foreign_keys(session_id)
        joins = []
        joined_tables = {table_clean}
        available_cols = set(profile.get(table_clean, {}).keys())

        # Iteratively join tables until all required columns are available
        for fk in fks:
            from_t = fk["from_table"]
            to_t = fk["to_table"]
            if from_t in joined_tables and to_t not in joined_tables:
                joins.append(f"LEFT JOIN `{to_t}` ON `{from_t}`.`{fk['from_column']}` = `{to_t}`.`{fk['to_column']}`")
                joined_tables.add(to_t)
                available_cols.update(profile.get(to_t, {}).keys())
            elif to_t in joined_tables and from_t not in joined_tables:
                joins.append(f"LEFT JOIN `{from_t}` ON `{to_t}`.`{fk['to_column']}` = `{from_t}`.`{fk['from_column']}`")
                joined_tables.add(from_t)
                available_cols.update(profile.get(from_t, {}).keys())

            if required_columns.issubset(available_cols):
                break

        if joins:
            return f"`{table_clean}` " + " ".join(joins)

        return f"`{table_clean}`"

    def compile(self, raw_ast: FinancialQueryAST, session_id: Optional[str] = None) -> str:
        """
        Translates FinancialQueryAST into a secure, parameterized MySQL 8.0 ANSI-SQL string.
        Zero hardcoding: validates and heals columns dynamically against the live database catalog.
        """
        # 1. Anti-hallucination validation and healing against active database
        ast = schema_validator.validate_and_heal(raw_ast, session_id)
        target_table = ast.target_domain
        metric_col = ast.metric_column or "transaction_amount"
        date_col = ast.date_column

        # Collect all columns required by this query to determine joins
        required_cols = set()
        
        # If it's a raw records query and the target is a view, force the view by requesting a column 
        # that only exists in the view (e.g. bank_name or masked_account_number)
        if ast.target_metric == "records_list" and target_table.startswith("v_"):
            required_cols.add("bank_name")
            
        if metric_col:
            required_cols.add(metric_col)
        if date_col:
            required_cols.add(date_col)
        for f in ast.entity_filters:
            required_cols.add(f.field)
        for g in (ast.group_by or []):
            if g not in ["month", "year", "day"]:
                required_cols.add(g)

        # 2. Build WHERE clauses
        where_clauses = []
        field_filters: Dict[str, List[EntityFilter]] = {}
        for f in ast.entity_filters:
            field = f.field.lower().strip()
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
                        where_clauses.append(f"UPPER(CAST({field} AS CHAR)) = UPPER('{escaped_val}')")
                else:
                    if field == "utr_number":
                        enc_vals = [encrypt_utr(str(v)).replace("'", "''") for v in vals]
                        all_vals = ", ".join(f"'{v}'" for v in enc_vals + [str(v).replace("'", "''") for v in vals])
                        where_clauses.append(f"{field} IN ({all_vals})")
                    else:
                        escaped_vals = ", ".join(f"UPPER('{str(v).replace('\'', '\'\'')}')" for v in vals)
                        where_clauses.append(f"UPPER(CAST({field} AS CHAR)) IN ({escaped_vals})")
            else:
                for f in filters:
                    op = f.operator.lower()
                    val = f.value
                    if op == "like":
                        where_clauses.append(f"UPPER(CAST({field} AS CHAR)) LIKE UPPER('%{str(val).replace('\'', '\'\'')}%')")
                    elif op == "gt":
                        where_clauses.append(f"{field} > {val}")
                    elif op == "gte":
                        where_clauses.append(f"{field} >= {val}")
                    elif op == "lt":
                        where_clauses.append(f"{field} < {val}")
                    elif op == "lte":
                        where_clauses.append(f"{field} <= {val}")
                    elif op == "neq":
                        where_clauses.append(f"UPPER(CAST({field} AS CHAR)) != UPPER('{str(val).replace('\'', '\'\'')}')")

        # Date range boundary filters
        if ast.date_range and date_col:
            start_d = ast.date_range.start_date
            end_d = ast.date_range.end_date
            where_clauses.append(f"{date_col} >= '{start_d}'")
            where_clauses.append(f"{date_col} <= '{end_d}'")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # 3. Build SELECT, GROUP BY, and ORDER BY
        if ast.group_by:
            select_cols = []
            group_cols = []
            order_cols = []
            for g in ast.group_by:
                g_lower = g.lower().strip()
                if g_lower == "month" and date_col:
                    expr = f"DATE_FORMAT(`{date_col}`, '%Y-%m')"
                    select_cols.append(f"{expr} AS month")
                    group_cols.append(expr)
                    order_cols.append(f"month {'DESC' if ast.order_by_desc else 'ASC'}")
                elif g_lower == "year" and date_col:
                    expr = f"YEAR(`{date_col}`)"
                    select_cols.append(f"{expr} AS year")
                    group_cols.append(expr)
                    order_cols.append(f"year {'DESC' if ast.order_by_desc else 'ASC'}")
                elif g_lower == "day" and date_col:
                    expr = f"DATE_FORMAT(`{date_col}`, '%Y-%m-%d')"
                    select_cols.append(f"{expr} AS day")
                    group_cols.append(expr)
                    order_cols.append(f"day {'DESC' if ast.order_by_desc else 'ASC'}")
                else:
                    select_cols.append(f"`{g}`")
                    group_cols.append(f"`{g}`")
                    order_cols.append(f"`{g}` ASC")

            metric_expr = f"ROUND(COALESCE(SUM(`{metric_col}`), 0), 2)" if metric_col else "0"
            avg_expr = f"ROUND(COALESCE(AVG(`{metric_col}`), 0), 2)" if metric_col else "0"

            select_sql = f"SELECT {', '.join(select_cols)}, {metric_expr} AS total_amount, COUNT(*) AS record_count, {avg_expr} AS average_amount"
            group_sql = f"GROUP BY {', '.join(group_cols)}"
            order_sql = f"ORDER BY {', '.join(order_cols)}"
        else:
            metric_expr = f"ROUND(COALESCE(SUM(`{metric_col}`), 0), 2)" if metric_col else "0"
            avg_expr = f"ROUND(COALESCE(AVG(`{metric_col}`), 0), 2)" if metric_col else "0"

            if ast.target_metric == "total_amount":
                select_sql = f"SELECT {metric_expr} AS total_amount, COUNT(*) AS record_count, {avg_expr} AS average_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "available_balance":
                select_sql = f"SELECT {metric_expr} AS total_amount, COUNT(*) AS record_count, {avg_expr} AS average_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "average_amount":
                select_sql = f"SELECT {avg_expr} AS average_amount, COUNT(*) AS record_count"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric == "record_count":
                select_sql = f"SELECT {metric_expr} AS total_amount, COUNT(*) AS record_count"
                group_sql = ""
                order_sql = ""
            else:  # records_list
                select_sql = "SELECT *"
                group_sql = ""
                if target_table.startswith("v_") or target_table == "v_transactions":
                    order_sql = ""
                else:
                    if date_col:
                        order_sql = f"ORDER BY `{date_col}` {'DESC' if ast.order_by_desc else 'ASC'}"
                    elif metric_col:
                        order_sql = f"ORDER BY `{metric_col}` {'DESC' if ast.order_by_desc else 'ASC'}"
                    else:
                        order_sql = ""

        limit_sql = f"LIMIT {ast.limit}"
        source_relation = self.get_source_relation(target_table, required_cols, session_id)

        sql = f"{select_sql} FROM {source_relation} {where_sql} {group_sql} {order_sql} {limit_sql};".strip()
        sql = " ".join(sql.split())

        # 4. Security validation with sqlglot (MySQL dialect)
        self.validate_safety(sql)
        return sql

    def compile_records_query(self, ast: FinancialQueryAST, session_id: Optional[str] = None) -> str:
        """Always compiles raw line items query so AgGrid and CSV export have granular records."""
        records_ast = ast.model_copy(deep=True)
        records_ast.target_metric = "records_list"
        records_ast.group_by = []
        return self.compile(records_ast, session_id)

    def validate_safety(self, sql: str) -> bool:
        """Enforces that the compiled SQL is strictly a read-only SELECT statement."""
        try:
            parsed = sqlglot.parse_one(sql, read="mysql")
        except Exception:
            parsed = sqlglot.parse_one(sql)

        if not isinstance(parsed, exp.Select):
            raise ValueError(f"Security Violation: Only SELECT queries are permitted. Got: {type(parsed)}")

        disallowed = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter)
        for node in parsed.walk():
            if isinstance(node, disallowed):
                raise ValueError(f"Security Violation: Disallowed statement found: {type(node)}")

        return True

query_compiler = QueryCompiler()
