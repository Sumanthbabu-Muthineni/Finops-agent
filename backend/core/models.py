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
    target_domain: str = Field(
        "transactions", description="Target database table or view name (e.g. v_transactions, transactions, accounts, orders)"
    )
    target_metric: Literal[
        "total_amount", "available_balance", "average_amount", "record_count", "records_list",
        "sum", "average", "count", "min", "max"
    ] = Field(
        "total_amount", description="Core aggregation metric or raw line items"
    )
    metric_column: Optional[str] = Field(
        None, description="Optional target numeric column to aggregate (e.g. transaction_amount, available_balance, amount)"
    )
    date_column: Optional[str] = Field(
        None, description="Optional temporal column for date range filtering (e.g. transaction_date, created_at)"
    )
    entity_filters: List[EntityFilter] = Field(
        default_factory=list, description="Column match constraints: column name, operator, and value"
    )
    date_range: Optional[DateRangeFilter] = Field(
        None, description="Normalized ISO date boundaries"
    )
    group_by: Optional[List[str]] = Field(
        default_factory=list, description="Categorical or temporal grouping columns"
    )
    order_by_desc: bool = Field(
        True, description="Order results descending"
    )
    limit: int = Field(
        100, ge=1, le=1000, description="Max rows returned to prevent client overflow"
    )

AnalyticalQueryAST = FinancialQueryAST

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
    index_status: Optional[str] = None
    advisories: List[str] = Field(default_factory=list)

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

class ConnectDbRequest(BaseModel):
    session_id: Optional[str] = None
    host: str
    port: int = 3306
    user: Optional[str] = None
    username: Optional[str] = None
    password: str = ""
    database: str
    ssl: bool = False

class ConnectDbResponse(BaseModel):
    success: bool
    session_id: str
    database: str
    host: str
    port: int
    tables_count: int
    tables: List[str]
    total_rows: int
    advisor_report: Optional[Dict[str, Any]] = None
    message: str

class DisconnectDbResponse(BaseModel):
    success: bool
    session_id: str
    message: str
