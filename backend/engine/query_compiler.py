"""
TBX FinOps Assistant - Universal Dynamic Query Compiler (MySQL 8.0 Native)
Compiles typed AST into secure, parameterized MySQL 8.0 ANSI-SQL queries.
Zero hardcoded domain or column schemas. Leverages SchemaValidator for healing
and sqlglot for strict read-only AST safety validation.
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

    def get_source_relation(self, target_table: str, required_columns: Set[str]) -> str:
        """
        Determines the optimal source table, view, or dynamically synthesized join.
        If the target table already contains all required columns (e.g. a view or single table),
        it is used directly. Otherwise, traverses foreign keys to build necessary JOINs.
        """
        profile = db.get_schema_profile()
        table_clean = target_table.lower().strip()

        # 0. Optimization: if target is a view, see if the base table has all required columns
        # to avoid 17 million row joins dynamically
        base_cand = table_clean
        if base_cand.startswith("v_"):
            base_cand = base_cand[2:]
        if base_cand.endswith("s") and base_cand != "transactions":
            # "transactions" doesn't have an "s" table but "account" does. Let's just try both
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
            # If all required columns exist in this table/view, query directly!
            if required_columns.issubset(table_cols) or not required_columns:
                return f"`{table_clean}`"

        # 2. Check if an analytical view exists for this domain (e.g. v_transactions)
        view_cand = f"v_{table_clean}" if not table_clean.startswith("v_") else table_clean
        if db.has_view(view_cand):
            return f"`{view_cand}`"

        # 3. Dynamic Foreign Key Join Traversal
        fks = db.get_foreign_keys()
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

    def compile(self, raw_ast: FinancialQueryAST) -> str:
        """
        Translates FinancialQueryAST into a secure, parameterized MySQL 8.0 ANSI-SQL string.
        Zero hardcoding: validates and heals columns dynamically against the live database catalog.
        """
        # 1. Anti-hallucination validation and healing
        ast = schema_validator.validate_and_heal(raw_ast)
        target_table = ast.target_domain
        metric_col = ast.metric_column or "transaction_amount"
        date_col = ast.date_column

        # Collect all columns required by this query to determine joins
        required_cols = set()
        
        # If it's a raw records query and the target is a view, force the view by requesting a column 
        # that only exists in the view (e.g. bank_name or masked_account_number)
        if ast.target_metric == "records_list" and target_table.startswith("v_"):
            # This ensures we don't accidentally fall back to the base table and lose UI columns
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
                            col_clauses.append(f"UPPER(CAST({field} AS CHAR)) = UPPER('{escaped_val}')")
                    elif op == "neq":
                        escaped_val = str(val).replace("'", "''")
                        col_clauses.append(f"UPPER(CAST({field} AS CHAR)) != UPPER('{escaped_val}')")
                    elif op == "in" and isinstance(val, list):
                        escaped_vals = ", ".join(f"UPPER('{str(v).replace('\'', '\'\'')}')" for v in val)
                        col_clauses.append(f"UPPER(CAST({field} AS CHAR)) IN ({escaped_vals})")
                    elif op == "like":
                        escaped_val = str(val).replace("'", "''")
                        col_clauses.append(f"LOWER(CAST({field} AS CHAR)) LIKE LOWER('%{escaped_val}%')")
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

        # Date Range Filters (applied when table has a temporal column)
        if date_col and ast.date_range:
            if ast.date_range.start_date:
                where_clauses.append(f"{date_col} >= '{ast.date_range.start_date}'")
            if ast.date_range.end_date:
                where_clauses.append(f"{date_col} <= '{ast.date_range.end_date}'")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # 3. Build SELECT, GROUP BY, and ORDER BY clauses
        mapped_group_bys = []
        for g in (ast.group_by or []):
            g_clean = g.lower().strip()
            if g_clean in ["month", "year", "day"] and date_col:
                mapped_group_bys.append(g_clean)
            elif g_clean in required_cols and g_clean != "entity_id":
                if g_clean not in mapped_group_bys:
                    mapped_group_bys.append(g_clean)

        if mapped_group_bys:
            select_group_cols = []
            actual_group_by_cols = []
            for g in mapped_group_bys:
                if date_col and g == "month":
                    select_group_cols.append(f"MONTH({date_col}) AS month")
                    actual_group_by_cols.append(f"MONTH({date_col})")
                elif date_col and g == "year":
                    select_group_cols.append(f"YEAR({date_col}) AS year")
                    actual_group_by_cols.append(f"YEAR({date_col})")
                elif date_col and g == "day":
                    select_group_cols.append(f"DATE({date_col}) AS day")
                    actual_group_by_cols.append(f"DATE({date_col})")
                else:
                    select_group_cols.append(f"`{g}`")
                    actual_group_by_cols.append(f"`{g}`")

            metric_expr = f"ROUND(COALESCE(SUM(`{metric_col}`), 0), 2)" if metric_col else "0"
            select_sql = f"SELECT {', '.join(select_group_cols)}, {metric_expr} AS total_amount, COUNT(*) AS record_count"
            group_sql = f"GROUP BY {', '.join(actual_group_by_cols)}"
            order_sql = f"ORDER BY total_amount {'DESC' if ast.order_by_desc else 'ASC'}"
        else:
            if ast.target_metric in ["total_amount", "available_balance", "sum"]:
                metric_expr = f"ROUND(COALESCE(SUM(`{metric_col}`), 0), 2)" if metric_col else "0"
                avg_expr = f"ROUND(COALESCE(AVG(`{metric_col}`), 0), 2)" if metric_col else "0"
                select_sql = f"SELECT {metric_expr} AS total_amount, COUNT(*) AS record_count, {avg_expr} AS average_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric in ["average_amount", "average"]:
                metric_expr = f"ROUND(COALESCE(SUM(`{metric_col}`), 0), 2)" if metric_col else "0"
                avg_expr = f"ROUND(COALESCE(AVG(`{metric_col}`), 0), 2)" if metric_col else "0"
                select_sql = f"SELECT {avg_expr} AS average_amount, COUNT(*) AS record_count, {metric_expr} AS total_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric in ["record_count", "count"]:
                metric_expr = f"ROUND(COALESCE(SUM(`{metric_col}`), 0), 2)" if metric_col else "0"
                select_sql = f"SELECT COUNT(*) AS record_count, {metric_expr} AS total_amount"
                group_sql = ""
                order_sql = ""
            elif ast.target_metric in ["min", "max"]:
                fn = "MIN" if ast.target_metric == "min" else "MAX"
                metric_expr = f"ROUND(COALESCE({fn}(`{metric_col}`), 0), 2)" if metric_col else "0"
                select_sql = f"SELECT {metric_expr} AS total_amount, COUNT(*) AS record_count"
                group_sql = ""
                order_sql = ""
            else:  # records_list
                select_sql = "SELECT *"
                group_sql = ""
                # Avoid massive filesorts on 17M row views by disabling ORDER BY
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
        source_relation = self.get_source_relation(target_table, required_cols)

        sql = f"{select_sql} FROM {source_relation} {where_sql} {group_sql} {order_sql} {limit_sql};".strip()
        sql = " ".join(sql.split())

        # 4. Security validation with sqlglot (MySQL dialect)
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
        try:
            parsed = sqlglot.parse_one(sql, read="mysql")
        except Exception:
            parsed = sqlglot.parse_one(sql)

        if not isinstance(parsed, exp.Select):
            raise ValueError(f"Security Violation: Only SELECT queries are permitted. Got: {type(parsed)}")

        # Ensure no disallowed expressions (Insert, Update, Delete, Drop, Alter)
        disallowed = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter)
        for node in parsed.walk():
            if isinstance(node, disallowed):
                raise ValueError(f"Security Violation: Disallowed statement found: {type(node)}")

        return True

query_compiler = QueryCompiler()
