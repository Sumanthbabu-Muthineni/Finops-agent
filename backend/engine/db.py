"""
TBX FinOps Assistant - Multi-Tenant Relational Database Engine (MySQL 8.0 Native)
Provides thread-safe connection pooling, session-scoped tenant isolation (BYODB),
zero-DDL index and schema introspection, and read-only enforcement.
"""

import time
import os
import queue
import threading
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime
import pandas as pd
import pymysql

from backend.config import settings
from backend.core.masking import mask_records_dataframe

class PyMySQLConnectionPool:
    """Thread-safe high-throughput connection pool for MySQL 8.0."""
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        db: str,
        minconn: int = 2,
        maxconn: int = 20,
        read_only: bool = False,
        use_ssl: bool = False
    ):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.db = db
        self.read_only = read_only
        self.use_ssl = use_ssl
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
                print(f"⚠️ Warning during initial MySQL connection creation ({self.host}:{self.port}/{self.db}): {e}")
                break

    def _create_conn(self):
        ssl_config = {"ssl": {"ssl_mode": "REQUIRED"}} if self.use_ssl else None
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.db,
            connect_timeout=10,
            read_timeout=120,
            write_timeout=120,
            autocommit=True,
            **(ssl_config if ssl_config else {})
        )
        if self.read_only:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY;")
            except Exception:
                pass
        return conn

    def getconn(self):
        try:
            conn = self._pool.get_nowait()
            try:
                conn.ping()
            except Exception:
                conn = self._create_conn()
            return conn
        except queue.Empty:
            with self._lock:
                if self._created < self.maxconn:
                    self._created += 1
                    return self._create_conn()
            return self._pool.get(timeout=10.0)

    def putconn(self, conn):
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created -= 1

    def close_all(self):
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._created = 0


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
        # Default system database pool (Demo database)
        self.default_pool = None
        self._tenant_pools: Dict[str, PyMySQLConnectionPool] = {}
        self._tenant_configs: Dict[str, Dict[str, Any]] = {}
        self._tenant_advisors: Dict[str, Dict[str, Any]] = {}

        # Session-aware caches
        self._cached_schema_profiles: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._cached_indexes_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        self._cached_foreign_keys_map: Dict[str, List[Dict[str, str]]] = {}
        self._cached_tables_map: Dict[str, Dict[str, str]] = {}
        self._cached_distinct_entities_map: Dict[str, Dict[str, List[Any]]] = {}
        self._cached_value_maps: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        self._cached_max_dates: Dict[str, str] = {}
        self._existing_views_map: Dict[str, Set[str]] = {}

        try:
            self.default_pool = PyMySQLConnectionPool(
                host=settings.MYSQL_HOST,
                port=settings.MYSQL_PORT,
                user=settings.MYSQL_USER,
                password=settings.MYSQL_PASSWORD,
                db=settings.MYSQL_DB,
                minconn=getattr(settings, "DB_POOL_MIN", 2),
                maxconn=getattr(settings, "DB_POOL_MAX", 20)
            )
            print(f"✅ Connected to Default MySQL Database at {settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}")
            self.reload_data()
        except Exception as e:
            print(f"⚠️ Warning: Failed to connect to default MySQL at {settings.MYSQL_HOST}:{settings.MYSQL_PORT}: {e}")
            self.default_pool = None

    def is_custom_database(self, session_id: Optional[str] = None) -> bool:
        """Returns True if the session is currently connected to a customer database."""
        return bool(session_id and session_id in self._tenant_pools)

    def get_active_db_info(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns metadata about the active database connection for this session."""
        if self.is_custom_database(session_id):
            cfg = self._tenant_configs.get(session_id, {})
            return {
                "mode": "custom",
                "database": cfg.get("database", "custom_db"),
                "host": cfg.get("host", "unknown"),
                "port": cfg.get("port", 3306),
                "db_type": cfg.get("db_type", "mysql")
            }
        return {
            "mode": "default",
            "database": settings.MYSQL_DB or "tiby_hackathon",
            "host": settings.MYSQL_HOST or "localhost",
            "port": settings.MYSQL_PORT or 3306,
            "db_type": "mysql"
        }

    def connect_tenant_database(self, session_id: str, db_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Connects a customer database for the given session.
        Enforces read-only transactions and generates an onboarding optimization report.
        """
        host = str(db_config.get("host", "")).strip()
        port = int(db_config.get("port", 3306))
        user = str(db_config.get("username") or db_config.get("user") or "").strip()
        password = str(db_config.get("password", ""))
        database = str(db_config.get("database", "")).strip()
        db_type = str(db_config.get("db_type", "mysql")).lower()
        use_ssl = bool(db_config.get("ssl", False))

        if not host:
            raise ValueError("Database host address is required.")
        if not database:
            raise ValueError("Database name is required.")
        if not user:
            raise ValueError("Database username is required.")

        ssl_config = {"ssl": {"ssl_mode": "REQUIRED"}} if use_ssl else None

        # 1. Pre-flight connectivity check with strict 6s timeout
        try:
            test_conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=6,
                read_timeout=10,
                write_timeout=10,
                autocommit=True,
                **(ssl_config if ssl_config else {})
            )
            # Verify read-only enforcement
            try:
                with test_conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY;")
            except Exception:
                pass
            test_conn.close()
        except pymysql.err.OperationalError as e:
            code, msg = e.args if len(e.args) >= 2 else (0, str(e))
            if code == 1045:
                raise ValueError(f"Authentication Failed (1045): Access denied for user '{user}'. Please verify your username and password.") from e
            elif code == 1049:
                raise ValueError(f"Database Not Found (1049): Unknown database '{database}'. Please verify the database exists on host '{host}'.") from e
            elif code in (2003, 2005):
                raise ValueError(f"Host Unreachable ({code}): Could not resolve or connect to '{host}' on port {port}. Please check the hostname and ensure firewall / AWS security group rules allow traffic.") from e
            elif "timed out" in str(msg).lower():
                raise ValueError(f"Connection Timed Out: Connection to {host}:{port} timed out after 6 seconds. Please verify network routing and firewall rules.") from e
            else:
                raise ValueError(f"MySQL Connection Error ({code}): {msg}") from e
        except Exception as e:
            raise ValueError(f"Failed to connect to database at {host}:{port}: {e}") from e

        # 2. Close previous tenant connection if one existed for this session
        if session_id in self._tenant_pools:
            try:
                self._tenant_pools[session_id].close_all()
            except Exception:
                pass

        # 3. Create isolated tenant pool with read-only enforcement
        tenant_pool = PyMySQLConnectionPool(
            host=host,
            port=port,
            user=user,
            password=password,
            db=database,
            minconn=1,
            maxconn=5,
            read_only=True,
            use_ssl=use_ssl
        )

        self._tenant_pools[session_id] = tenant_pool
        self._tenant_configs[session_id] = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "db_type": db_type,
            "ssl": use_ssl,
            "connected_at": time.time()
        }

        # 4. Clear and rebuild session metadata
        self.reload_data(session_id)
        schema_prof = self.get_schema_profile(session_id)
        indexes = self.get_indexes(session_id)
        fks = self.get_foreign_keys(session_id)
        row_counts = self.get_table_row_counts(session_id)

        # 5. Run Database Profiler & Index Advisor
        from backend.engine.index_advisor import index_advisor
        advisor_report = index_advisor.profile_schema(schema_prof, indexes, fks, row_counts)
        self._tenant_advisors[session_id] = advisor_report

        total_rows = sum(row_counts.values())

        return {
            "status": "connected",
            "session_id": session_id,
            "database": database,
            "host": host,
            "port": port,
            "tables_count": len(schema_prof),
            "tables": list(schema_prof.keys()),
            "total_rows": total_rows,
            "advisor_report": advisor_report
        }

    def disconnect_tenant_database(self, session_id: str) -> bool:
        """Disconnects customer database and seamlessly reverts session to default demo database."""
        if session_id in self._tenant_pools:
            try:
                self._tenant_pools[session_id].close_all()
            except Exception:
                pass
            del self._tenant_pools[session_id]

        self._tenant_configs.pop(session_id, None)
        self._tenant_advisors.pop(session_id, None)
        self._clear_session_caches(session_id)
        return True

    def get_tenant_advisor_report(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves the proactive index optimization advice for the connected database."""
        if session_id and session_id in self._tenant_advisors:
            return self._tenant_advisors[session_id]

        # If on default database, generate for default
        schema_prof = self.get_schema_profile()
        indexes = self.get_indexes()
        fks = self.get_foreign_keys()
        row_counts = self.get_table_row_counts()
        from backend.engine.index_advisor import index_advisor
        return index_advisor.profile_schema(schema_prof, indexes, fks, row_counts)

    def _clear_session_caches(self, session_id: str):
        self._cached_schema_profiles.pop(session_id, None)
        self._cached_indexes_map.pop(session_id, None)
        self._cached_foreign_keys_map.pop(session_id, None)
        self._cached_tables_map.pop(session_id, None)
        self._cached_distinct_entities_map.pop(session_id, None)
        self._cached_value_maps.pop(session_id, None)
        self._cached_max_dates.pop(session_id, None)
        self._existing_views_map.pop(session_id, None)

    def _resolve_pool(self, session_id: Optional[str] = None) -> PyMySQLConnectionPool:
        if session_id and session_id in self._tenant_pools:
            return self._tenant_pools[session_id]
        if self.default_pool is None:
            self._init_db()
        if self.default_pool is None:
            raise RuntimeError("Database connection pool is uninitialized.")
        return self.default_pool

    def get_connection(self, session_id: Optional[str] = None):
        pool = self._resolve_pool(session_id)
        return pool.getconn()

    def release_connection(self, conn, session_id: Optional[str] = None):
        pool = self._resolve_pool(session_id)
        pool.putconn(conn)

    def reload_data(self, session_id: Optional[str] = None):
        """Refreshes in-memory dynamic schema, index, foreign key, and entity caches."""
        key = session_id or "__default__"
        self._cached_schema_profiles.pop(key, None)
        self._cached_indexes_map.pop(key, None)
        self._cached_foreign_keys_map.pop(key, None)
        self._cached_tables_map.pop(key, None)
        self._cached_distinct_entities_map.pop(key, None)
        self._cached_value_maps.pop(key, None)
        self._cached_max_dates.pop(key, None)
        self._existing_views_map.pop(key, None)

    def has_view(self, view_name: str, session_id: Optional[str] = None) -> bool:
        """Checks if an analytical view exists in the target database."""
        key = session_id or "__default__"
        if key not in self._existing_views_map:
            try:
                conn = self.get_connection(session_id)
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema = DATABASE();")
                    self._existing_views_map[key] = {str(r[0]).lower() for r in cur.fetchall()}
                    cur.close()
                finally:
                    self.release_connection(conn, session_id)
            except Exception:
                self._existing_views_map[key] = set()

        return view_name.lower() in self._existing_views_map.get(key, set())

    def execute_query(
        self,
        query: str,
        params: Optional[Tuple] = None,
        session_id: Optional[str] = None
    ) -> Tuple[pd.DataFrame, float, int]:
        """
        Executes a read-only SQL query on the resolved database (Default or Customer Tenant).
        Enforces universal sensitive data masking on all returned records.
        Returns (DataFrame, latency_ms, row_count).
        """
        start = time.perf_counter()
        conn = self.get_connection(session_id)
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
            self.release_connection(conn, session_id)

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
    # 1. Zero-DDL Dynamic Introspection (information_schema)
    # -------------------------------------------------------------------------

    def get_tables_and_views(self, session_id: Optional[str] = None) -> Dict[str, str]:
        """Dynamically discovers all tables and views in the connected database schema."""
        key = session_id or "__default__"
        if key in self._cached_tables_map:
            return self._cached_tables_map[key]

        tables = {}
        try:
            df, _, count = self.execute_query("""
                SELECT table_name, table_type 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
                ORDER BY table_type DESC, table_name ASC;
            """, session_id=session_id)
            for _, row in df.iterrows():
                t_name = str(row["table_name"]).lower()
                t_type = "VIEW" if "VIEW" in str(row["table_type"]).upper() else "BASE TABLE"
                tables[t_name] = t_type
        except Exception as e:
            print(f"Error fetching tables: {e}")

        self._cached_tables_map[key] = tables
        return tables

    def get_indexes(self, session_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Introspects existing B-Tree indexes from information_schema.statistics without running any DDL."""
        key = session_id or "__default__"
        if key in self._cached_indexes_map:
            return self._cached_indexes_map[key]

        indexes_by_table: Dict[str, Dict[str, Dict[str, Any]]] = {}
        try:
            query = """
                SELECT table_name, index_name, column_name, seq_in_index, non_unique, index_type
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                ORDER BY table_name, index_name, seq_in_index;
            """
            df, _, count = self.execute_query(query, session_id=session_id)
            for _, row in df.iterrows():
                tbl = str(row["table_name"]).lower()
                idx_name = str(row["index_name"])
                col_name = str(row["column_name"])
                is_unique = (int(row["non_unique"]) == 0)
                idx_type = str(row["index_type"])

                if tbl not in indexes_by_table:
                    indexes_by_table[tbl] = {}
                if idx_name not in indexes_by_table[tbl]:
                    indexes_by_table[tbl][idx_name] = {
                        "name": idx_name,
                        "columns": [],
                        "is_unique": is_unique,
                        "type": idx_type
                    }
                indexes_by_table[tbl][idx_name]["columns"].append(col_name)

            final_indexes = {
                tbl: list(idx_dict.values())
                for tbl, idx_dict in indexes_by_table.items()
            }
            self._cached_indexes_map[key] = final_indexes
            return final_indexes
        except Exception as e:
            return {}

    def get_table_row_counts(self, session_id: Optional[str] = None) -> Dict[str, int]:
        """Reads approximate table row counts from information_schema without running full COUNT(*) scans."""
        try:
            query = """
                SELECT table_name, table_rows 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE();
            """
            df, _, _ = self.execute_query(query, session_id=session_id)
            return {str(r["table_name"]).lower(): int(r["table_rows"] or 0) for _, r in df.iterrows()}
        except Exception:
            return {}

    def get_foreign_keys(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Dynamically extracts Foreign Key relationships between tables."""
        key = session_id or "__default__"
        if key in self._cached_foreign_keys_map:
            return self._cached_foreign_keys_map[key]

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
            """, session_id=session_id)
            for _, row in df.iterrows():
                fks.append({
                    "from_table": str(row["table_name"]).lower(),
                    "from_column": str(row["column_name"]).lower(),
                    "to_table": str(row["referenced_table_name"]).lower(),
                    "to_column": str(row["referenced_column_name"]).lower()
                })
        except Exception as e:
            print(f"Error fetching foreign keys: {e}")

        self._cached_foreign_keys_map[key] = fks
        return fks

    def get_schema_profile(self, session_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically introspects the database to discover all tables, columns,
        data types, key constraints, and 3-5 distinct sample values.
        Zero hardcoded table names or schemas.
        """
        key = session_id or "__default__"
        if key in self._cached_schema_profiles:
            return self._cached_schema_profiles[key]

        profile: Dict[str, Dict[str, Any]] = {}
        tables = self.get_tables_and_views(session_id)

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
            """, session_id=session_id)

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

        # Step 2: Sample distinct values for categorical / text columns
        for t_name, cols in profile.items():
            for c_name, c_info in cols.items():
                d_type = c_info.get("type", "")
                is_text = any(t in d_type for t in ["CHAR", "TEXT", "ENUM"])
                is_sensitive = any(k in c_name for k in ["password", "hash", "secret", "token", "salt"])
                is_id = (c_name.endswith("_id") or c_name == "id") and not any(k in c_name for k in ["code", "type", "category"])

                if is_text and not is_sensitive and not is_id:
                    try:
                        df_s, _, s_cnt = self.execute_query(f"""
                            SELECT DISTINCT `{c_name}` AS val 
                            FROM (
                                SELECT `{c_name}` FROM `{t_name}` 
                                WHERE `{c_name}` IS NOT NULL 
                                LIMIT 10000
                            ) AS subq
                            WHERE TRIM(CAST(`{c_name}` AS CHAR)) != '' 
                            LIMIT 15;
                        """, session_id=session_id)
                        vals = [str(v) for v in df_s["val"].tolist() if pd.notnull(v)]
                        if vals:
                            profile[t_name][c_name]["sample_values"] = vals
                    except Exception:
                        pass

        self._cached_schema_profiles[key] = profile
        return profile

    def get_schema_prompt_context(self, session_id: Optional[str] = None) -> str:
        """Generates a concise, formatted schema summary for LLM prompt injection."""
        profile = self.get_schema_profile(session_id)
        lines = ["CURRENT DATABASE SCHEMA & DOMAIN PROFILE:"]
        for table, cols in profile.items():
            lines.append(f"\nTable/View: `{table}`")
            lines.append("Columns:")
            for col, info in cols.items():
                col_type = info.get("type", "UNKNOWN") if isinstance(info, dict) else str(info)
                samples = info.get("sample_values", []) if isinstance(info, dict) else []
                sample_str = f" | Sample Values: {samples[:5]}" if samples else ""
                lines.append(f"  - `{col}` ({col_type}){sample_str}")
        return "\n".join(lines)

    def get_max_dataset_date(self, session_id: Optional[str] = None) -> str:
        """Dynamically finds the maximum date recorded across all discovered date columns."""
        key = session_id or "__default__"
        if key in self._cached_max_dates:
            return self._cached_max_dates[key]

        profile = self.get_schema_profile(session_id)
        max_dates = []

        for t_name, cols in profile.items():
            for c_name, c_info in cols.items():
                d_type = c_info.get("type", "")
                if any(t in d_type for t in ["DATE", "TIMESTAMP", "DATETIME"]) or "date" in c_name:
                    try:
                        df, _, cnt = self.execute_query(f"""
                            SELECT DATE_FORMAT(`{c_name}`, '%Y-%m-%d') AS max_dt 
                            FROM (
                                SELECT `{c_name}` FROM `{t_name}` 
                                WHERE `{c_name}` IS NOT NULL 
                                LIMIT 500000
                            ) AS subq
                            ORDER BY `{c_name}` DESC
                            LIMIT 1;
                        """, session_id=session_id)
                        if cnt > 0 and pd.notnull(df["max_dt"].iloc[0]):
                            val = str(df["max_dt"].iloc[0])
                            if len(val) >= 10:
                                max_dates.append(val[:10])
                    except Exception:
                        pass

        if max_dates:
            self._cached_max_dates[key] = max(max_dates)
            return self._cached_max_dates[key]

        return self.get_anchor_date()

    def get_distinct_entities(self, session_id: Optional[str] = None) -> Dict[str, List[Any]]:
        """
        Dynamically extracts distinct entity values from all categorical columns.
        Provides both generic discovered entities and backward-compatible keys.
        """
        key = session_id or "__default__"
        if key in self._cached_distinct_entities_map:
            return self._cached_distinct_entities_map[key]

        entities: Dict[str, List[Any]] = {
            "banks": [],
            "bank_codes": [],
            "programs": [],
            "entities": [],
            "all_categorical_values": []
        }

        profile = self.get_schema_profile(session_id)
        all_vals: Set[str] = set()

        for t_name, cols in profile.items():
            for c_name, info in cols.items():
                samples = info.get("sample_values", [])
                for s in samples:
                    if len(str(s)) >= 2:
                        all_vals.add(str(s))

        for k in entities:
            if isinstance(entities[k], list):
                entities[k] = list(dict.fromkeys(entities[k]))

        # Look for explicit bank / vendor table if available
        for bank_cand in ["bank", "banks", "vendor", "vendors"]:
            if bank_cand in profile and not entities["banks"]:
                for col in ["bank_name", "vendor_name", "name"]:
                    if col in profile[bank_cand]:
                        try:
                            df, _, _ = self.execute_query(
                                f"SELECT DISTINCT `{col}` FROM `{bank_cand}` WHERE `{col}` IS NOT NULL;",
                                session_id=session_id
                            )
                            entities["banks"] = [str(x) for x in df[col].tolist() if pd.notnull(x)]
                            break
                        except Exception:
                            pass

        entities["all_categorical_values"] = list(all_vals)
        self._cached_distinct_entities_map[key] = entities
        return entities

    def get_value_to_column_map(self, session_id: Optional[str] = None) -> Dict[str, List[Dict[str, str]]]:
        """Maps distinct categorical values to their source (table, column) for schema linking."""
        key = session_id or "__default__"
        if key in self._cached_value_maps:
            return self._cached_value_maps[key]

        profile = self.get_schema_profile(session_id)
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

        self._cached_value_maps[key] = val_map
        return val_map


db = DatabaseManager()
