# Data Models, AST Schemas & Database Specifications

This document defines the complete technical specifications for:
1. **Relational Database Schemas & DuckDB Views**
2. **Pydantic V2 Abstract Syntax Tree (AST) Models**
3. **Verifiable API Response Contracts**
4. **AST-to-SQL Compilation & Parameterization Rules**

---

## 1. Relational Database Schemas (TBX 3-Table Connected Banking)

The FinOps Assistant operates directly over the official 3-table relational schema defined in `TBX - Database Schema.md`. DuckDB parses these datasets via its high-performance C++ vectorized CSV reader into in-memory tables and semantic views.

### 1.1 Base Tables DDL

```sql
-- 1. Bank Master Table
CREATE TABLE bank (
    bank_code VARCHAR PRIMARY KEY,  -- e.g. 'HDFC', 'SBIN', 'ICIC', 'UTIB', 'KKBK'
    bank_name VARCHAR NOT NULL      -- e.g. 'HDFC BANK LIMITED', 'STATE BANK OF INDIA'
);

-- 2. Account Master Table
CREATE TABLE account (
    account_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR NOT NULL,
    account_number VARCHAR NOT NULL, -- Sensitive: masked to ****<last_4> in analytical views
    bank_code VARCHAR NOT NULL REFERENCES bank(bank_code),
    program_id BIGINT NOT NULL,
    balance DOUBLE PRECISION NOT NULL
);

-- 3. Transaction Ledger Table
CREATE TABLE transaction (
    transaction_id VARCHAR PRIMARY KEY,
    account_id VARCHAR NOT NULL REFERENCES account(account_id),
    entity_id VARCHAR NOT NULL,
    program_id BIGINT NOT NULL,
    transaction_date TIMESTAMP NOT NULL,
    transaction_type VARCHAR NOT NULL, -- 'credit', 'debit'
    amount DOUBLE PRECISION NOT NULL,
    description VARCHAR,
    transaction_reference_id VARCHAR NOT NULL, -- Plaintext searchable identifier
    utr_number VARCHAR                         -- Sensitive: masked in analytical views
);
```

---

### 1.2 Analytical Semantic Views (DuckDB OLAP)

```sql
-- View 1: Transaction Details with Dynamic Masking and Calendar Aliases
CREATE OR REPLACE VIEW v_transactions AS
SELECT 
    t.transaction_id,
    t.account_id,
    a.entity_id,
    CONCAT('****', SUBSTRING(CAST(a.account_number AS VARCHAR), -4)) AS masked_account_number,
    b.bank_code,
    b.bank_name,
    a.program_id,
    t.transaction_date,
    CAST(t.transaction_date AS DATE) AS transaction_day,
    LOWER(t.transaction_type) AS transaction_type,
    t.transaction_amount,
    t.transaction_amount AS amount,
    t.description,
    t.transaction_reference_id,
    t.transaction_reference_id AS reference_id,
    CASE 
        WHEN t.utr_number IS NOT NULL AND LENGTH(CAST(t.utr_number AS VARCHAR)) > 8 
        THEN CONCAT(SUBSTRING(CAST(t.utr_number AS VARCHAR), 1, 8), '...') 
        ELSE CAST(t.utr_number AS VARCHAR) 
    END AS masked_utr_number,
    a.available_balance,
    EXTRACT(YEAR FROM t.transaction_date) AS txn_year,
    EXTRACT(MONTH FROM t.transaction_date) AS txn_month
FROM transaction t
LEFT JOIN account a ON t.account_id = a.account_id
LEFT JOIN bank b ON a.bank_code = b.bank_code;

-- View 2: Account Balances View
CREATE OR REPLACE VIEW v_accounts AS
SELECT 
    a.account_id,
    a.entity_id,
    CONCAT('****', SUBSTRING(CAST(a.account_number AS VARCHAR), -4)) AS masked_account_number,
    a.bank_code,
    b.bank_name,
    a.program_id,
    a.available_balance,
    a.available_balance AS balance
FROM account a
LEFT JOIN bank b ON a.bank_code = b.bank_code;

-- View 3: Bank Summary View
CREATE OR REPLACE VIEW v_banks AS
SELECT 
    b.bank_code,
    b.bank_name,
    COUNT(a.account_id) AS account_count,
    ROUND(SUM(a.available_balance), 2) AS total_available_balance
FROM bank b
LEFT JOIN account a ON b.bank_code = a.bank_code
GROUP BY b.bank_code, b.bank_name;
```

---

## 2. Pydantic V2 Abstract Syntax Tree (AST) Models

These schemas govern the structured decoding of the lightweight LLM.

```python
from __future__ import annotations
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, field_validator

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class TargetDomain(str, Enum):
    VENDOR_PAYOUTS = "VENDOR_PAYOUTS"
    TRANSACTIONS = "TRANSACTIONS"
    RECONCILIATION = "RECONCILIATION"

class TargetMetric(str, Enum):
    SUM_AMOUNT = "SUM_AMOUNT"
    COUNT_RECORDS = "COUNT_RECORDS"
    AVG_AMOUNT = "AVG_AMOUNT"
    LIST_RECORDS = "LIST_RECORDS"
    UNRECONCILED_BALANCE = "UNRECONCILED_BALANCE"

class RelativePeriod(str, Enum):
    LAST_MONTH = "LAST_MONTH"
    THIS_MONTH = "THIS_MONTH"
    CURRENT_QUARTER = "CURRENT_QUARTER"
    LAST_QUARTER = "LAST_QUARTER"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    YTD = "YTD"
    LAST_YEAR = "LAST_YEAR"
    ALL_TIME = "ALL_TIME"
    CUSTOM = "CUSTOM"

class ReconciliationStatusFilter(str, Enum):
    ALL = "ALL"
    RECONCILED = "RECONCILED"
    UNRECONCILED = "UNRECONCILED"
    PENDING = "PENDING"

class GroupByDimension(str, Enum):
    VENDOR = "VENDOR"
    MONTH = "MONTH"
    CATEGORY = "CATEGORY"
    STATUS = "STATUS"

# -----------------------------------------------------------------------------
# Date Range Model
# -----------------------------------------------------------------------------

class DateRangeAST(BaseModel):
    relative_period: RelativePeriod = Field(
        default=RelativePeriod.ALL_TIME,
        description="Standardized relative time window"
    )
    year: Optional[int] = Field(
        default=None,
        description="Explicit calendar year if requested (e.g., 2024)"
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Exact ISO start date YYYY-MM-DD if explicit"
    )
    end_date: Optional[str] = Field(
        default=None,
        description="Exact ISO end date YYYY-MM-DD if explicit"
    )

# -----------------------------------------------------------------------------
# Master Financial Query AST
# -----------------------------------------------------------------------------

class FinancialQueryAST(BaseModel):
    target_domain: TargetDomain = Field(
        ...,
        description="Target dataset domain for query routing"
    )
    target_metric: TargetMetric = Field(
        default=TargetMetric.SUM_AMOUNT,
        description="Analytical metric to compute"
    )
    entity_filters: List[str] = Field(
        default_factory=list,
        description="List of canonical vendor or account names"
    )
    account_categories: List[str] = Field(
        default_factory=list,
        description="Chart of account categories (e.g., 'Cloud Infrastructure')"
    )
    date_range: DateRangeAST = Field(
        default_factory=DateRangeAST,
        description="Temporal bounds"
    )
    status_filter: ReconciliationStatusFilter = Field(
        default=ReconciliationStatusFilter.ALL,
        description="Filter by reconciliation status"
    )
    group_by: List[GroupByDimension] = Field(
        default_factory=list,
        description="Dimensions to group by"
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum breakdown records to return"
    )
```

---

## 3. Verifiable Response Contract

Every response emitted by the backend adheres to this strict contract, providing complete verifiability, tabular records, audit lineage, and confidence scores.

```python
class AnomalyRecord(BaseModel):
    flagged: bool = True
    record_id: str
    vendor_name: str
    amount: float
    historical_median: float
    iqr_upper_bound: float
    deviation_ratio: float
    note: str

class ConfidenceBreakdown(BaseModel):
    composite_score: float = Field(..., ge=0.0, le=1.0)
    entity_grounding_score: float = Field(..., ge=0.0, le=1.0)
    ast_alignment_score: float = Field(..., ge=0.0, le=1.0)
    data_presence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_tier: str = Field(..., description="'HIGH', 'MODERATE', 'LOW'")

class QueryAuditTrail(BaseModel):
    compiled_sql: str
    execution_latency_ms: float
    rows_retrieved: int
    target_view: str
    anchor_date_applied: str

class ComputedMetrics(BaseModel):
    metric_name: str
    scalar_value: float
    formatted_value: str
    currency: str = "USD"
    record_count: int

class VerifiableResponsePayload(BaseModel):
    natural_language_answer: str
    key_findings: List[str]
    computed_metrics: ComputedMetrics
    table_breakdown: List[Dict[str, Any]]
    anomalies_detected: List[AnomalyRecord]
    confidence: ConfidenceBreakdown
    audit_trail: QueryAuditTrail
    export_ready: bool = True
```

---

## 4. AST-to-SQL Compiler Mapping Rules

The AST compiler deterministic maps the Pydantic AST into ANSI SQL queries targeting DuckDB.

### 4.1 View Selection Matrix
| `target_domain` | Target DuckDB View | Date Column | Primary Metric Column |
| :--- | :--- | :--- | :--- |
| `transactions` | `v_transactions` | `transaction_date` | `transaction_amount` |
| `accounts` | `v_accounts` | N/A | `available_balance` |
| `banks` | `v_banks` | N/A | `total_available_balance` |

### 4.2 Where Clause Generation Rules
1. **Bank & Entity Filters**:
   ```sql
   AND UPPER(CAST(bank_name AS VARCHAR)) = UPPER('HDFC BANK LIMITED')
   ```
2. **Transaction Type / Program Filters**:
   ```sql
   AND UPPER(CAST(transaction_type AS VARCHAR)) = UPPER('debit')
   AND program_id = 21
   ```
3. **Reference ID Exact Search**:
   ```sql
   AND UPPER(CAST(transaction_reference_id AS VARCHAR)) = UPPER('1715499972')
   ```
4. **Date Bounds**:
   ```sql
   AND transaction_date >= '2026-06-01' AND transaction_date <= '2026-06-30'
   ```

### 4.3 KPI vs Breakdown Queries
The compiler generates two synchronized queries:

**1. Primary KPI Query (Scalar Metric or Group-By Breakdown)**:
```sql
SELECT 
    transaction_type, 
    ROUND(SUM(transaction_amount), 2) AS total_amount, 
    COUNT(*) AS record_count 
FROM v_transactions 
WHERE transaction_date >= '2026-06-01' AND transaction_date <= '2026-06-30' 
GROUP BY transaction_type 
ORDER BY total_amount DESC 
LIMIT 100;
```

**2. Drill-Down Line Items Query (UI Table & CSV Export)**:
```sql
SELECT * 
FROM v_transactions 
WHERE UPPER(CAST(transaction_reference_id AS VARCHAR)) = UPPER('1715499972') 
ORDER BY transaction_date DESC 
LIMIT 100;
```
