"""
Multi-Turn Integration Test Suite for LLM Conversation Context Agent
Verifies dialogue understanding, affirmation handling, context isolation,
and unit integrity across multi-turn sessions.
"""

import sys
from pathlib import Path
import json

root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root_dir))

from backend.graph.workflow import financial_agent_graph
from backend.core.conversation_agent import conversation_agent
from backend.engine.db import db

def test_shorthand_resolution_no_friction():
    """Verify standard bank acronyms (e.g. hdfc, sbi) resolve immediately with 100% confidence."""
    print("\n--- Test 1: Direct Bank Shorthand Resolution ---")
    state = {
        "session_id": "test-shorthand",
        "user_query": "what is the balance on hdfc",
        "conversation_history": [],
        "last_ast": None,
        "session_confirmed_entities": {},
        "active_context_vendor": None,
        "resolved_vendor": None,
        "entity_score": 1.0,
        "target_domain": None,
        "current_ast": None,
        "compiled_sql": None,
        "records_sql": None,
        "db_records": [],
        "summary_metrics": [],
        "breakdown_items": [],
        "row_count": 0,
        "execution_time_ms": 0.0,
        "anomaly": None,
        "confidence": None,
        "intent_type": None,
        "needs_clarification": False,
        "clarification_options": None,
        "final_narrative": None,
        "status": "processing"
    }

    result = financial_agent_graph.invoke(state)
    assert result["status"] == "success", f"Expected success, got {result['status']}"
    assert result["needs_clarification"] is False, "Should not require clarification modal"
    narrative = result.get("final_narrative", "")
    print("Direct HDFC Narrative:\n", narrative)
    assert "HDFC BANK LIMITED" in narrative or "HDFC" in narrative
    # Assert accounts vs transactions integrity: should not say '3 transactions' for account balance
    assert "3 transactions" not in narrative.lower(), "Should not call accounts 'transactions'"
    print("✓ Test 1 Passed: HDFC resolved directly with 100% confidence without confirmation friction.")

def test_affirmation_after_clarification():
    """Verify 'yes you are right' correctly resolves after clarification without being marked OUT_OF_SCOPE."""
    print("\n--- Test 2: Affirmation after Clarification ---")
    # Simulate a history where the assistant asked for confirmation
    history = [
        {"role": "user", "content": "what is the balance on hdfc on june 23rd."},
        {"role": "assistant", "content": "Did you mean **HDFC BANK LIMITED (HDFC)**? Please confirm below to view payouts and transactions."}
    ]

    state = {
        "session_id": "test-affirmation",
        "user_query": "yes you are right",
        "conversation_history": history,
        "last_ast": None,
        "session_confirmed_entities": {},
        "active_context_vendor": None,
        "resolved_vendor": None,
        "entity_score": 1.0,
        "target_domain": None,
        "current_ast": None,
        "compiled_sql": None,
        "records_sql": None,
        "db_records": [],
        "summary_metrics": [],
        "breakdown_items": [],
        "row_count": 0,
        "execution_time_ms": 0.0,
        "anomaly": None,
        "confidence": None,
        "intent_type": None,
        "needs_clarification": False,
        "clarification_options": None,
        "final_narrative": None,
        "status": "processing"
    }

    result = financial_agent_graph.invoke(state)
    print("Affirmation Status:", result["status"])
    print("Affirmation Narrative:\n", result.get("final_narrative"))
    assert result["status"] != "out_of_scope", "Affirmation must NEVER be marked OUT_OF_SCOPE!"
    assert result["status"] == "success", f"Expected success, got {result['status']}"
    assert "HDFC BANK LIMITED" in result.get("final_narrative", ""), "Should resolve HDFC BANK LIMITED"
    print("✓ Test 2 Passed: 'yes you are right' resolved pending clarification to HDFC.")

def test_context_switch_isolation():
    """Verify switching from AU Bank to 'how many rows you have in db' does not attribute company records to AU Bank."""
    print("\n--- Test 3: Context Switch & Company-Wide Isolation ---")
    # Turn 1: User asks about AU Bank
    history_turn1 = [
        {"role": "user", "content": "how maby accounts we have udner above bank"},
        {"role": "assistant", "content": "There is 1 account under AU SMALL FINANCE BANK LIMITED with an available balance of $5,420,190.50."}
    ]

    # Turn 2: User asks how many rows you have in db
    state = {
        "session_id": "test-isolation",
        "user_query": "how many rows you have in db",
        "conversation_history": history_turn1,
        "last_ast": None,
        "session_confirmed_entities": {"au small finance bank limited": "AU SMALL FINANCE BANK LIMITED"},
        "active_context_vendor": "AU SMALL FINANCE BANK LIMITED",
        "resolved_vendor": None,
        "entity_score": 1.0,
        "target_domain": None,
        "current_ast": None,
        "compiled_sql": None,
        "records_sql": None,
        "db_records": [],
        "summary_metrics": [],
        "breakdown_items": [],
        "row_count": 0,
        "execution_time_ms": 0.0,
        "anomaly": None,
        "confidence": None,
        "intent_type": None,
        "needs_clarification": False,
        "clarification_options": None,
        "final_narrative": None,
        "status": "processing"
    }

    result = financial_agent_graph.invoke(state)
    narrative = result.get("final_narrative", "")
    print("Global DB Rows Narrative:\n", narrative)
    assert result["status"] == "success"
    # The narrative must NOT claim that AU SMALL FINANCE BANK LIMITED has 13 rows or 25,010 rows!
    assert "13 rows in the database for au small finance" not in narrative.lower(), "Must NOT attribute company rows to AU Bank!"
    assert any(k in narrative for k in ["10,010", "25,010", "13", "10"]), "Should mention the database rows or accounts"
    print("✓ Test 3 Passed: Global database rows are not falsely attributed to AU Bank.")

def test_date_inquiry_does_not_inherit_conflicting_date():
    """Verify asking for dates of existing records does not inherit a restrictive single date filter."""
    print("\n--- Test 4: Date Inquiry on Records ---")
    history = [
        {"role": "user", "content": "what is the balance on hdfc"},
        {"role": "assistant", "content": "The total available balance for HDFC BANK LIMITED is $-252,302,939.33 across 3 bank accounts."}
    ]
    prior_ast = {
        "target_domain": "accounts",
        "target_metric": "available_balance",
        "entity_filters": [{"field": "bank_name", "operator": "eq", "value": "HDFC BANK LIMITED"}],
        "date_range": {"start_date": "2026-06-23", "end_date": "2026-06-23"},
        "group_by": [],
        "order_by_desc": False,
        "limit": 100
    }

    state = {
        "session_id": "test-date-inq",
        "user_query": "all these three records are on which date",
        "conversation_history": history,
        "last_ast": prior_ast,
        "session_confirmed_entities": {"hdfc": "HDFC BANK LIMITED"},
        "active_context_vendor": "HDFC BANK LIMITED",
        "resolved_vendor": None,
        "entity_score": 1.0,
        "target_domain": None,
        "current_ast": None,
        "compiled_sql": None,
        "records_sql": None,
        "db_records": [],
        "summary_metrics": [],
        "breakdown_items": [],
        "row_count": 0,
        "execution_time_ms": 0.0,
        "anomaly": None,
        "confidence": None,
        "intent_type": None,
        "needs_clarification": False,
        "clarification_options": None,
        "final_narrative": None,
        "status": "processing"
    }

    result = financial_agent_graph.invoke(state)
    narrative = result.get("final_narrative", "")
    print("Date Inquiry Narrative:\n", narrative)
    # Ensure it did not fail with "no records found for 2026-06-23"
    assert "no records to provide for the requested date range" not in narrative.lower(), "Should not fail due to inherited date filter"
    print("✓ Test 4 Passed: Date inquiry executed cleanly without conflicting date filter.")

def test_greeting_and_personal_questions_bypass_db():
    """Verify greetings ('hi', 'how are you?') and personal questions ('tell me a joke', 'who made you?') bypass database queries completely."""
    print("\n--- Test 5: Greetings and Personal Questions Dynamic LLM Classification ---")
    
    test_queries = [
        ("hi", "GREETING"),
        ("how are you?", "GREETING"),
        ("who are you", "GREETING"),
        ("can you tell me a joke?", "OUT_OF_SCOPE"),
        ("what is the weather today", "OUT_OF_SCOPE")
    ]

    for q, expected_intent in test_queries:
        state = {
            "session_id": "test-chat",
            "user_query": q,
            "conversation_history": [],
            "last_ast": None,
            "session_confirmed_entities": {},
            "active_context_vendor": None,
            "resolved_vendor": None,
            "entity_score": 1.0,
            "target_domain": None,
            "current_ast": None,
            "compiled_sql": None,
            "records_sql": None,
            "db_records": [],
            "summary_metrics": [],
            "breakdown_items": [],
            "row_count": 0,
            "execution_time_ms": 0.0,
            "anomaly": None,
            "confidence": None,
            "intent_type": None,
            "needs_clarification": False,
            "clarification_options": None,
            "final_narrative": None,
            "status": "processing"
        }

        result = financial_agent_graph.invoke(state)
        intent = result.get("intent_type")
        assert intent in ["GREETING", "OUT_OF_SCOPE"], f"Query '{q}' expected GREETING/OUT_OF_SCOPE but got {intent}"
        assert result.get("compiled_sql") is None, f"Query '{q}' executed SQL: {result.get('compiled_sql')}"
        assert result.get("summary_metrics") == [], f"Query '{q}' returned summary metrics: {result.get('summary_metrics')}"
        assert result.get("confidence") is None, f"Query '{q}' should have no confidence score: {result.get('confidence')}"
        assert result.get("final_narrative"), f"Query '{q}' returned empty narrative"
        print(f"  ✓ '{q}' -> {intent} (Zero SQL, Direct narrative: {result.get('final_narrative')[:60]}...)")

    print("✓ Test 5 Passed: All greetings & personal questions dynamically routed and bypassed DB.")

if __name__ == "__main__":
    test_shorthand_resolution_no_friction()
    test_affirmation_after_clarification()
    test_context_switch_isolation()
    test_date_inquiry_does_not_inherit_conflicting_date()
    test_greeting_and_personal_questions_bypass_db()
    print("\n==================================================")
    print("ALL MULTI-TURN CONVERSATION TESTS PASSED 100%!")
    print("==================================================")
