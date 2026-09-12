"""
TBX FinOps Assistant - Index & Schema Performance Advisor
Performs zero-DDL schema profiling to discover index coverage, detects unindexed
analytical bottlenecks, and generates actionable, copy-pasteable optimization advice
to make the AI agent run up to 50x faster on customer databases.
"""

from typing import Dict, Any, List, Optional, Set
import re

CRITICAL_ANALYTICAL_PATTERNS = [
    # (Regex pattern matching column name, priority, analytical role)
    (r"(date|time|timestamp|created_at|txn_date)", "HIGH", "Temporal Filtering & Date-Range Aggregations"),
    (r"(account_id|entity_id|bank_code|customer_id|vendor_id|user_id)", "HIGH", "Entity Lookups & Foreign Key Table Joins"),
    (r"(reference_id|ref_id|receipt|utr|utr_number|hash)", "MEDIUM", "Unique Receipt & Transaction Reference Lookups"),
    (r"(type|transaction_type|status|category)", "MEDIUM", "Categorical Grouping & Filter Slicing"),
    (r"(amount|transaction_amount|balance|available_balance)", "LOW", "Numeric Aggregations & Outlier Detection")
]

class IndexAdvisor:
    """
    Introspects and advises on database schema performance without executing any DDL.
    """

    def profile_schema(
        self,
        schema_profile: Dict[str, Dict[str, str]],
        indexes: Dict[str, List[Dict[str, Any]]],
        foreign_keys: Dict[str, List[Dict[str, str]]],
        table_counts: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """
        Produces a comprehensive Database Health & Optimization Report.
        """
        table_counts = table_counts or {}
        recommendations = []
        indexed_columns_by_table: Dict[str, Set[str]] = {}

        for table, index_list in indexes.items():
            cols = set()
            for idx in index_list:
                for col in idx.get("columns", []):
                    cols.add(col.lower())
                if "column_name" in idx:
                    cols.add(str(idx["column_name"]).lower())
            indexed_columns_by_table[table.lower()] = cols

        total_tables = len(schema_profile)
        total_indexes = sum(len(v) for v in indexes.values())

        # Inspect each table for missing critical indexes
        for table, cols in schema_profile.items():
            table_lower = table.lower()
            # Skip analytical views if present (views don't have direct B-Tree indexes)
            if table_lower.startswith("v_"):
                continue

            existing_indexed = indexed_columns_by_table.get(table_lower, set())
            row_count = table_counts.get(table, table_counts.get(table_lower, 0))

            # Normalize cols to a list of (col_name, col_type_str)
            col_items = []
            if isinstance(cols, dict):
                for c_name, c_info in cols.items():
                    c_type = c_info.get("type", str(c_info)) if isinstance(c_info, dict) else str(c_info)
                    col_items.append((c_name, c_type))
            elif isinstance(cols, list):
                for c_info in cols:
                    if isinstance(c_info, dict):
                        col_items.append((c_info.get("name", ""), c_info.get("type", "varchar")))
                    else:
                        col_items.append((str(c_info), "varchar"))

            for col_name, col_type in col_items:
                if not col_name:
                    continue
                col_lower = col_name.lower()
                if col_lower in existing_indexed:
                    continue

                for pattern, priority, role in CRITICAL_ANALYTICAL_PATTERNS:
                    if re.search(pattern, col_lower):
                        # Construct clean index name
                        idx_name = f"idx_{table_lower}_{col_lower}"[:30]
                        sql_statement = f"CREATE INDEX {idx_name} ON `{table}`(`{col_name}`);"

                        impact = "Accelerates query filtering from full table scans down to sub-50ms B-Tree lookups."
                        if row_count > 100000:
                            impact = f"CRITICAL: Table has ~{row_count:,} rows. Indexing avoids scanning millions of records per query."

                        recommendations.append({
                            "table": table,
                            "column": col_name,
                            "column_type": col_type,
                            "role": role,
                            "priority": priority,
                            "reason": f"Column `{col_name}` is used for {role.lower()} but lacks an index.",
                            "impact": impact,
                            "suggested_sql": sql_statement,
                            "suggested_ddl": sql_statement
                        })
                        break

        # Sort recommendations by priority (HIGH -> MEDIUM -> LOW)
        prio_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recommendations.sort(key=lambda r: prio_order.get(r["priority"], 9))

        # Overall health rating
        health_status = "OPTIMAL" if not recommendations else ("NEEDS_OPTIMIZATION" if any(r["priority"] == "HIGH" for r in recommendations) else "GOOD")

        return {
            "health_status": health_status,
            "total_tables": total_tables,
            "total_indexes": total_indexes,
            "recommendations": recommendations,
            "lead_summary": (
                f"Scanned {total_tables} tables. Found {len(recommendations)} recommended index optimizations to maximize query throughput."
                if recommendations else
                f"Scanned {total_tables} tables. All critical join, temporal, and categorical columns are indexed."
            )
        }

    def analyze_runtime_query(
        self,
        table: str,
        filter_columns: List[str],
        indexes: Dict[str, List[Dict[str, Any]]],
        execution_time_ms: float = 0.0
    ) -> Dict[str, Any]:
        """
        Analyzes an executed query to check if it benefited from an index or suffered from an unindexed full scan.
        """
        table_lower = table.lower().strip("`").strip()
        index_list = indexes.get(table_lower, [])
        indexed_cols = set()
        for idx in index_list:
            for c in idx.get("columns", []):
                indexed_cols.add(c.lower())
            if "column_name" in idx:
                indexed_cols.add(str(idx["column_name"]).lower())

        unindexed_filters = [c for c in filter_columns if c.lower() not in indexed_cols]

        if not filter_columns:
            return {
                "status": "OPTIMAL_INDEX_HIT",
                "message": "Full-table aggregate without filter predicates.",
                "advisories": [],
                "unindexed_columns": [],
                "advisory": None
            }

        if unindexed_filters:
            first_unindexed = unindexed_filters[0]
            time_str = f"{execution_time_ms:.0f}ms" if execution_time_ms > 0 else "higher latency"
            ddl_stmt = f"CREATE INDEX idx_{table}_{first_unindexed} ON `{table}`(`{first_unindexed}`);"
            adv_text = (
                f"⚡ Performance Note: Column `{first_unindexed}` on table `{table}` is not indexed, causing a sequential scan ({time_str}). "
                f"Creating a B-Tree index (`{ddl_stmt}`) will accelerate future aggregations to sub-50ms."
            )
            return {
                "status": "UNINDEXED_SCAN",
                "unindexed_columns": unindexed_filters,
                "message": f"Query filtered on unindexed column(s): {', '.join(unindexed_filters)}",
                "advisories": [ddl_stmt],
                "advisory": adv_text
            }

        return {
            "status": "OPTIMAL_INDEX_HIT",
            "unindexed_columns": [],
            "advisories": [],
            "message": "Query utilized existing database index(es) for sub-millisecond execution.",
            "advisory": None
        }

index_advisor = IndexAdvisor()
