from typing import Dict, Any, List
from datetime import datetime
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
from backend.core.masking import mask_records_dataframe

from backend.core.conversation_agent import conversation_agent

def intent_and_entity_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 1: Checks scope/greeting intent and resolves multi-turn conversational context using ConversationContextAgent."""
    query = state["user_query"]
    session_confirmed = dict(state.get("session_confirmed_entities") or {})
    active_vendor = state.get("active_context_vendor")
    history = state.get("conversation_history") or []

    # 1. Agentic Conversational Reasoning (Zero brittle regex / hardcoded lists)
    conv_res = conversation_agent.resolve(
        query=query,
        conversation_history=history,
        active_context_vendor=active_vendor,
        llm_client=llm_adapter.client
    )

    intent_type = conv_res.intent
    if intent_type in ["GREETING", "OUT_OF_SCOPE"]:
        sample_vendors = entity_resolver.vendors[:4]
        return {
            "intent_type": intent_type,
            "resolved_vendor": None,
            "entity_score": 1.0,
            "final_narrative": conv_res.conversational_reply or "I am your enterprise FinOps Banking Assistant.",
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

    # 2. Use the disambiguated standalone query from the Conversation Agent
    resolved_query = conv_res.standalone_query or query
    resolved_vendor = conv_res.resolved_bank
    context_scope = conv_res.context_scope

    # If the conversation agent resolved a specific bank:
    if resolved_vendor:
        active_vendor = resolved_vendor
        for alias in entity_resolver.get_aliases_for_vendor(resolved_vendor):
            session_confirmed[alias] = resolved_vendor
        score = 1.0
        suggestions = []
    elif context_scope == "GLOBAL":
        # Global query: completely clear active single-bank context!
        active_vendor = None
        resolved_vendor = None
        score = 1.0
        suggestions = []
    else:
        # Fallback to entity resolver for keyword / alias checks on the resolved query
        er_vendor, er_score, er_req, er_sugg, er_alias = entity_resolver.resolve_with_session(
            query=resolved_query,
            session_confirmed_entities=session_confirmed,
            active_context_vendor=active_vendor
        )
        if er_vendor:
            resolved_vendor = er_vendor
            active_vendor = er_vendor
            score = er_score
            suggestions = []
        else:
            resolved_vendor = None
            score = er_score
            suggestions = er_sugg

    return {
        "intent_type": "FINANCIAL",
        "user_query": resolved_query,
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
    session_confirmed = state.get("session_confirmed_entities") or {}
    active_vendor = state.get("active_context_vendor")
    session_id = state.get("session_id")

    ast_obj = llm_adapter.generate_ast(
        query=query,
        resolved_vendor=resolved_vendor,
        anchor_date=anchor_date,
        last_ast=last_ast,
        conversation_history=history,
        active_context_vendor=active_vendor,
        session_confirmed_entities=session_confirmed,
        session_id=session_id
    )

    return {
        "current_ast": ast_obj.model_dump(),
        "target_domain": ast_obj.target_domain,
        "active_context_vendor": active_vendor,
        "session_confirmed_entities": session_confirmed
    }

def sql_compiler_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 3: Deterministic compilation from AST to parameterized MySQL ANSI-SQL."""
    ast_dict = state["current_ast"]
    ast_obj = FinancialQueryAST(**ast_dict)
    session_id = state.get("session_id")

    compiled_sql = query_compiler.compile(ast_obj, session_id=session_id)
    records_sql = query_compiler.compile_records_query(ast_obj, session_id=session_id)

    return {
        "compiled_sql": compiled_sql,
        "records_sql": records_sql
    }

def db_execution_and_iqr_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 4: Executes MySQL ANSI-SQL (zero LLM math) and triggers IQR Anomaly Hook."""
    compiled_sql = state["compiled_sql"]
    records_sql = state["records_sql"]
    session_id = state.get("session_id")

    # 1. Execute summary aggregation query
    summary_df, latency_ms, _ = db.execute_query(compiled_sql, session_id=session_id)

    # 2. Execute granular records query for AgGrid and CSV export
    records_df, _, row_count = db.execute_query(records_sql, session_id=session_id)

    # 3. Trigger IQR Anomaly Hook
    records_df, anomaly_info = iqr_detector.detect(records_df, amount_col="amount")

    summary_metrics = []
    breakdown_items = []
    ast_dict = state.get("current_ast") or {}
    is_grouped = bool(ast_dict.get("group_by"))
    is_balance_query = (state.get("target_domain") == "accounts") or any(
        w in state.get("user_query", "").lower() for w in ["balance", "balances"]
    )

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

            # For concise groupings (<= 3 items, e.g. Credit vs Debit), show individual KPI cards
            if len(breakdown_items) <= 3:
                for item in breakdown_items:
                    val_str = item["name"]
                    amt = item["amount"]
                    if is_balance_query:
                        metric_suffix = "Balance"
                    elif any(x in val_str.upper() for x in ["CREDIT", "DEBIT"]):
                        metric_suffix = "Amount"
                    else:
                        metric_suffix = "Spend"
                    summary_metrics.append({
                        "label": f"{val_str.title()} {metric_suffix}",
                        "value": f"${amt:,.2f}"
                    })

                if len(breakdown_items) > 1:
                    total_label = "Total Balance" if is_balance_query else "Total Amount"
                    records_label = "Accounts" if is_balance_query else "Transactions"
                    summary_metrics.append({
                        "label": total_label,
                        "value": f"${total_grouped_spend:,.2f}"
                    })
                    summary_metrics.append({
                        "label": records_label,
                        "value": str(total_grouped_records)
                    })
            else:
                # For multi-item groupings (> 3 items, e.g. 10 companies), provide clean high-level executive cards
                total_label = "Total Balance" if is_balance_query else "Total Amount"
                records_label = "Total Accounts" if is_balance_query else "Total Transactions"
                group_label = "Companies" if is_balance_query else "Categories"

                # Identify highest item by amount
                sorted_items = sorted(breakdown_items, key=lambda x: x["amount"], reverse=True)
                top_item = sorted_items[0]

                summary_metrics.append({
                    "label": total_label,
                    "value": f"${total_grouped_spend:,.2f}"
                })
                summary_metrics.append({
                    "label": "Top Company" if is_balance_query else "Top Category",
                    "value": top_item["name"].title()
                })
                summary_metrics.append({
                    "label": "Top Balance" if is_balance_query else "Top Amount",
                    "value": f"${top_item['amount']:,.2f}"
                })
                summary_metrics.append({
                    "label": group_label,
                    "value": str(len(breakdown_items))
                })
                summary_metrics.append({
                    "label": records_label,
                    "value": str(total_grouped_records)
                })
        else:
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

    # For account inquiries, enrich with total transaction volume across these accounts
    if is_balance_query and not records_df.empty and "account_id" in records_df.columns:
        try:
            acc_ids = [r for r in records_df["account_id"].dropna().tolist() if r]
            if acc_ids:
                cnt_df, _, _ = db.execute_query(
                    "SELECT COUNT(*) AS txn_count FROM transaction WHERE account_id = ANY(%s)",
                    (acc_ids,)
                )
                if not cnt_df.empty and pd.notnull(cnt_df["txn_count"].iloc[0]):
                    txn_cnt = int(cnt_df["txn_count"].iloc[0])
                    summary_metrics.append({"label": "Total Transactions", "value": f"{txn_cnt:,}"})
        except Exception:
            pass

    # Determine if query warrants displaying a raw data table in the UI
    # Single-number / pure aggregate questions (e.g. "What is our total balance?")
    # should only display KPI cards, not dump all individual underlying accounts/transactions.
    user_q = (state.get("user_query") or "").lower()
    ast_metric = (ast_dict.get("target_metric") or "").lower()
    has_grouping = bool(ast_dict.get("group_by"))

    is_pure_aggregate = (
        not has_grouping 
        and ast_metric in ["total_amount", "available_balance", "average_amount", "record_count"]
        and not any(w in user_q for w in ["show", "list", "lookup", "details", "recent", "find", "top", "negative", "transactions", "records", "accounts", "how many accounts", "how many accoutns", "which accounts", "who paid", "who credited", "creditor"])
    )

    if is_pure_aggregate:
        records_list = []
    else:
        # Prepare table records (limit to 100 for fast UI rendering, clean NaT/NaN to None)
        clean_records_df = records_df.copy()
        # SENSITIVE DATA MASKING (Mandatory): Never leak raw account numbers or full UTR hashes
        clean_records_df = mask_records_dataframe(clean_records_df)
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

def index_advisor_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 4B: Proactively inspects runtime query execution against database index coverage."""
    session_id = state.get("session_id")
    ast_dict = state.get("current_ast") or {}
    target_table = state.get("target_domain") or ast_dict.get("target_domain") or "transaction"
    filters = ast_dict.get("entity_filters") or []
    date_range = ast_dict.get("date_range")
    date_col = ast_dict.get("date_column")

    filter_cols = [f.get("field") for f in filters if f.get("field")]
    if date_range and date_col:
        filter_cols.append(date_col)

    indexes = db.get_indexes(session_id)
    latency_ms = state.get("execution_time_ms", 0.0)

    from backend.engine.index_advisor import index_advisor
    analysis = index_advisor.analyze_runtime_query(
        table=target_table,
        filter_columns=filter_cols,
        indexes=indexes,
        execution_time_ms=latency_ms
    )

    advisories = []
    if analysis.get("advisory"):
        advisories.append(analysis)

    is_custom = db.is_custom_database(session_id)

    return {
        "query_index_status": analysis.get("status", "INDEX_ACCELERATED"),
        "optimization_advisories": advisories,
        "is_custom_database": is_custom
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
    query = state.get("user_query", "")
    resolved_vendor = state.get("resolved_vendor")
    row_count = state.get("row_count", 0)
    options = state.get("clarification_options") or entity_resolver.vendors[:4]
    ast_dict = state.get("current_ast") or {}
    date_range = ast_dict.get("date_range") or {}
    start_date = date_range.get("start_date") if isinstance(date_range, dict) else getattr(date_range, "start_date", None)
    end_date = date_range.get("end_date") if isinstance(date_range, dict) else getattr(date_range, "end_date", None)

    cur_anchor = db.get_anchor_date()
    max_db_dt = db.get_max_dataset_date()

    narrative = llm_adapter.synthesize_clarification(
        query=query,
        resolved_vendor=resolved_vendor,
        start_date=start_date,
        end_date=end_date,
        options=options,
        cur_anchor=cur_anchor,
        max_db_dt=max_db_dt,
        row_count=row_count
    )

    return {
        "final_narrative": narrative,
        "status": "clarification_needed",
        "summary_metrics": [],
        "breakdown_items": [],
        "db_records": [],
        "anomaly": None,
        "clarification_options": options[:4] if options else None,
        "needs_clarification": True,
        "active_context_vendor": state.get("active_context_vendor"),
        "session_confirmed_entities": state.get("session_confirmed_entities")
    }

def synthesizer_node(state: FinancialAgentState) -> Dict[str, Any]:
    """Node 6B: Zero-Math synthesis using MySQL relational calculated values."""
    query = state["user_query"]
    anomaly_dict = state.get("anomaly", {})
    anomaly_obj = AnomalyInfo(**anomaly_dict) if anomaly_dict else AnomalyInfo()
    sample_rows = state.get("db_records", [])
    breakdown_items = state.get("breakdown_items") or []
    # Check if the executed query actually filtered on bank_name / vendor_name
    ast_dict = state.get("current_ast") or {}
    filters = ast_dict.get("entity_filters") or []
    has_bank_filter = any(f.get("field") in ["bank_name", "vendor_name", "bank_code"] for f in filters)

    if has_bank_filter:
        resolved_vendor = state.get("resolved_vendor") or state.get("active_context_vendor")
    else:
        # Company-Wide / Global Query: NEVER attribute company-wide totals to an active vendor!
        resolved_vendor = None

    # Extract metrics for synthesizer
    metrics_map = {}
    for m in state.get("summary_metrics", []):
        lbl = m.get("label", "")
        val = str(m.get("value", ""))
        num_val = val.replace("$", "").replace(",", "")
        if lbl in ["Total Spend", "Total Amount", "Total Balance"]:
            metrics_map["total_amount"] = num_val
        elif lbl in ["Transactions", "Accounts", "Total Accounts", "Records Found"]:
            metrics_map["record_count"] = num_val
        elif lbl == "Total Transactions":
            metrics_map["total_transactions"] = num_val
        elif lbl in ["Average Payout", "Average Amount", "Average Transaction", "Average Balance"]:
            metrics_map["average_amount"] = num_val

    # Identify domain unit: bank accounts vs transactions
    target_domain = state.get("target_domain") or ast_dict.get("target_domain") or "transactions"
    is_balance_q = (target_domain == "accounts") or any(
        w in query.lower() for w in ["balance", "balances", "account", "accounts"]
    )
    domain_unit = "bank accounts" if is_balance_q else "transactions"

    narrative = llm_adapter.synthesize_narrative(
        query=query,
        metrics=metrics_map,
        anomaly=anomaly_obj,
        sample_rows=sample_rows,
        breakdown_items=breakdown_items,
        resolved_vendor=resolved_vendor,
        unit=domain_unit
    )

    # Append proactive index performance note if query suffered from unindexed scan on custom database
    advisories = state.get("optimization_advisories") or []
    if advisories and state.get("is_custom_database"):
        first_adv = advisories[0].get("advisory")
        if first_adv and first_adv not in narrative:
            narrative += f"\n\n> {first_adv}"

    return {
        "final_narrative": narrative,
        "status": "success",
        "last_ast": state.get("current_ast"),
        "active_context_vendor": state.get("active_context_vendor"),
        "session_confirmed_entities": state.get("session_confirmed_entities")
    }
