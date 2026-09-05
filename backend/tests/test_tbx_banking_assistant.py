import sys
from pathlib import Path
import json

root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root_dir))

from backend.engine.db import db
from backend.core.entity_resolver import entity_resolver
from backend.engine.query_compiler import query_compiler
from backend.core.models import FinancialQueryAST, EntityFilter, DateRangeFilter
from backend.analytics.anomaly import iqr_detector
from backend.analytics.confidence import confidence_evaluator
from backend.graph.workflow import financial_agent_graph

def test_tbx_schema_and_views():
    print("--- 1. Testing TBX Schema & Views ---")
    anchor = db.get_anchor_date()
    print(f"✅ Dynamic anchor date: {anchor}")
    assert anchor.startswith("2026-")

    # 1. v_transactions
    df_tx, lat1, count1 = db.execute_query("SELECT * FROM v_transactions LIMIT 5;")
    print(f"✅ v_transactions queried in {lat1} ms (Count: {count1})")
    assert count1 == 5
    assert "masked_account_number" in df_tx.columns
    assert "transaction_type" in df_tx.columns
    assert "bank_name" in df_tx.columns
    # Verify masking
    for acc in df_tx["masked_account_number"]:
        assert str(acc).startswith("****"), f"Expected masked account, got {acc}"

    # 2. v_accounts
    df_acc, lat2, count2 = db.execute_query("SELECT * FROM v_accounts LIMIT 5;")
    print(f"✅ v_accounts queried in {lat2} ms (Count: {count2})")
    assert count2 == 5
    assert "available_balance" in df_acc.columns

    # 3. v_banks
    df_banks, lat3, count3 = db.execute_query("SELECT * FROM v_banks;")
    print(f"✅ v_banks queried in {lat3} ms (Banks: {count3})")
    assert count3 == 10

def test_entity_resolver_banks():
    print("\n--- 2. Testing Entity Resolver for Banks ---")
    # Exact code
    b, score, _ = entity_resolver.resolve_vendor("HDFC")
    print(f"✅ 'HDFC' -> '{b}' (Score: {score})")
    assert "HDFC" in b

    # Shorthand acronym
    b, score, _ = entity_resolver.resolve_vendor("SBI")
    print(f"✅ 'SBI' -> '{b}' (Score: {score})")
    assert "STATE BANK OF INDIA" in b

    # Name variant
    b, score, _ = entity_resolver.resolve_vendor("Axis Bank")
    print(f"✅ 'Axis Bank' -> '{b}' (Score: {score})")
    assert "AXIS" in b

def test_balance_and_breakdown_compilation():
    print("\n--- 3. Testing Query Compilation for TBX Schema ---")
    # A. Balance query
    ast_bal = FinancialQueryAST(
        target_domain="accounts",
        target_metric="available_balance",
        group_by=["bank_name"]
    )
    sql_bal = query_compiler.compile(ast_bal)
    print(f"✅ Compiled Balance SQL: {sql_bal}")
    assert "v_accounts" in sql_bal
    assert "available_balance" in sql_bal
    df_b, _, _ = db.execute_query(sql_bal)
    assert len(df_b) > 0

    # B. Credit vs Debit breakdown query
    ast_type = FinancialQueryAST(
        target_domain="transactions",
        target_metric="total_amount",
        date_range=DateRangeFilter(start_date="2026-06-01", end_date="2026-06-30"),
        group_by=["transaction_type"]
    )
    sql_type = query_compiler.compile(ast_type)
    print(f"✅ Compiled Breakdown SQL: {sql_type}")
    assert "v_transactions" in sql_type
    assert "GROUP BY transaction_type" in sql_type
    df_t, _, _ = db.execute_query(sql_type)
    assert len(df_t) == 2  # credit and debit

    # C. Search by Reference ID
    ast_ref = FinancialQueryAST(
        target_domain="transactions",
        target_metric="records_list",
        entity_filters=[EntityFilter(field="transaction_reference_id", operator="eq", value="1715499972")]
    )
    sql_ref = query_compiler.compile(ast_ref)
    print(f"✅ Compiled Reference Search SQL: {sql_ref}")
    df_r, _, count_r = db.execute_query(sql_ref)
    assert count_r == 1
    assert df_r["masked_account_number"].iloc[0] == "****9069"

def test_iqr_anomaly_hook():
    print("\n--- 4. Testing Statistical IQR Anomaly Hook ---")
    # All transactions in June 2026 (includes the intentional 1,850,000 outlier)
    sql = "SELECT * FROM v_transactions WHERE transaction_date >= '2026-06-01' AND transaction_date <= '2026-06-30' ORDER BY transaction_date ASC;"
    df, _, count = db.execute_query(sql)
    df_flagged, anomaly = iqr_detector.detect(df, amount_col="transaction_amount")
    print(f"✅ June 2026 transactions analyzed: {count} rows")
    print(f"   Anomaly Detected: {anomaly.detected}")
    if anomaly.detected:
        print(f"   Outlier Value: ${anomaly.outlier_value:,.2f}")
        print(f"   Baseline: {anomaly.typical_range}")
        print(f"   Message: {anomaly.message}")
    assert anomaly.detected == True
    assert anomaly.outlier_value >= 1850000.00

def test_langgraph_banking_workflow():
    print("\n--- 5. Testing LangGraph State Machine on Banking Queries ---")
    # Turn 1: Check total available balance
    state_turn_1 = {
        "session_id": "test-bank-session-1",
        "user_query": "What is our total available balance across all banks?",
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

    res1 = financial_agent_graph.invoke(state_turn_1)
    print("✅ Turn 1 (Total Balance):")
    print("   Status:", res1["status"])
    print("   Narrative:", res1["final_narrative"])
    print("   Metrics:", res1["summary_metrics"])
    assert res1["status"] == "success"
    assert len(res1["summary_metrics"]) > 0

    # Turn 2: Credit vs Debit in June 2026
    state_turn_2 = {
        "session_id": "test-bank-session-1",
        "user_query": "How much was credited vs debited in June 2026?",
        "conversation_history": [
            {"role": "user", "content": state_turn_1["user_query"]},
            {"role": "assistant", "content": res1["final_narrative"]}
        ],
        "last_ast": res1["current_ast"],
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

    res2 = financial_agent_graph.invoke(state_turn_2)
    print("\n✅ Turn 2 (Credit vs Debit Breakdown):")
    print("   Status:", res2["status"])
    print("   Narrative:", res2["final_narrative"])
    print("   Metrics:", res2["summary_metrics"])
    assert res2["status"] == "success"
    assert any("Debit" in m["label"] for m in res2["summary_metrics"])
    assert any("Credit" in m["label"] for m in res2["summary_metrics"])

    # Turn 3: Lookup reference ID from official sample data
    state_turn_3 = {
        "session_id": "test-bank-session-1",
        "user_query": "Lookup transaction with reference ID 1715499972",
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

    res3 = financial_agent_graph.invoke(state_turn_3)
    print("\n✅ Turn 3 (Reference ID Lookup):")
    print("   Status:", res3["status"])
    print("   Narrative:", res3["final_narrative"])
    print("   Records:", len(res3["db_records"]))
    assert res3["status"] == "success"
    assert len(res3["db_records"]) == 1
    # Check that sensitive account number was masked in output
    record = res3["db_records"][0]
    assert record["masked_account_number"] == "****9069"
    assert record["account_number"] == "****9069"

if __name__ == "__main__":
    print("=================================================================")
    print("RUNNING TBX BANKING ASSISTANT AUTOMATED TEST SUITE")
    print("=================================================================")
    test_tbx_schema_and_views()
    test_entity_resolver_banks()
    test_balance_and_breakdown_compilation()
    test_iqr_anomaly_hook()
    test_langgraph_banking_workflow()
    print("\n=================================================================")
    print("🎉 ALL TBX BANKING ASSISTANT TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")
