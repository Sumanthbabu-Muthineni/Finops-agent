from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, Field
from datetime import date

# ------------------------------------------------------------------------------
# 1. Grammar-Constrained AST Models
# ------------------------------------------------------------------------------

class EntityFilter(BaseModel):
    field: str = Field(..., description="Target database column: vendor_name, status, category, account_name")
    operator: Literal["eq", "neq", "in", "like", "gt", "lt", "gte", "lte"] = Field(
        "eq", description="SQL comparison operator"
    )
    value: Any = Field(..., description="Filter literal or list of literals")

class DateRangeFilter(BaseModel):
    start_date: Optional[str] = Field(None, description="ISO format YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="ISO format YYYY-MM-DD")

class FinancialQueryAST(BaseModel):
    target_domain: Literal["transactions", "accounts", "banks", "vendor_payouts"] = Field(
        "transactions", description="Primary semantic domain view to query: transactions, accounts, banks"
    )
    target_metric: Literal["total_amount", "available_balance", "average_amount", "record_count", "records_list"] = Field(
        "total_amount", description="Core aggregation metric or raw line items"
    )
    entity_filters: List[EntityFilter] = Field(
        default_factory=list, description="Fuzzy/exact entity match constraints: bank_name, bank_code, transaction_type, program_id, etc."
    )
    date_range: Optional[DateRangeFilter] = Field(
        None, description="Normalized ISO date boundaries"
    )
    group_by: Optional[List[str]] = Field(
        default_factory=list, description="Categorical or temporal grouping: transaction_type, bank_name, program_id, month"
    )
    order_by_desc: bool = Field(
        True, description="Order results by metric/date descending"
    )
    limit: int = Field(
        100, ge=1, le=1000, description="Max rows returned to prevent client overflow"
    )

# ------------------------------------------------------------------------------
# 2. UI & API Response Contracts
# ------------------------------------------------------------------------------

class AnomalyInfo(BaseModel):
    detected: bool = False
    field: str = "amount"
    outlier_value: Optional[float] = None
    typical_range: Optional[str] = None
    affected_rows: int = 0
    message: Optional[str] = None

class ConfidenceBreakdown(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    tier: Literal["HIGH", "MEDIUM", "LOW"]
    entity_score: float
    ast_score: float
    data_score: float
    explanation: str

class SummaryMetric(BaseModel):
    label: str
    value: str

class AuditTrail(BaseModel):
    sql_query: str
    execution_time_ms: float
    rows_scanned: int
    model_used: str

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str

class ChatResponse(BaseModel):
    session_id: str
    status: Literal["success", "clarification_needed", "out_of_scope", "error"]
    narrative: str
    confidence: Optional[ConfidenceBreakdown] = None
    anomaly: Optional[AnomalyInfo] = None
    summary_metrics: List[SummaryMetric] = Field(default_factory=list)
    table_data: List[Dict[str, Any]] = Field(default_factory=list)
    audit_trail: Optional[AuditTrail] = None
    clarification_options: Optional[List[str]] = None
