import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app import app
from backend.engine.index_advisor import IndexAdvisor
from backend.engine.db import db
from backend.engine.query_compiler import query_compiler
from backend.core.models import FinancialQueryAST, EntityFilter
from backend.graph.workflow import financial_agent_graph

client = TestClient(app)

class TestIndexAdvisor(unittest.TestCase):
    def setUp(self):
        self.advisor = IndexAdvisor()

    def test_profile_schema_identifies_unindexed_columns(self):
        # Mock schema profile without indexes on transaction_date
        schema_profile = {
            "customer_transactions": [
                {"name": "id", "type": "int", "is_primary": True},
                {"name": "txn_date", "type": "date", "is_primary": False},
                {"name": "account_id", "type": "int", "is_primary": False},
                {"name": "amount", "type": "decimal(12,2)", "is_primary": False},
                {"name": "status", "type": "varchar(50)", "is_primary": False}
            ]
        }
        # Only primary key is indexed
        existing_indexes = {
            "customer_transactions": [
                {"index_name": "PRIMARY", "column_name": "id", "non_unique": 0, "seq_in_index": 1}
            ]
        }
        fks = {}
        row_counts = {"customer_transactions": 50000}

        report = self.advisor.profile_schema(schema_profile, existing_indexes, fks, row_counts)
        self.assertIn("recommendations", report)
        self.assertGreater(len(report["recommendations"]), 0)

        # Ensure recommendations include txn_date and account_id
        cols_recommended = [r["column"] for r in report["recommendations"]]
        self.assertIn("txn_date", cols_recommended)
        self.assertIn("account_id", cols_recommended)

        # Check that suggested DDL has proper syntax
        date_rec = next(r for r in report["recommendations"] if r["column"] == "txn_date")
        self.assertIn("CREATE INDEX", date_rec["suggested_ddl"])
        self.assertIn("`customer_transactions`(`txn_date`)", date_rec["suggested_ddl"])

    def test_runtime_query_analysis(self):
        existing_indexes = {
            "transaction": [
                {"index_name": "idx_txn_date", "column_name": "transaction_date", "non_unique": 1, "seq_in_index": 1}
            ]
        }
        # 1. Indexed query
        analysis_indexed = self.advisor.analyze_runtime_query(
            table="transaction",
            filter_columns=["transaction_date"],
            indexes=existing_indexes,
            execution_time_ms=12.5
        )
        self.assertEqual(analysis_indexed["status"], "OPTIMAL_INDEX_HIT")
        self.assertEqual(len(analysis_indexed["unindexed_columns"]), 0)

        # 2. Unindexed query
        analysis_unindexed = self.advisor.analyze_runtime_query(
            table="transaction",
            filter_columns=["vendor_name", "status"],
            indexes=existing_indexes,
            execution_time_ms=85.0
        )
        self.assertEqual(analysis_unindexed["status"], "UNINDEXED_SCAN")
        self.assertIn("vendor_name", analysis_unindexed["unindexed_columns"])
        self.assertGreater(len(analysis_unindexed["advisories"]), 0)


class TestQueryCompilerZeroDDL(unittest.TestCase):
    def test_compiles_fallback_joins_when_views_absent(self):
        # When compiling against a customer database with base tables but no v_transactions
        ast = FinancialQueryAST(
            target_domain="transaction",
            target_metric="total_amount",
            entity_filters=[
                EntityFilter(field="status", operator="eq", value="COMPLETED")
            ]
        )
        # Mock schema profile where transaction, bank_account, bank exist, but v_transactions does NOT exist
        custom_schema = {
            "transaction": {
                "transaction_id": {"type": "int", "is_primary": True},
                "amount": {"type": "decimal(12,2)", "is_primary": False},
                "status": {"type": "varchar(50)", "is_primary": False},
                "account_id": {"type": "int", "is_primary": False}
            },
            "bank_account": {
                "account_id": {"type": "int", "is_primary": True},
                "bank_id": {"type": "int", "is_primary": False},
                "account_number": {"type": "varchar(50)", "is_primary": False}
            },
            "bank": {
                "bank_id": {"type": "int", "is_primary": True},
                "bank_name": {"type": "varchar(100)", "is_primary": False}
            }
        }

        with patch.object(db, "get_schema_profile", return_value=custom_schema):
            sql = query_compiler.compile(ast, session_id="test-session-zero-ddl")
            self.assertIn("SELECT", sql.upper())
            self.assertIn("transaction", sql)
            # Ensure it did NOT assume v_transactions
            self.assertNotIn("v_transactions", sql)


class TestFastApiByodbEndpoints(unittest.TestCase):
    def test_db_status_default(self):
        res = client.get("/api/db/status/test-session-123")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_custom"])
        self.assertEqual(data["info"]["mode"], "default")

    def test_db_connect_validation_error_handling(self):
        # Intentionally invalid host to verify clean user-facing error response
        payload = {
            "session_id": "test-session-err",
            "host": "nonexistent-db-host-999.invalid",
            "port": 3306,
            "database": "bad_db",
            "username": "bad_user",
            "password": "bad_password"
        }
        res = client.post("/api/db/connect", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("detail", res.json())
        # Check that error is descriptive
        self.assertTrue(len(res.json()["detail"]) > 10)

    def test_db_disconnect(self):
        res = client.post("/api/db/disconnect", json={"session_id": "test-session-123"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("Reverted to default", data["message"])

    def test_chat_endpoint_includes_index_audit(self):
        # Querying the default DB
        res = client.post("/api/chat", json={
            "session_id": "test-chat-index-audit",
            "message": "What is our total available balance across all banks?"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("audit_trail", data)
        if data["audit_trail"]:
            self.assertIn("index_status", data["audit_trail"])
            # Default DB has B-Tree indexes
            self.assertIsNotNone(data["audit_trail"]["index_status"])


class TestLangGraphIndexAdvisorNode(unittest.TestCase):
    def test_workflow_has_index_advisor_node(self):
        # Verify node is compiled into LangGraph workflow
        nodes = financial_agent_graph.nodes
        self.assertIn("index_advisor", nodes)

if __name__ == "__main__":
    unittest.main()
