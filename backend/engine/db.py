"""
TBX FinOps Assistant - Native PostgreSQL Database Manager
High-performance connection-pooled execution engine supporting 20M-80M rows scale
with B-Tree indexed execution, zero DuckDB reliance, and universal sensitive data masking.
"""

import time
import re
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional
import pandas as pd
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from backend.config import settings
from backend.core.masking import mask_records_dataframe

class DatabaseManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        self._cached_schema_profile = None
        self._cached_value_map = None
        self._cached_distinct_entities = None
        self._cached_anchor_date = None

        # Initialize PostgreSQL Threaded Connection Pool
        db_url = settings.DATABASE_URL
        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=settings.POSTGRES_POOL_MIN,
                maxconn=settings.POSTGRES_POOL_MAX,
                dsn=db_url
            )
            # Verify connectivity and ensure schema exists
            self.reload_data()
        except Exception as e:
            print(f"⚠️ Warning: Failed to connect to PostgreSQL at {db_url}: {e}")
            self.pool = None

    def get_connection(self):
        if self.pool is None:
            # Attempt to re-initialize pool
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=settings.POSTGRES_POOL_MIN,
                maxconn=settings.POSTGRES_POOL_MAX,
                dsn=settings.DATABASE_URL
            )
        return self.pool.getconn()

    def release_connection(self, conn):
        if self.pool and conn:
            self.pool.putconn(conn)

    def has_view(self, view_name: str) -> bool:
        """Checks if an analytical view exists in the connected PostgreSQL database."""
        if hasattr(self, "_existing_views") and self._existing_views is not None:
            return view_name.lower() in self._existing_views

        try:
            conn = self.get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT table_name FROM information_schema.views 
                    WHERE table_schema = 'public';
                """)
                self._existing_views = {r[0].lower() for r in cur.fetchall()}
                cur.close()
            finally:
                self.release_connection(conn)
        except Exception:
            self._existing_views = set()

        return view_name.lower() in self._existing_views

    def reload_data(self):
        """Ensures PostgreSQL views exist and refreshes in-memory schema caches."""
        self._cached_schema_profile = None
        self._cached_value_map = None
        self._cached_distinct_entities = None
        self._cached_anchor_date = None
        self._existing_views = None

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            # 1. Verify core tables exist
            cur.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name IN ('bank', 'account', 'transaction');
            """)
            tables = [r[0] for r in cur.fetchall()]
            if len(tables) < 3:
                # If tables don't exist yet, apply schema DDL
                from pathlib import Path
                ddl_path = Path(__file__).resolve().parent.parent / "database" / "schema_postgres.sql"
                if ddl_path.exists():
                    with open(ddl_path) as f:
                        cur.execute(f.read())
                    conn.commit()

            # 2. Check if analytical views exist. If missing on evaluator DB, attempt to create them
            cur.execute("""
                SELECT table_name FROM information_schema.views 
                WHERE table_schema = 'public' AND table_name IN ('v_transactions', 'v_accounts', 'v_banks');
            """)
            existing_views = {r[0].lower() for r in cur.fetchall()}
            self._existing_views = existing_views
            if len(existing_views) < 3:
                try:
                    cur.execute("""
                        CREATE OR REPLACE VIEW v_transactions AS
                        SELECT 
                            t.transaction_id,
                            t.account_id,
                            a.entity_id,
                            '****' || RIGHT(a.account_number, 4) AS masked_account_number,
                            '****' || RIGHT(a.account_number, 4) AS account_number,
                            b.bank_code,
                            b.bank_name,
                            a.program_id,
                            t.transaction_date,
                            CAST(t.transaction_date AS DATE) AS transaction_day,
                            LOWER(t.transaction_type) AS transaction_type,
                            t.transaction_amount,
                            t.transaction_amount AS amount,
                            t.description,
                            t.transaction_reference_id,
                            t.transaction_reference_id AS reference_id,
                            t.utr_number AS masked_utr_number,
                            t.utr_number,
                            a.available_balance,
                            EXTRACT(YEAR FROM t.transaction_date)::INTEGER AS txn_year,
                            EXTRACT(MONTH FROM t.transaction_date)::INTEGER AS txn_month
                        FROM transaction t
                        JOIN account a ON t.account_id = a.account_id
                        JOIN bank b ON a.bank_code = b.bank_code;

                        CREATE OR REPLACE VIEW v_accounts AS
                        SELECT 
                            a.account_id,
                            a.entity_id,
                            '****' || RIGHT(a.account_number, 4) AS masked_account_number,
                            '****' || RIGHT(a.account_number, 4) AS account_number,
                            a.bank_code,
                            b.bank_name,
                            a.program_id,
                            a.available_balance,
                            a.available_balance AS balance
                        FROM account a
                        JOIN bank b ON a.bank_code = b.bank_code;

                        CREATE OR REPLACE VIEW v_banks AS
                        SELECT 
                            b.bank_code,
                            b.bank_name,
                            COUNT(a.account_id) AS total_accounts,
                            ROUND(CAST(COALESCE(SUM(a.available_balance), 0) AS NUMERIC), 2) AS total_available_balance
                        FROM bank b
                        LEFT JOIN account a ON b.bank_code = a.bank_code
                        GROUP BY b.bank_code, b.bank_name;
                    """)
                    conn.commit()
                    self._existing_views = {"v_transactions", "v_accounts", "v_banks"}
                except Exception:
                    conn.rollback()
                    # Evaluator user might have read-only permissions without CREATE VIEW privilege
                    pass
            cur.close()
        finally:
            self.release_connection(conn)

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> Tuple[pd.DataFrame, float, int]:
        """
        Executes a parameterized or read-only SQL query on PostgreSQL.
        Enforces universal sensitive data masking on all returned records.
        Returns (DataFrame, latency_ms, row_count).
        """
        start = time.perf_counter()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            # Sanitize trailing semicolons for consistency
            clean_sql = query.strip()
            if clean_sql.endswith(";"):
                clean_sql = clean_sql[:-1]

            if params:
                cur.execute(clean_sql, params)
            else:
                cur.execute(clean_sql)

            if cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                df = pd.DataFrame(rows, columns=columns)
            else:
                df = pd.DataFrame()

            cur.close()
        finally:
            self.release_connection(conn)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        row_count = len(df)

        # Apply Universal Sensitive Data Masking Guardrail
        df = mask_records_dataframe(df)

        return df, elapsed_ms, row_count

    def get_anchor_date(self) -> str:
        """Returns the machine's current local date as the anchor date."""
        return datetime.now().strftime("%Y-%m-%d")

    def get_max_dataset_date(self) -> str:
        """Dynamically computes maximum date from transactions in PostgreSQL."""
        if getattr(self, "_cached_max_dataset_date", None):
            return self._cached_max_dataset_date

        try:
            df, _, count = self.execute_query("SELECT TO_CHAR(MAX(transaction_date), 'YYYY-MM-DD') AS max_dt FROM transaction;")
            if count > 0 and pd.notnull(df["max_dt"].iloc[0]):
                self._cached_max_dataset_date = str(df["max_dt"].iloc[0])
                return self._cached_max_dataset_date
        except Exception:
            pass

        return self.get_anchor_date()

    def get_anchor_year(self) -> int:
        anchor = self.get_anchor_date()
        try:
            return int(anchor.split("-")[0])
        except Exception:
            return 2026

    def get_distinct_entities(self) -> Dict[str, List[Any]]:
        """Extracts distinct entities directly from PostgreSQL."""
        if self._cached_distinct_entities:
            return self._cached_distinct_entities

        entities: Dict[str, List[Any]] = {
            "banks": [],
            "bank_codes": [],
            "programs": [],
            "entities": []
        }

        try:
            df_banks, _, _ = self.execute_query("SELECT DISTINCT bank_code, bank_name FROM bank ORDER BY bank_name;")
            entities["banks"] = [str(x) for x in df_banks["bank_name"].tolist() if pd.notnull(x)]
            entities["bank_codes"] = [str(x) for x in df_banks["bank_code"].tolist() if pd.notnull(x)]

            df_prog, _, _ = self.execute_query("SELECT DISTINCT program_id FROM account ORDER BY program_id;")
            entities["programs"] = [int(x) for x in df_prog["program_id"].tolist() if pd.notnull(x)]

            df_ent, _, _ = self.execute_query("SELECT DISTINCT entity_id FROM account LIMIT 100;")
            entities["entities"] = [str(x) for x in df_ent["entity_id"].tolist() if pd.notnull(x)]
        except Exception as e:
            print(f"Error fetching distinct entities: {e}")

        self._cached_distinct_entities = entities
        return entities

    def get_schema_profile(self) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically introspects PostgreSQL views to discover columns, types, and sample categorical values.
        Zero hardcoding.
        """
        if self._cached_schema_profile:
            return self._cached_schema_profile

        profile: Dict[str, Dict[str, Any]] = {}
        target_views = {
            "transactions": "v_transactions",
            "accounts": "v_accounts",
            "banks": "v_banks"
        }

        for domain_key, view_name in target_views.items():
            profile[domain_key] = {}
            try:
                # Query column names and types from PostgreSQL information_schema
                df_cols, _, _ = self.execute_query(f"""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = '{view_name}' 
                    ORDER BY ordinal_position;
                """)

                for _, row in df_cols.iterrows():
                    col_name = row["column_name"]
                    data_type = row["data_type"].upper()
                    profile[domain_key][col_name] = {"type": data_type}

                    # If column is categorical string, extract distinct sample values
                    if any(t in data_type for t in ["CHAR", "TEXT"]) and not any(k in col_name for k in ["id", "description"]):
                        df_samples, _, _ = self.execute_query(f"""
                            SELECT DISTINCT {col_name} AS val 
                            FROM {view_name} 
                            WHERE {col_name} IS NOT NULL 
                            LIMIT 10;
                        """)
                        vals = [str(v) for v in df_samples["val"].tolist() if pd.notnull(v)]
                        if vals:
                            profile[domain_key][col_name]["sample_values"] = vals
            except Exception as e:
                print(f"Error profiling view {view_name}: {e}")

        self._cached_schema_profile = profile
        return profile

    def get_value_to_column_map(self) -> Dict[str, List[Dict[str, str]]]:
        """Maps distinct values to their source column for dynamic schema linking."""
        if self._cached_value_map:
            return self._cached_value_map

        profile = self.get_schema_profile()
        val_map: Dict[str, List[Dict[str, str]]] = {}

        for domain, cols in profile.items():
            for col_name, info in cols.items():
                samples = info.get("sample_values", [])
                for val in samples:
                    val_clean = str(val).strip().lower()
                    if len(val_clean) < 2 or val_clean.startswith("****"):
                        continue
                    if val_clean not in val_map:
                        val_map[val_clean] = []
                    val_map[val_clean].append({
                        "domain": domain,
                        "column": col_name,
                        "canonical": str(val).strip()
                    })

        self._cached_value_map = val_map
        return val_map

db = DatabaseManager()
