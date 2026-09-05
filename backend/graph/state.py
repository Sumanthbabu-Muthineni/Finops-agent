from typing import TypedDict, Optional, List, Dict, Any

class FinancialAgentState(TypedDict):
    session_id: str
    user_query: str
    conversation_history: List[Dict[str, str]]
    last_ast: Optional[Dict[str, Any]]
    
    # Entity Resolution & Multi-Turn Session Memory
    intent_type: Optional[str]
    session_confirmed_entities: Optional[Dict[str, str]]
    active_context_vendor: Optional[str]
    resolved_vendor: Optional[str]
    entity_score: float
    target_domain: Optional[str]
    
    # Grammar-Constrained AST & SQL
    current_ast: Optional[Dict[str, Any]]
    compiled_sql: Optional[str]
    records_sql: Optional[str]
    
    # Execution & Analytics
    db_records: List[Dict[str, Any]]
    summary_metrics: List[Dict[str, str]]
    breakdown_items: Optional[List[Dict[str, Any]]]
    row_count: int
    execution_time_ms: float
    
    # Statistical Anomaly & Confidence Scoring
    anomaly: Optional[Dict[str, Any]]
    confidence: Optional[Dict[str, Any]]
    
    # Guardrails & Output
    needs_clarification: bool
    clarification_options: Optional[List[str]]
    final_narrative: Optional[str]
    status: str
