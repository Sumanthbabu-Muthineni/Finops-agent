import sys
from pathlib import Path
import json

root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root_dir))

from backend.engine.db import db
from backend.engine.query_compiler import query_compiler
from backend.llm.client import MockLLMClient, llm_adapter
from backend.core.models import FinancialQueryAST, EntityFilter, DateRangeFilter
from backend.graph.workflow import financial_agent_graph

def test_dynamic_schema_profile_introspection():
    """Verify DuckDB dynamic schema profiling discovers columns and distinct values without hardcoding."""
    profile = db.get_schema_profile()
    assert "transactions" in profile
    assert "accounts" in profile
    assert "banks" in profile

    txn_cols = profile["transactions"]
    assert "transaction_type" in txn_cols
    assert "bank_name" in txn_cols
    assert "transaction_amount" in txn_cols

    # Check distinct values extracted
    type_vals = txn_cols["transaction_type"].get("sample_values", [])
    assert any("CREDIT" in str(v).upper() for v in type_vals)
    assert any("DEBIT" in str(v).upper() for v in type_vals)

    bank_vals = txn_cols["bank_name"].get("sample_values", [])
    assert any("HDFC" in str(v).upper() for v in bank_vals)
    assert any("STATE BANK OF INDIA" in str(v).upper() for v in bank_vals)

    val_map = db.get_value_to_column_map()
    assert "credit" in val_map
    assert "debit" in val_map

def test_mock_llm_credit_debit_breakdown():
    """Query with 'credit vs debit' maps dynamically to group_by: ['transaction_type']."""
    client = MockLLMClient()
    prompt = "How much was credited vs debited in June 2026?"
    res = json.loads(client.complete(prompt))
    assert res["target_domain"] == "transactions"
    assert "transaction_type" in res["group_by"]

def test_mock_llm_bank_breakdown():
    """Query with 'by bank' maps dynamically to group_by: ['bank_name']."""
    client = MockLLMClient()
    prompt = "Show total available balance breakdown by bank"
    res = json.loads(client.complete(prompt))
    assert res["target_domain"] == "accounts"
    assert "bank_name" in res["group_by"]

def test_mock_llm_program_filter():
    """Query with 'program 101' maps dynamically to program_id filter."""
    client = MockLLMClient()
    prompt = "Show transactions for program 101"
    res = json.loads(client.complete(prompt))
    assert res["target_domain"] == "transactions"
    filters = {f["field"]: f["value"] for f in res["entity_filters"]}
    assert "program_id" in filters
    assert str(filters["program_id"]) == "101"

def test_mock_llm_reference_id_search():
    """Query with 'reference ID 1715499972' maps to transaction_reference_id lookup."""
    client = MockLLMClient()
    prompt = "Lookup transaction reference 1715499972"
    res = json.loads(client.complete(prompt))
    assert res["target_domain"] == "transactions"
    filters = {f["field"]: f["value"] for f in res["entity_filters"]}
    assert "transaction_reference_id" in filters
    assert filters["transaction_reference_id"] == "1715499972"

def test_universal_sql_compiler():
    """Compiler handles filters on any column with uniform case-insensitive comparisons."""
    ast = FinancialQueryAST(
        target_domain="transactions",
        target_metric="total_amount",
        entity_filters=[
            EntityFilter(field="bank_name", operator="eq", value="HDFC BANK LIMITED"),
            EntityFilter(field="transaction_type", operator="eq", value="debit")
        ],
        group_by=["program_id"],
        order_by_desc=True,
        limit=50
    )
    sql = query_compiler.compile(ast)
    assert "v_transactions" in sql
    assert "UPPER(CAST(bank_name AS VARCHAR)) = UPPER('HDFC BANK LIMITED')" in sql
    assert "UPPER(CAST(transaction_type AS VARCHAR)) = UPPER('debit')" in sql
    assert "GROUP BY program_id" in sql

def test_full_graph_banking_breakdown():
    """LangGraph execution end-to-end for credit vs debit breakdown."""
    state = {
        "session_id": "test-breakdown-session-1",
        "user_query": "How much was credited vs debited in June 2026?",
        "conversation_history": [],
        "last_ast": None,
        "resolved_vendor": None,
        "entity_score": 1.0,
        "target_domain": None,
        "current_ast": None,
        "compiled_sql": None,
        "records_sql": None,
        "db_records": [],
        "summary_metrics": [],
        "row_count": 0,
        "execution_time_ms": 0.0,
        "anomaly": None,
        "confidence": None,
        "needs_clarification": False,
        "clarification_options": None,
        "final_narrative": None,
        "status": "processing"
    }
    result = financial_agent_graph.invoke(state)
    assert result["status"] == "success"
    assert len(result["db_records"]) > 0

    # Ensure summary metrics contain breakdown KPI cards
    labels = [m["label"] for m in result.get("summary_metrics", [])]
    assert any("Credit" in lbl for lbl in labels)
    assert any("Debit" in lbl for lbl in labels)

if __name__ == "__main__":
    tests = [
        test_dynamic_schema_profile_introspection,
        test_mock_llm_credit_debit_breakdown,
        test_mock_llm_bank_breakdown,
        test_mock_llm_program_filter,
        test_mock_llm_reference_id_search,
        test_universal_sql_compiler,
        test_full_graph_banking_breakdown
    ]
    print("=== Running Universal Schema Dynamicity Test Suite (TBX Schema) ===")
    for t in tests:
        t()
        print(f"✅ {t.__name__} PASSED")
    print("\n🎉 ALL 7 TBX DYNAMIC SCHEMA TESTS PASSED SUCCESSFULLY!")
