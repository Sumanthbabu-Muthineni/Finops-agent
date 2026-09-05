import duckdb
import time
import pandas as pd
from pathlib import Path
from typing import Tuple, List, Dict, Any
from backend.config import settings

class DatabaseManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        self.con = duckdb.connect(database=":memory:")
        self.anchor_date = time.strftime("%Y-%m-%d")
        self.reload_data()

    def reload_data(self):
        """Loads or reloads datasets from CSVs into DuckDB and builds analytical views."""
        self._cached_schema_profile = None
        self._cached_value_map = None
        data_path = settings.data_path

        # Verify files exist
        required_files = [
            "bank.csv",
            "account.csv",
            "transaction.csv"
        ]
        for f in required_files:
            file_path = data_path / f
            if not file_path.exists():
                raise FileNotFoundError(f"Required dataset missing: {file_path}")

        # Load base tables directly via DuckDB C++ CSV parser
        self.con.execute(f"""
            CREATE OR REPLACE TABLE bank AS 
            SELECT * FROM read_csv_auto('{data_path / "bank.csv"}', header=True);
        """)

        self.con.execute(f"""
            CREATE OR REPLACE TABLE account AS 
            SELECT * FROM read_csv_auto('{data_path / "account.csv"}', header=True);
        """)

        self.con.execute(f"""
            CREATE OR REPLACE TABLE transaction AS 
            SELECT * FROM read_csv_auto('{data_path / "transaction.csv"}', header=True);
        """)

        # Build Pre-Joined Semantic Views
        # View 1: v_transactions (Transactional details with sensitive data masked)
        self.con.execute("""
            CREATE OR REPLACE VIEW v_transactions AS
            SELECT 
                t.transaction_id,
                t.account_id,
                a.entity_id,
                CONCAT('****', SUBSTRING(CAST(a.account_number AS VARCHAR), -4)) AS masked_account_number,
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
                CASE 
                    WHEN t.utr_number IS NOT NULL AND LENGTH(CAST(t.utr_number AS VARCHAR)) > 8 
                    THEN CONCAT(SUBSTRING(CAST(t.utr_number AS VARCHAR), 1, 8), '...') 
                    ELSE CAST(t.utr_number AS VARCHAR) 
                END AS masked_utr_number,
                a.available_balance,
                EXTRACT(YEAR FROM CAST(t.transaction_date AS DATE)) AS txn_year,
                EXTRACT(MONTH FROM CAST(t.transaction_date AS DATE)) AS txn_month
            FROM transaction t
            JOIN account a ON t.account_id = a.account_id
            JOIN bank b ON a.bank_code = b.bank_code;
        """)

        # View 2: v_accounts (Ledger accounts with sensitive masking)
        self.con.execute("""
            CREATE OR REPLACE VIEW v_accounts AS
            SELECT 
                a.account_id,
                a.entity_id,
                CONCAT('****', SUBSTRING(CAST(a.account_number AS VARCHAR), -4)) AS masked_account_number,
                b.bank_code,
                b.bank_name,
                a.program_id,
                a.available_balance,
                a.available_balance AS balance
            FROM account a
            JOIN bank b ON a.bank_code = b.bank_code;
        """)

        # View 3: v_banks (High-level aggregation per bank)
        self.con.execute("""
            CREATE OR REPLACE VIEW v_banks AS
            SELECT 
                b.bank_code,
                b.bank_name,
                COUNT(a.account_id) AS account_count,
                ROUND(COALESCE(SUM(a.available_balance), 0.0), 2) AS total_available_balance
            FROM bank b
            LEFT JOIN account a ON b.bank_code = a.bank_code
            GROUP BY b.bank_code, b.bank_name;
        """)

        # Derive anchor date dynamically from MAX(transaction_date)
        try:
            res = self.con.execute("SELECT CAST(MAX(transaction_date) AS VARCHAR) FROM transaction WHERE transaction_date IS NOT NULL;").fetchone()
            if res and res[0]:
                self.anchor_date = str(res[0]).split()[0]
            else:
                self.anchor_date = time.strftime("%Y-%m-%d")
        except Exception:
            self.anchor_date = time.strftime("%Y-%m-%d")

    def get_anchor_date(self) -> str:
        return self.anchor_date

    def get_anchor_year(self) -> str:
        return self.anchor_date.split("-")[0]

    def get_distinct_entities(self) -> Dict[str, List[str]]:
        """Extracts distinct bank names, bank codes, and entity IDs for fuzzy indexer."""
        banks = [r[0] for r in self.con.execute("SELECT DISTINCT bank_name FROM bank WHERE bank_name IS NOT NULL;").fetchall()]
        bank_codes = [r[0] for r in self.con.execute("SELECT DISTINCT bank_code FROM bank WHERE bank_code IS NOT NULL;").fetchall()]
        entities = [r[0] for r in self.con.execute("SELECT DISTINCT entity_id FROM account WHERE entity_id IS NOT NULL;").fetchall()]
        programs = [str(r[0]) for r in self.con.execute("SELECT DISTINCT program_id FROM account WHERE program_id IS NOT NULL;").fetchall()]
        return {
            "banks": banks,
            "bank_codes": bank_codes,
            "entities": entities,
            "programs": programs,
            "transaction_types": ["credit", "debit"],
            # Alias for backward-compatible resolver queries
            "vendors": banks
        }

    def get_schema_profile(self) -> Dict[str, Any]:
        """
        Dynamically introspects all analytical views in DuckDB.
        Discovers:
        - View names and column names
        - Column data types
        - Sample distinct values for categorical/text columns (cardinality <= 30)
        Zero hardcoded column names or enums.
        """
        if hasattr(self, "_cached_schema_profile") and self._cached_schema_profile:
            return self._cached_schema_profile

        views = {
            "transactions": "v_transactions",
            "accounts": "v_accounts",
            "banks": "v_banks"
        }
        profile = {}
        for domain, view in views.items():
            try:
                cols_info = self.con.execute(f"PRAGMA table_info('{view}')").fetchall()
                domain_columns = {}
                for row in cols_info:
                    col_name = row[1]
                    col_type = str(row[2]).upper()
                    if col_name.endswith(("_year", "_month")):
                        continue

                    col_meta: Dict[str, Any] = {"type": col_type}
                    if any(t in col_type for t in ["VARCHAR", "TEXT", "CHAR"]):
                        if not any(k in col_name for k in ["_id", "description", "reference", "utr", "notes"]):
                            distinct_rows = self.con.execute(
                                f"SELECT DISTINCT {col_name} FROM {view} WHERE {col_name} IS NOT NULL LIMIT 30;"
                            ).fetchall()
                            values = [r[0] for r in distinct_rows if r[0] is not None]
                            if len(values) <= 30:
                                col_meta["sample_values"] = values
                    domain_columns[col_name] = col_meta
                profile[domain] = domain_columns
            except Exception:
                pass

        self._cached_schema_profile = profile
        return profile

    def get_value_to_column_map(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Dynamically builds an inverted index mapping lowercased values to their (domain, column, canonical_value).
        Used by LLM layer and MockLLMClient for zero-hardcoded entity-column mapping.
        """
        if hasattr(self, "_cached_value_map") and self._cached_value_map:
            return self._cached_value_map

        profile = self.get_schema_profile()
        val_map: Dict[str, List[Dict[str, str]]] = {}
        for domain, cols in profile.items():
            for col_name, meta in cols.items():
                for sample_val in meta.get("sample_values", []):
                    s_str = str(sample_val).strip()
                    if not s_str or len(s_str) < 2:
                        continue
                    s_lower = s_str.lower()
                    if s_lower not in val_map:
                        val_map[s_lower] = []
                    val_map[s_lower].append({
                        "domain": domain,
                        "column": col_name,
                        "canonical": s_str
                    })

        self._cached_value_map = val_map
        return val_map

    def get_schema_structure(self) -> Dict[str, List[str]]:
        """Dynamically returns view names and their available column names directly from DuckDB."""
        profile = self.get_schema_profile()
        return {domain: list(cols.keys()) for domain, cols in profile.items()}

    def execute_query(self, sql: str) -> Tuple[pd.DataFrame, float, int]:
        """Executes a SQL query and returns (DataFrame, latency_ms, row_count)."""
        start_time = time.perf_counter()
        df = self.con.execute(sql).fetchdf()
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return df, latency_ms, len(df)

# Global database singleton
db = DatabaseManager()
