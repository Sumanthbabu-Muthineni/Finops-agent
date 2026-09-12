"""
TBX FinOps Assistant - Universal Dynamic Database Engine (MySQL 8.0 Native)
High-performance connection-pooled execution engine supporting 10M-80M rows scale
with B-Tree indexed execution, zero hardcoded schemas, dynamic information_schema
introspection, foreign key relationship extraction, and sensitive data masking.
"""

import time
import re
import queue
import threading
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional, Set
import pandas as pd
from backend.config import settings
from backend.core.masking import mask_records_dataframe

class PyMySQLConnectionPool:
    """Thread-safe high-throughput connection pool for MySQL 8.0."""
    def __init__(self, host: str, port: int, user: str, password: str, db: str, minconn: int = 2, maxconn: int = 20):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.db = db
        self.maxconn = max(maxconn, minconn)
        self._pool = queue.Queue(maxsize=self.maxconn)
        self._lock = threading.Lock()
        self._created = 0

        # Eagerly initialize minimum connections
        for _ in range(minconn):
            try:
                conn = self._create_conn()
                self._pool.put_nowait(conn)
                self._created += 1
            except Exception as e:
                print(f"⚠️ Warning during initial MySQL connection creation: {e}")
                break

    def _create_conn(self):
        import pymysql
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.db,
            connect_timeout=10,
            read_timeout=120,
            write_timeout=120,
            autocommit=True
        )

    def getconn(self):
        try:
            conn = self._pool.get_nowait()
            try:
                conn.ping(reconnect=True)
            except Exception:
                conn = self._create_conn()
            return conn
        except queue.Empty:
            with self._lock:
                if self._created < self.maxconn:
                    conn = self._create_conn()
                    self._created += 1
                    return conn
            # Pool is at capacity, wait up to 15 seconds
            conn = self._pool.get(timeout=15)
            try:
                conn.ping(reconnect=True)
            except Exception:
                conn = self._create_conn()
            return conn

    def putconn(self, conn):
        if conn:
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    self._created -= 1


class DatabaseManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._init_db()
        return cls._instance

    @property
    def is_mysql(self) -> bool:
        return True

    def _init_db(self):
        self._cached_schema_profile = None
        self._cached_value_map = None
        self._cached_distinct_entities = None
        self._cached_anchor_date = None
        self._cached_max_dataset_date = None
        self._cached_foreign_keys = None
        self._cached_tables = None
        self._existing_views = None

        try:
            self.pool = PyMySQLConnectionPool(
                host=settings.MYSQL_HOST,
                port=settings.MYSQL_PORT,
                user=settings.MYSQL_USER,
                password=settings.MYSQL_PASSWORD,
                db=settings.MYSQL_DB,
                minconn=getattr(settings, "DB_POOL_MIN", 2),
                maxconn=getattr(settings, "DB_POOL_MAX", 20)
            )
            print(f"✅ Connected to MySQL Database at {settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}")
            self.reload_data()
        except Exception as e:
            print(f"⚠️ Warning: Failed to connect to MySQL at {settings.MYSQL_HOST}:{settings.MYSQL_PORT}: {e}")
            self.pool = None

    def get_connection(self):
        if self.pool is None:
            self._init_db()
        return self.pool.getconn()

    def release_connection(self, conn):
        if self.pool and conn:
            self.pool.putconn(conn)

    def reload_data(self):
        """Refreshes all in-memory dynamic schema, foreign key, and entity caches."""
        self._cached_schema_profile = None
        self._cached_value_map = None
        self._cached_distinct_entities = None
        self._cached_anchor_date = None
        self._cached_max_dataset_date = None
        self._cached_foreign_keys = None
        self._cached_tables = None
        self._existing_views = None

    def has_view(self, view_name: str) -> bool:
        """Checks if an analytical view exists in the connected MySQL database."""
        if hasattr(self, "_existing_views") and self._existing_views is not None:
            return view_name.lower() in self._existing_views

        try:
            conn = self.get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema = DATABASE();")
                self._existing_views = {str(r[0]).lower() for r in cur.fetchall()}
                cur.close()
            finally:
                self.release_connection(conn)
        except Exception:
            self._existing_views = set()

        return view_name.lower() in self._existing_views

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> Tuple[pd.DataFrame, float, int]:
        """
        Executes a parameterized or read-only SQL query on MySQL 8.0.
        Enforces universal sensitive data masking on all returned records.
        Returns (DataFrame, latency_ms, row_count).
        """
        start = time.perf_counter()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            clean_sql = query.strip()
            if clean_sql.endswith(";"):
                clean_sql = clean_sql[:-1]

            if params:
                cur.execute(clean_sql, params)
            else:
                cur.execute(clean_sql)

            if cur.description:
                columns = [str(desc[0]).lower() for desc in cur.description]
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

    def get_anchor_year(self) -> int:
        anchor = self.get_anchor_date()
        try:
            return int(anchor.split("-")[0])
        except Exception:
            return 2026

    # -------------------------------------------------------------------------
    # 1. Universal Dynamic Database Introspection (information_schema)
    # -------------------------------------------------------------------------

    def get_tables_and_views(self) -> Dict[str, str]:
        """Dynamically discovers all tables and views in the connected database schema."""
        if self._cached_tables is not None:
            return self._cached_tables

        tables = {}
        try:
            df, _, count = self.execute_query("""
                SELECT table_name, table_type 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
                ORDER BY table_type DESC, table_name ASC;
            """)
            for _, row in df.iterrows():
                t_name = str(row["table_name"]).lower()
                t_type = "VIEW" if "VIEW" in str(row["table_type"]).upper() else "BASE TABLE"
                tables[t_name] = t_type
        except Exception as e:
            print(f"Error fetching tables: {e}")

        self._cached_tables = tables
        return tables

    def get_foreign_keys(self) -> List[Dict[str, str]]:
        """Dynamically extracts Foreign Key relationships between tables."""
        if self._cached_foreign_keys is not None:
            return self._cached_foreign_keys

        fks = []
        try:
            df, _, count = self.execute_query("""
                SELECT 
                    kcu.table_name,
                    kcu.column_name,
                    kcu.referenced_table_name,
                    kcu.referenced_column_name
                FROM information_schema.key_column_usage kcu
                JOIN information_schema.table_constraints tc 
                  ON kcu.constraint_name = tc.constraint_name 
                 AND kcu.table_schema = tc.table_schema
                WHERE kcu.table_schema = DATABASE()
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.referenced_table_name IS NOT NULL;
            """)
            for _, row in df.iterrows():
                fks.append({
                    "from_table": str(row["table_name"]).lower(),
                    "from_column": str(row["column_name"]).lower(),
                    "to_table": str(row["referenced_table_name"]).lower(),
                    "to_column": str(row["referenced_column_name"]).lower()
                })
        except Exception as e:
            print(f"Error fetching foreign keys: {e}")

        self._cached_foreign_keys = fks
        return fks

    def get_schema_profile(self) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically introspects ANY database to discover all tables, columns,
        data types, key constraints, and 3-5 distinct sample values.
        Zero hardcoded table names or schemas.
        """
        if self._cached_schema_profile is not None:
            return self._cached_schema_profile

        profile: Dict[str, Dict[str, Any]] = {}
        tables = self.get_tables_and_views()

        # Step 1: Discover columns, data types, nullability, keys
        try:
            df_cols, _, _ = self.execute_query("""
                SELECT 
                    table_name, 
                    column_name, 
                    data_type, 
                    is_nullable, 
                    column_key
                FROM information_schema.columns 
                WHERE table_schema = DATABASE()
                ORDER BY table_name, ordinal_position;
            """)

            for _, row in df_cols.iterrows():
                t_name = str(row["table_name"]).lower()
                c_name = str(row["column_name"]).lower()
                d_type = str(row["data_type"]).upper()
                c_key = str(row["column_key"]).upper()

                if t_name not in profile:
                    profile[t_name] = {}

                profile[t_name][c_name] = {
                    "type": d_type,
                    "is_primary": c_key == "PRI",
                    "is_nullable": str(row["is_nullable"]).upper() == "YES"
                }
        except Exception as e:
            print(f"Error inspecting columns: {e}")

        # Step 2: Sample distinct values for categorical / text columns (3 to 5 samples)
        for t_name, cols in profile.items():
            for c_name, c_info in cols.items():
                d_type = c_info.get("type", "")
                is_text = any(t in d_type for t in ["CHAR", "TEXT", "ENUM"])
                # Exclude internal UUIDs, hashes, encrypted fields, and passwords
                is_sensitive = any(k in c_name for k in ["password", "hash", "secret", "token", "salt"])
                is_id = (c_name.endswith("_id") or c_name == "id") and not any(k in c_name for k in ["code", "type", "category"])

                if is_text and not is_sensitive and not is_id:
                    try:
                        # Use a subquery with LIMIT to prevent full table scans on 17M row tables
                        df_s, _, s_cnt = self.execute_query(f"""
                            SELECT DISTINCT `{c_name}` AS val 
                            FROM (
                                SELECT `{c_name}` FROM `{t_name}` 
                                WHERE `{c_name}` IS NOT NULL 
                                LIMIT 10000
                            ) AS subq
                            WHERE TRIM(CAST(`{c_name}` AS CHAR)) != '' 
                            LIMIT 15;
                        """)
                        vals = [str(v) for v in df_s["val"].tolist() if pd.notnull(v)]
                        if vals:
                            profile[t_name][c_name]["sample_values"] = vals
                    except Exception:
                        pass



        self._cached_schema_profile = profile
        return profile

    def get_max_dataset_date(self) -> str:
        """Dynamically finds the maximum date recorded across all discovered date columns."""
        if getattr(self, "_cached_max_dataset_date", None):
            return self._cached_max_dataset_date

        profile = self.get_schema_profile()
        max_dates = []

        for t_name, cols in profile.items():
            for c_name, c_info in cols.items():
                d_type = c_info.get("type", "")
                if any(t in d_type for t in ["DATE", "TIMESTAMP", "DATETIME"]) or "date" in c_name:
                    try:
                        # Quick lookup by sorting the table by date DESC and taking the top row.
                        # For tables with indexes, this is O(1). 
                        # To avoid full table scans on unindexed 17M tables, we use a simple subquery limit fallback
                        df, _, cnt = self.execute_query(f"""
                            SELECT DATE_FORMAT(`{c_name}`, '%Y-%m-%d') AS max_dt 
                            FROM (
                                SELECT `{c_name}` FROM `{t_name}` 
                                WHERE `{c_name}` IS NOT NULL 
                                LIMIT 1000000
                            ) AS subq
                            ORDER BY `{c_name}` DESC
                            LIMIT 1;
                        """)
                        if cnt > 0 and pd.notnull(df["max_dt"].iloc[0]):
                            val = str(df["max_dt"].iloc[0])
                            if len(val) >= 10:
                                max_dates.append(val[:10])
                    except Exception:
                        pass

        if max_dates:
            self._cached_max_dataset_date = max(max_dates)
            return self._cached_max_dataset_date

        return self.get_anchor_date()

    def get_distinct_entities(self) -> Dict[str, List[Any]]:
        """
        Dynamically extracts distinct entity values from all categorical columns.
        Provides both generic discovered entities and backward-compatible keys.
        """
        if self._cached_distinct_entities:
            return self._cached_distinct_entities

        entities: Dict[str, List[Any]] = {
            "banks": [],
            "bank_codes": [],
            "programs": [],
            "entities": [],
            "all_categorical_values": []
        }

        profile = self.get_schema_profile()
        all_vals: Set[str] = set()

        for t_name, cols in profile.items():
            for c_name, info in cols.items():
                samples = info.get("sample_values", [])
                for s in samples:
                    if len(str(s)) >= 2:
                        all_vals.add(str(s))



        # Ensure unique items
        for k in entities:
            if isinstance(entities[k], list):
                entities[k] = list(dict.fromkeys(entities[k]))

        # If banks is still empty, attempt direct query on bank table if present
        if not entities["banks"] and "bank" in profile:
            try:
                df, _, _ = self.execute_query("SELECT DISTINCT bank_name FROM bank WHERE bank_name IS NOT NULL;")
                entities["banks"] = [str(x) for x in df["bank_name"].tolist() if pd.notnull(x)]
            except Exception:
                pass

        entities["all_categorical_values"] = list(all_vals)
        self._cached_distinct_entities = entities
        return entities

    def get_value_to_column_map(self) -> Dict[str, List[Dict[str, str]]]:
        """Maps distinct categorical values to their source (table, column) for schema linking."""
        if self._cached_value_map:
            return self._cached_value_map

        profile = self.get_schema_profile()
        val_map: Dict[str, List[Dict[str, str]]] = {}

        for table_name, cols in profile.items():
            for col_name, info in cols.items():
                samples = info.get("sample_values", [])
                for val in samples:
                    val_clean = str(val).strip().lower()
                    if len(val_clean) < 2 or val_clean.startswith("****"):
                        continue
                    if val_clean not in val_map:
                        val_map[val_clean] = []
                    val_map[val_clean].append({
                        "domain": table_name,
                        "table": table_name,
                        "column": col_name,
                        "canonical": str(val).strip()
                    })

        self._cached_value_map = val_map
        return val_map

    def get_schema_prompt_context(self) -> str:
        """
        Produces a compact, highly structured DDL + sample values representation of the
        connected database for dynamic prompt injection. Zero hardcoding.
        """
        profile = self.get_schema_profile()
        tables = self.get_tables_and_views()
        fks = self.get_foreign_keys()

        lines = ["CONNECTED DATABASE SCHEMA (MySQL 8.0 Live Introspection):"]
        
        # Display each discovered table/view
        for t_name, t_type in sorted(tables.items(), key=lambda x: (x[1] != "VIEW", x[0])):
            cols = profile.get(t_name, {})
            lines.append(f"\n{t_type}: `{t_name}`")
            lines.append("  Columns:")
            for c_name, c_info in cols.items():
                d_type = c_info.get("type", "TEXT")
                pk_marker = " [PRIMARY KEY]" if c_info.get("is_primary") else ""
                samples = c_info.get("sample_values")
                sample_str = f" | Samples: {samples}" if samples else ""
                lines.append(f"    - `{c_name}` ({d_type}){pk_marker}{sample_str}")

        if fks:
            lines.append("\nForeign Key Relationships (Table Joins):")
            for fk in fks:
                lines.append(f"  - `{fk['from_table']}`.`{fk['from_column']}` -> `{fk['to_table']}`.`{fk['to_column']}`")

        return "\n".join(lines)


db = DatabaseManager()
