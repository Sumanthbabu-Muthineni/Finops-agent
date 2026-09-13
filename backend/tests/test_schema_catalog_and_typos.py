"""
Tests for SchemaCatalog, Proactive Column Typo Detection, and Schema Inquiries.
Ensures zero hardcoding, dynamic schema inspection, and seamless LangGraph routing.
"""

import unittest
from backend.engine.schema_catalog import schema_catalog
from backend.graph.workflow import create_financial_agent_graph

class TestSchemaCatalogAndTypos(unittest.TestCase):

    def test_schema_catalog_extracts_columns_dynamically(self):
        cols = schema_catalog.get_all_columns()
        self.assertIn("utr_number", cols)
        self.assertIn("account_number", cols)
        self.assertIn("available_balance", cols)
        self.assertIn("transaction_amount", cols)

        # Check metadata properties
        utr_info = cols["utr_number"]
        self.assertIn("Unique Transaction Reference", utr_info["description"])
        self.assertTrue(len(utr_info["tables"]) > 0)

    def test_exact_column_inquiry(self):
        res = schema_catalog.detect_schema_inquiry("whats utr_number??")
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "COLUMN_EXPLANATION")
        self.assertEqual(res["column"], "utr_number")
        self.assertFalse(res["is_typo"])
        self.assertIn("Unique Transaction Reference", res["narrative"])
        self.assertIn("Database Metadata", res["narrative"])

    def test_typo_column_inquiry_with_did_you_mean(self):
        # User typed "otr_number" instead of "utr_number"
        res = schema_catalog.detect_schema_inquiry("otr_number")
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "COLUMN_TYPO")
        self.assertEqual(res["suggested_column"], "utr_number")
        self.assertTrue(res["is_typo"])
        self.assertIn("Did you mean **`utr_number`**?", res["narrative"])
        self.assertIn("Unique Transaction Reference", res["narrative"])

    def test_typo_column_with_question_mark(self):
        res = schema_catalog.detect_schema_inquiry("what is otr_number?")
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "COLUMN_TYPO")
        self.assertEqual(res["suggested_column"], "utr_number")

    def test_data_query_passes_through(self):
        # "no i am asking about utr_number for any two accounts" is a data query, NOT a schema definition request
        res = schema_catalog.detect_schema_inquiry("no i am asking about utr_number for any two accounts")
        self.assertIsNone(res)

    def test_financial_calculation_query_passes_through(self):
        res = schema_catalog.detect_schema_inquiry("What is our total available balance across all banks?")
        self.assertIsNone(res)

    def test_langgraph_end_to_end_schema_inquiry(self):
        graph = create_financial_agent_graph()
        initial_state = {
            "session_id": "test_schema_session",
            "user_query": "whats utr_number??",
            "conversation_history": [],
            "last_ast": None,
            "session_confirmed_entities": {},
            "active_context_vendor": None
        }
        final_state = graph.invoke(initial_state)
        self.assertEqual(final_state["intent_type"], "SCHEMA_INQUIRY")
        self.assertEqual(final_state["status"], "success")
        self.assertIn("Column Definition: `utr_number`", final_state["final_narrative"])
        self.assertIsNotNone(final_state["clarification_options"])

    def test_langgraph_end_to_end_column_typo(self):
        graph = create_financial_agent_graph()
        initial_state = {
            "session_id": "test_typo_session",
            "user_query": "otr_number",
            "conversation_history": [],
            "last_ast": None,
            "session_confirmed_entities": {},
            "active_context_vendor": None
        }
        final_state = graph.invoke(initial_state)
        self.assertEqual(final_state["intent_type"], "SCHEMA_INQUIRY")
        self.assertEqual(final_state["status"], "success")
        self.assertIn("Did you mean **`utr_number`**?", final_state["final_narrative"])

if __name__ == "__main__":
    unittest.main()
