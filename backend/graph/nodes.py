from typing import Dict, Any, List
import pandas as pd
from backend.graph.state import FinancialAgentState
from backend.core.entity_resolver import entity_resolver
from backend.core.models import FinancialQueryAST, AnomalyInfo
from backend.llm.client import llm_adapter
from backend.engine.db import db
from backend.engine.query_compiler import query_compiler
from backend.analytics.anomaly import iqr_detector
from backend.analytics.confidence import confidence_evaluator
from backend.core.intent_classifier import intent_classifier

def intent_and_entity_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 1: Checks scope/greeting intent and resolves entities with multi-turn session awareness."""
    query = state["user_query"]
    session_confirmed = dict(state.get("session_confirmed_entities") or {})
    active_vendor = state.get("active_context_vendor")

    # 1. Hallucination Guardrail & Chit-Chat Interception
    intent_type, direct_response = intent_classifier.classify(query, llm_client=llm_adapter.client)
    if intent_type in ["GREETING", "OUT_OF_SCOPE"]:
        # Dynamically pull sample vendors directly from loaded database
        sample_vendors = entity_resolver.vendors[:4]
        return {
            "intent_type": intent_type,
            "resolved_vendor": None,
            "entity_score": 1.0,
            "final_narrative": direct_response,
            "status": "success" if intent_type == "GREETING" else "out_of_scope",
            "db_records": [],
            "summary_metrics": [],
            "row_count": 0,
            "execution_time_ms": 0.0,
            "anomaly": None,
            "confidence": None,
            "clarification_options": sample_vendors if intent_type == "OUT_OF_SCOPE" else None,
            "needs_clarification": False,
            "active_context_vendor": active_vendor,
            "session_confirmed_entities": session_confirmed,
            "breakdown_items": []
        }

    # 2. Dynamic, Session-Aware Entity Resolution (Zero Hardcoding)
    resolved_vendor, score, requires_confirmation, suggestions, matched_alias = entity_resolver.resolve_with_session(
        query=query,
        session_confirmed_entities=session_confirmed,
        active_context_vendor=active_vendor
    )

    # If an ambiguous acronym/shorthand was encountered for the first time without prior session confirmation:
    if requires_confirmation and resolved_vendor:
        alias_display = f" ({matched_alias.upper()})" if matched_alias else ""
        return {
            "intent_type": "FINANCIAL",
            "resolved_vendor": None,
            "entity_score": score,
            "final_narrative": (
                f"Did you mean **{resolved_vendor}{alias_display}**? "
                f"Please confirm below to view payouts and transactions."
            ),
            "status": "clarification_needed",
            "db_records": [],
            "summary_metrics": [],
            "breakdown_items": [],
            "row_count": 0,
            "execution_time_ms": 0.0,
            "anomaly": None,
            "confidence": {
                "score": score,
                "tier": "MEDIUM",
                "entity_score": score,
                "ast_score": 1.0,
                "data_score": 0.0,
                "explanation": f"Disambiguation requested for '{matched_alias}'. Please confirm canonical vendor '{resolved_vendor}'."
            },
            "clarification_options": [resolved_vendor],
            "needs_clarification": True,
            "active_context_vendor": active_vendor,
            "session_confirmed_entities": session_confirmed
        }

    import re
    # Check if query is explicitly an all-entities / global query
    is_global = bool(re.search(
        r"\b(all entities|all vendors|all companies|all accounts|every vendor|across all|select all|for all entities|for all vendors|for all companies|for all|all of them|everyone)\b",
        query.lower()
    ))
    if is_global:
        active_vendor = None
        resolved_vendor = None
        score = 1.0
        suggestions = []

    # If vendor resolved with confidence:
    if resolved_vendor:
        # Update active vendor context
        active_vendor = resolved_vendor
        # Register all dynamic aliases for this vendor so subsequent turns never re-ask!
        for alias in entity_resolver.get_aliases_for_vendor(resolved_vendor):
            session_confirmed[alias] = resolved_vendor
        if matched_alias:
            session_confirmed[matched_alias] = resolved_vendor

    return {
        "intent_type": "FINANCIAL",
        "resolved_vendor": resolved_vendor,
        "entity_score": score,
        "active_context_vendor": active_vendor,
        "session_confirmed_entities": session_confirmed,
        "clarification_options": suggestions if not resolved_vendor and suggestions else None,
        "needs_clarification": False
    }

def ast_generator_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 2: Generates grammar-constrained Pydantic AST using 8B model."""
    query = state["user_query"]
    resolved_vendor = state.get("resolved_vendor")
    anchor_date = db.get_anchor_date()
    last_ast = state.get("last_ast")
    history = state.get("conversation_history") or []
    active_vendor = state.get("active_context_vendor")
    session_confirmed = state.get("session_confirmed_entities") or {}

    ast_obj = llm_adapter.generate_ast(
        query=query,
        resolved_vendor=resolved_vendor,
        anchor_date=anchor_date,
        last_ast=last_ast,
        conversation_history=history,
        active_context_vendor=active_vendor,
        session_confirmed_entities=session_confirmed
    )

    return {
        "current_ast": ast_obj.model_dump(),
        "target_domain": ast_obj.target_domain,
        "active_context_vendor": active_vendor,
        "session_confirmed_entities": session_confirmed
    }

def sql_compiler_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 3: Deterministic compilation from AST to parameterized DuckDB SQL."""
    ast_dict = state["current_ast"]
    ast_obj = FinancialQueryAST(**ast_dict)

    compiled_sql = query_compiler.compile(ast_obj)
    records_sql = query_compiler.compile_records_query(ast_obj)

    return {
        "compiled_sql": compiled_sql,
        "records_sql": records_sql
    }

def db_execution_and_iqr_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 4: Executes DuckDB SQL (zero LLM math) and triggers IQR Anomaly Hook."""
    compiled_sql = state["compiled_sql"]
    records_sql = state["records_sql"]

    # 1. Execute summary aggregation query
    summary_df, latency_ms, _ = db.execute_query(compiled_sql)

    # 2. Execute granular records query for AgGrid and CSV export
    records_df, _, row_count = db.execute_query(records_sql)

    # 3. Trigger IQR Anomaly Hook
    records_df, anomaly_info = iqr_detector.detect(records_df, amount_col="amount")

    # Format summary KPI cards (ONLY when records exist and have valid non-NaN values)
    summary_metrics = []
    breakdown_items = []
    ast_dict = state.get("current_ast") or {}
    is_grouped = bool(ast_dict.get("group_by"))

    if not summary_df.empty and row_count > 0:
        cols = list(summary_df.columns)
        # Check if query produced grouped results (e.g. breakdown by transaction_type, bank_name, etc.)
        group_cols = [c for c in cols if c not in ["total_amount", "record_count", "average_amount"]]

        if is_grouped and group_cols:
            total_grouped_spend = 0.0
            total_grouped_records = 0
            for _, row in summary_df.iterrows():
                group_val = row[group_cols[0]]
                val_str = str(group_val) if pd.notnull(group_val) else "Unknown"
                amt = float(row["total_amount"]) if "total_amount" in cols and pd.notnull(row["total_amount"]) else 0.0
                cnt = int(row["record_count"]) if "record_count" in cols and pd.notnull(row["record_count"]) else 0

                total_grouped_spend += amt
                total_grouped_records += cnt

                breakdown_items.append({
                    "name": val_str,
                    "amount": round(amt, 2),
                    "count": cnt
                })
                # Dynamic KPI card for each group value (e.g. "Credit Amount", "Debit Amount")
                metric_suffix = "Amount" if any(x in str(group_val).upper() for x in ["CREDIT", "DEBIT"]) else "Spend"
                summary_metrics.append({
                    "label": f"{val_str.title()} {metric_suffix}",
                    "value": f"${amt:,.2f}"
                })

            if len(breakdown_items) > 1:
                summary_metrics.append({
                    "label": "Total Amount",
                    "value": f"${total_grouped_spend:,.2f}"
                })
                summary_metrics.append({
                    "label": "Transactions",
                    "value": str(total_grouped_records)
                })
        else:
            is_balance_query = (state.get("target_domain") == "accounts") or any(w in state.get("user_query", "").lower() for w in ["balance", "balances"])
            total_label = "Total Balance" if is_balance_query else "Total Amount"
            count_label = "Accounts" if is_balance_query else "Transactions"
            avg_label = "Average Balance" if is_balance_query else "Average Transaction"

            if "total_amount" in cols and pd.notnull(summary_df["total_amount"].iloc[0]):
                val = summary_df["total_amount"].iloc[0]
                summary_metrics.append({"label": total_label, "value": f"${float(val):,.2f}"})
            if "record_count" in cols and pd.notnull(summary_df["record_count"].iloc[0]):
                val = summary_df["record_count"].iloc[0]
                summary_metrics.append({"label": count_label, "value": str(int(val))})
            if "average_amount" in cols and pd.notnull(summary_df["average_amount"].iloc[0]):
                val = summary_df["average_amount"].iloc[0]
                summary_metrics.append({"label": avg_label, "value": f"${float(val):,.2f}"})

    # If no metrics derived, populate from records
    if not summary_metrics and not records_df.empty:
        summary_metrics.append({"label": "Records Found", "value": str(len(records_df))})
        if "transaction_amount" in records_df.columns:
            total = records_df["transaction_amount"].sum()
            summary_metrics.append({"label": "Total Amount", "value": f"${float(total):,.2f}"})
        elif "amount" in records_df.columns:
            total = records_df["amount"].sum()
            summary_metrics.append({"label": "Total Amount", "value": f"${float(total):,.2f}"})

    # Prepare table records (limit to 100 for fast UI rendering, clean NaT/NaN to None)
    clean_records_df = records_df.copy()

    # SENSITIVE DATA MASKING (Mandatory): Never leak raw account numbers or full UTR hashes
    if "masked_account_number" in clean_records_df.columns:
        clean_records_df["account_number"] = clean_records_df["masked_account_number"]
    if "masked_utr_number" in clean_records_df.columns:
        clean_records_df["utr_number"] = clean_records_df["masked_utr_number"]

    clean_records_df = clean_records_df.astype(object).where(pd.notnull(clean_records_df), None)
    records_list = clean_records_df.head(100).to_dict(orient="records")

    return {
        "db_records": records_list,
        "summary_metrics": summary_metrics,
        "breakdown_items": breakdown_items,
        "row_count": row_count,
        "execution_time_ms": latency_ms,
        "anomaly": anomaly_info.model_dump()
    }

def confidence_gate_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 5: Computes Quantitative Confidence Score (0-100%)."""
    entity_score = state.get("entity_score", 1.0)
    ast_valid = state.get("current_ast") is not None
    row_count = state.get("row_count", 0)
    resolved_vendor = state.get("resolved_vendor")

    confidence = confidence_evaluator.evaluate(
        entity_score=entity_score,
        ast_valid=ast_valid,
        row_count=row_count,
        resolved_vendor=resolved_vendor
    )

    needs_clarification = (confidence.score < 0.65) or (row_count == 0)

    return {
        "confidence": confidence.model_dump(),
        "needs_clarification": needs_clarification
    }

def clarification_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 6A: Halts hallucination when data is missing or query is ambiguous."""
    resolved_vendor = state.get("resolved_vendor")
    row_count = state.get("row_count", 0)
    options = state.get("clarification_options") or entity_resolver.vendors[:4]

    if row_count == 0 and resolved_vendor:
        narrative = (
            f"No financial records were found for **'{resolved_vendor}'** matching your specified filters. "
            f"Please verify the date range or check one of our active banks/entities: {', '.join(options[:4])}."
        )
    elif not resolved_vendor and options:
        narrative = (
            f"We couldn't clearly identify the bank, account, or program in your question. "
            f"Did you mean one of these: **{', '.join(options[:4])}**?"
        )
    else:
        narrative = (
            "We could not locate data matching your query in the current financial datasets. "
            "Please refine your query or ask about bank accounts, balances, transactions, or reference IDs."
        )

    return {
        "final_narrative": narrative,
        "status": "clarification_needed",
        "summary_metrics": [],
        "breakdown_items": [],
        "db_records": [],
        "anomaly": None,
        "clarification_options": options[:4] if options else None,
        "active_context_vendor": state.get("active_context_vendor"),
        "session_confirmed_entities": state.get("session_confirmed_entities")
    }

def synthesizer_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 6B: Zero-Math synthesis using DuckDB calculated values."""
    query = state["user_query"]
    anomaly_dict = state.get("anomaly", {})
    anomaly_obj = AnomalyInfo(**anomaly_dict) if anomaly_dict else AnomalyInfo()
    sample_rows = state.get("db_records", [])
    breakdown_items = state.get("breakdown_items") or []
    resolved_vendor = state.get("resolved_vendor") or state.get("active_context_vendor")

    # Extract metrics for synthesizer
    metrics_map = {}
    for m in state.get("summary_metrics", []):
        lbl = m.get("label", "")
        val = str(m.get("value", ""))
        num_val = val.replace("$", "").replace(",", "")
        if lbl in ["Total Spend", "Total Amount", "Total Balance"]:
            metrics_map["total_amount"] = num_val
        elif lbl in ["Transactions", "Accounts", "Records Found"]:
            metrics_map["record_count"] = num_val
        elif lbl in ["Average Payout", "Average Amount", "Average Transaction", "Average Balance"]:
            metrics_map["average_amount"] = num_val

    narrative = llm_adapter.synthesize_narrative(
        query=query,
        metrics=metrics_map,
        anomaly=anomaly_obj,
        sample_rows=sample_rows,
        breakdown_items=breakdown_items,
        resolved_vendor=resolved_vendor
    )

    return {
        "final_narrative": narrative,
        "status": "success",
        "last_ast": state.get("current_ast"),
        "active_context_vendor": state.get("active_context_vendor"),
        "session_confirmed_entities": state.get("session_confirmed_entities")
    }
