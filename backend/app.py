import uuid
import re
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.core.models import (
    ChatRequest, ChatResponse, ConfidenceBreakdown, AnomalyInfo,
    SummaryMetric, AuditTrail
)
from backend.graph.workflow import financial_agent_graph
from backend.engine.db import db
from backend.core.entity_resolver import entity_resolver

app = FastAPI(
    title="TBX FinOps Assistant API",
    description="Grounded conversational assistant for financial operations (PostgreSQL + LangGraph + 8B LLM)",
    version="1.0.0"
)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-Memory Session Storage
sessions: Dict[str, Dict[str, Any]] = {}

@app.get("/api/health")
def health_check():
    """Returns database status, anchor date, and model configuration."""
    entities = db.get_distinct_entities()
    return {
        "status": "healthy",
        "llm_provider": settings.LLM_PROVIDER,
        "anchor_date": db.get_anchor_date(),
        "total_banks": len(entities.get("banks", [])),
        "total_accounts": len(entities.get("entities", [])),
        "total_vendors": len(entities.get("banks", [])),
        "environment": "production" if not settings.DEBUG else "development"
    }

@app.get("/api/banks")
def list_banks():
    """Returns all distinct banks in database for UI search / suggestion pills."""
    return {"banks": getattr(entity_resolver, "banks", [])}

@app.get("/api/vendors")
def list_vendors():
    """Returns all distinct banks/vendors in database for UI search / suggestion pills."""
    return {"vendors": getattr(entity_resolver, "banks", [])}

@app.get("/api/session/{session_id}")
def get_session_history(session_id: str):
    """Retrieves conversation history for a given session."""
    session = sessions.get(session_id)
    if not session:
        return {"session_id": session_id, "messages": []}
    return {"session_id": session_id, "messages": session.get("history", [])}

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """Main conversational endpoint powered by LangGraph."""
    session_id = request.session_id or str(uuid.uuid4())
    user_query = request.message.strip()

    if not user_query:
        raise HTTPException(status_code=400, detail="Query message cannot be empty.")

    # Retrieve or initialize session state
    session = sessions.setdefault(session_id, {
        "history": [],
        "last_ast": None,
        "pending_confirmation_vendor": None,
        "pending_alias": None,
        "confirmed_entities": {},
        "active_context_vendor": None
    })

    # Check multi-turn confirmation for acronyms (e.g. User replies 'yes' to 'Did you mean Amazon Web Services?')
    pending_vendor = session.get("pending_confirmation_vendor")
    pending_alias = session.get("pending_alias")
    clean_msg = user_query.strip().lower()
    if pending_vendor and clean_msg in ["yes", "confirm", "yup", "yeah", "sure", "correct", "please", "yes please", "do it"]:
        user_query = f"Show spend for {pending_vendor}"
        if pending_alias:
            session["confirmed_entities"][pending_alias] = pending_vendor
        session["active_context_vendor"] = pending_vendor
        for alias in entity_resolver.get_aliases_for_vendor(pending_vendor):
            session["confirmed_entities"][alias] = pending_vendor
        session["pending_confirmation_vendor"] = None
        session["pending_alias"] = None

    # Prepare initial LangGraph state
    initial_state = {
        "session_id": session_id,
        "user_query": user_query,
        "conversation_history": session["history"],
        "last_ast": session.get("last_ast"),
        "session_confirmed_entities": dict(session.get("confirmed_entities") or {}),
        "active_context_vendor": session.get("active_context_vendor"),
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

    # Execute LangGraph workflow
    final_state = financial_agent_graph.invoke(initial_state)

    # Update session memory
    session["history"].append({"role": "user", "content": user_query})
    session["history"].append({"role": "assistant", "content": final_state.get("final_narrative", "")})
    if final_state.get("current_ast"):
        session["last_ast"] = final_state["current_ast"]
    if final_state.get("active_context_vendor"):
        session["active_context_vendor"] = final_state["active_context_vendor"]
    if final_state.get("session_confirmed_entities"):
        session["confirmed_entities"].update(final_state["session_confirmed_entities"])

    # Store pending confirmation if clarification requested
    if final_state.get("needs_clarification") and final_state.get("clarification_options"):
        cand_vendor = final_state["clarification_options"][0]
        session["pending_confirmation_vendor"] = cand_vendor
        session["pending_alias"] = None
        for alias, canonical in entity_resolver.dynamic_aliases.items():
            if canonical == cand_vendor and re.search(r"\b" + re.escape(alias) + r"\b", user_query.lower()):
                session["pending_alias"] = alias
                break
    else:
        session["pending_confirmation_vendor"] = None
        session["pending_alias"] = None

    # Assemble response
    intent_type = final_state.get("intent_type")
    is_conversational = intent_type in ["GREETING", "OUT_OF_SCOPE"]
    needs_clarification = final_state.get("needs_clarification", False)

    confidence_obj = None
    anomaly_obj = None
    audit_trail_obj = None

    if not is_conversational:
        if final_state.get("confidence"):
            confidence_obj = ConfidenceBreakdown(**final_state["confidence"])
        else:
            confidence_obj = ConfidenceBreakdown(
                score=0.0,
                tier="LOW",
                entity_score=0.0,
                ast_score=0.0,
                data_score=0.0,
                explanation="No confidence evaluation"
            )

        if not needs_clarification:
            if final_state.get("anomaly"):
                anomaly_obj = AnomalyInfo(**final_state["anomaly"])
            else:
                anomaly_obj = AnomalyInfo()

            audit_trail_obj = AuditTrail(
                sql_query=final_state.get("compiled_sql") or "N/A",
                execution_time_ms=final_state.get("execution_time_ms", 0.0),
                rows_scanned=final_state.get("row_count", 0),
                model_used=f"8B ({settings.LLM_PROVIDER})"
            )

    summary_metrics = [
        SummaryMetric(label=m["label"], value=m["value"])
        for m in final_state.get("summary_metrics", [])
    ] if not is_conversational and not needs_clarification else []

    status_val = "out_of_scope" if intent_type == "OUT_OF_SCOPE" else (
        "clarification_needed" if needs_clarification else "success"
    )

    return ChatResponse(
        session_id=session_id,
        status=status_val,
        narrative=final_state.get("final_narrative", "Processed request."),
        confidence=confidence_obj,
        anomaly=anomaly_obj,
        summary_metrics=summary_metrics,
        table_data=final_state.get("db_records", []) if not is_conversational and not needs_clarification else [],
        audit_trail=audit_trail_obj,
        clarification_options=final_state.get("clarification_options")
    )
