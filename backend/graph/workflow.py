from langgraph.graph import StateGraph, END
from backend.graph.state import FinancialAgentState
from backend.graph.nodes import (
    intent_and_entity_node,
    ast_generator_node,
    sql_compiler_node,
    db_execution_and_iqr_node,
    confidence_gate_node,
    clarification_node,
    synthesizer_node
)

def should_clarify(state: FinancialAgentState) -> str:
    """Conditional router function for LangGraph."""
    if state.get("needs_clarification", False):
        return "clarification"
    return "synthesizer"

def route_after_intent(state: FinancialAgentState) -> str:
    """Routes greetings, out-of-scope, and acronym confirmations immediately to END, bypassing database queries."""
    intent_type = state.get("intent_type")
    if intent_type in ["GREETING", "OUT_OF_SCOPE"]:
        return "end"
    if state.get("needs_clarification") and state.get("final_narrative"):
        return "end"
    return "ast_generator"

def create_financial_agent_graph():
    """Builds and compiles the production LangGraph state machine."""
    workflow = StateGraph(FinancialAgentState)

    # 1. Register Nodes
    workflow.add_node("intent_and_entity", intent_and_entity_node)
    workflow.add_node("ast_generator", ast_generator_node)
    workflow.add_node("sql_compiler", sql_compiler_node)
    workflow.add_node("db_execution_and_iqr", db_execution_and_iqr_node)
    workflow.add_node("confidence_gate", confidence_gate_node)
    workflow.add_node("clarification", clarification_node)
    workflow.add_node("synthesizer", synthesizer_node)

    # 2. Define Edges
    workflow.set_entry_point("intent_and_entity")
    workflow.add_conditional_edges(
        "intent_and_entity",
        route_after_intent,
        {
            "end": END,
            "ast_generator": "ast_generator"
        }
    )
    workflow.add_edge("ast_generator", "sql_compiler")
    workflow.add_edge("sql_compiler", "db_execution_and_iqr")
    workflow.add_edge("db_execution_and_iqr", "confidence_gate")

    # 3. Conditional Branch from Confidence Gate
    workflow.add_conditional_edges(
        "confidence_gate",
        should_clarify,
        {
            "clarification": "clarification",
            "synthesizer": "synthesizer"
        }
    )

    workflow.add_edge("clarification", END)
    workflow.add_edge("synthesizer", END)

    return workflow.compile()

financial_agent_graph = create_financial_agent_graph()
