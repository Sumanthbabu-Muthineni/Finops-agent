# Sample Question Benchmark, Multi-Turn Scenarios & Evaluation Guide

This document defines the evaluation test suite for the **TBX FinOps Assistant**. It contains 10 rigorous test scenarios spanning single-turn questions, multi-turn drill downs, anomaly alerts, edge cases, and guardrail tests.

---

## Benchmark Scenario Matrix

| Scenario # | Category | User Query / Dialogue Flow | Key Tested Capability |
| :--- | :--- | :--- | :--- |
| **1** | Single-Turn Spend | *"How much did we spend on Stripe payouts last month?"* | Relative date anchor + vendor resolution |
| **2** | Single-Turn Reconciliation | *"Which transactions are still unreconciled from Q2?"* | Status filter + drill-down line items |
| **3** | Single-Turn Category | *"What was our total spend on Cloud Infrastructure in 2024?"* | Chart of Accounts category aggregation |
| **4** | Multi-Turn Sequence | **T1**: *"How much did we pay AWS in Q2?"*<br>**T2**: *"What about last month?"*<br>**T3**: *"Break it down by reconciliation status"* | Context preservation & AST Delta Merger |
| **5** | Anomaly Detection | *"Show all payouts to Datadog in May 2024"* | IQR statistical outlier detection ($Q_3 + 1.5\cdot\text{IQR}$) |
| **6** | Zero-Row Edge Case | *"What was our spend on Snowflake in January 2023?"* | Hard halt on missing data, zero hallucination |
| **7** | Ambiguous Entity | *"How much went to Amzn?"* | Fuzzy score in [65, 84] triggering clarification |
| **8** | Unresolved Entity | *"Show transactions for Wakanda Tech Ltd"* | Entity score < 65, graceful unknown entity handling |
| **9** | Out-of-Scope Guardrail | *"Write a poem about financial ledgers"* | Semantic router rejection |
| **10** | Metadata Discovery | *"What vendor categories do we currently track?"* | Direct metadata schema query |

---

## Detailed Test Scenarios

### Scenario 1: Single-Turn Vendor Payout
- **User Prompt**: *"How much did we spend on Stripe payouts last month?"*
- **Context**: Dataset Anchor Date = `2024-10-15` $\rightarrow$ `LAST_MONTH` = `2024-09-01` to `2024-09-30`.
- **Entity Resolution**: `Stripe` $\rightarrow$ canonical `Stripe Inc` (Score: 100).
- **Generated AST**:
  ```json
  {
    "target_domain": "VENDOR_PAYOUTS",
    "target_metric": "SUM_AMOUNT",
    "entity_filters": ["Stripe Inc"],
    "date_range": { "relative_period": "LAST_MONTH" },
    "status_filter": "ALL",
    "group_by": [],
    "limit": 50
  }
  ```
- **Compiled SQL**:
  ```sql
  SELECT 
      COALESCE(SUM(amount), 0.00) AS total_amount,
      COUNT(*) AS record_count
  FROM v_vendor_payouts
  WHERE LOWER(vendor_name) = 'stripe inc'
    AND payout_date BETWEEN '2024-09-01' AND '2024-09-30';
  ```
- **Synthesized Response**:
  > "In September 2024 (last month), total vendor payouts to **Stripe Inc** were **$42,500.00** across **14 transactions**."
- **Confidence Score**: $C = 0.4(1.0) + 0.3(1.0) + 0.3(1.0) = \mathbf{1.00}$ (Tier: HIGH).

---

### Scenario 2: Single-Turn Reconciliation Status
- **User Prompt**: *"Which transactions are still unreconciled from Q2?"*
- **Context**: Anchor Date = `2024-10-15` $\rightarrow$ `Q2` = `2024-04-01` to `2024-06-30`.
- **Generated AST**:
  ```json
  {
    "target_domain": "RECONCILIATION",
    "target_metric": "LIST_RECORDS",
    "entity_filters": [],
    "date_range": { "relative_period": "Q2", "year": 2024 },
    "status_filter": "UNRECONCILED",
    "group_by": [],
    "limit": 50
  }
  ```
- **Compiled SQL**:
  ```sql
  SELECT 
      transaction_id,
      transaction_date,
      vendor_name,
      amount,
      account_category,
      reconciliation_status
  FROM v_transactions_reconciliation
  WHERE reconciliation_status = 'UNRECONCILED'
    AND transaction_date BETWEEN '2024-04-01' AND '2024-06-30'
  ORDER BY transaction_date DESC
  LIMIT 50;
  ```
- **Synthesized Response**:
  > "There are **7 unreconciled transactions** in Q2 2024 totaling **$18,420.50**. The largest item is **$8,100.00** for Cloud Infrastructure on 2024-05-12."
- **UI Behavior**: AgGrid table renders all 7 rows with a 1-click **Export to CSV** button.

---

### Scenario 3: Multi-Turn Conversation Drill-Down
A three-turn dialogue testing context carryover, delta updates, and drill-downs:

#### Turn 1
- **User**: *"How much did we pay AWS in Q2?"*
- **AST**: `{domain: "VENDOR_PAYOUTS", vendor: "AWS", period: "Q2", metric: "SUM_AMOUNT"}`
- **Answer**: *"In Q2 2024, total payouts to AWS were $84,300.00 across 3 monthly invoices."*

#### Turn 2 (Temporal Delta)
- **User**: *"What about last month?"*
- **Session Merger Action**: Overwrites `period: "LAST_MONTH"`, retains `vendor: "AWS"`, retains `domain: "VENDOR_PAYOUTS"`.
- **Compiled SQL**: Searches AWS payouts in September 2024.
- **Answer**: *"In September 2024 (last month), payouts to AWS totaled $29,100.00."*

#### Turn 3 (Dimensional Breakdown Delta)
- **User**: *"Break it down by payment method and status"*
- **Session Merger Action**: Retains `vendor: "AWS"`, retains `period: "LAST_MONTH"`, sets `group_by: ["STATUS"]`.
- **Answer**: *"Here is the breakdown for AWS in September 2024: $29,100.00 total via ACH (100% Reconciled)."*

---

### Scenario 4: Statistical Anomaly Detection (IQR Hook)
- **User Prompt**: *"Show all payouts to Datadog in May 2024"*
- **Engine Execution**:
  - DuckDB returns 2 payouts in May 2024: `$4,200.00` on May 4, and `$28,400.00` on May 18.
  - IQR Hook analyzes historical baseline for Datadog ($N=18$ prior months):
    - $Q_1 = \$3,800.00$
    - $Q_3 = \$5,100.00$
    - $\text{IQR} = \$1,300.00$
    - $\text{Threshold}_{\text{upper}} = Q_3 + 1.5 \cdot \text{IQR} = \$5,100 + \$1,950 = \mathbf{\$7,050.00}$
  - Payout `TX_9102` ($28,400.00) exceeds threshold by **4.0x**!
- **Synthesized Response**:
  > "In May 2024, total payouts to Datadog were **$32,600.00** across 2 transactions.  
  > ⚠️ **Anomaly Detected**: Payout `TX_9102` for **$28,400.00** on 2024-05-18 is significantly higher than Datadog's historical upper threshold ($7,050.00)."
- **UI Element**: An alert banner renders in amber above the interactive table.

---

### Scenario 5: Missing Data / Zero-Row Return
- **User Prompt**: *"What was our spend on Snowflake in January 2023?"*
- **Execution**:
  - Entity `Snowflake` matches canonical vendor `Snowflake Computing`.
  - Date window: `2023-01-01` to `2023-01-31`.
  - DuckDB query returns **0 rows**.
- **Scoring**: $S_{\text{data}} = 0.0 \rightarrow$ Short-circuit synthesis.
- **Synthesized Output**:
  > "No payout records or transactions were found for **Snowflake Computing** in January 2023. Our records for this vendor begin in June 2023."
- **Confidence Score**: $C = 0.4(1.0) + 0.3(1.0) + 0.3(0.0) = \mathbf{0.70}$ (Titled: ZERO_DATA).

---

### Scenario 6: Ambiguous Entity Clarification
- **User Prompt**: *"How much did we pay to Amzn?"*
- **Entity Resolution**:
  - `Amzn` yields fuzzy matches:
    - `Amazon Web Services` (Ratio: 74)
    - `Amazon Retail Services` (Ratio: 71)
  - Scores fall in ambiguity band $[65, 84]$.
- **Action**: Halt query pipeline; trigger Clarification Gate.
- **Synthesized Output**:
  > "I found multiple vendors matching 'Amzn':  
  > • **Amazon Web Services (AWS)**  
  > • **Amazon Retail Services**  
  > Which vendor's records would you like to review?"

---

### Scenario 7: Out-of-Scope Guardrail
- **User Prompt**: *"Write a poem about balance sheets"*
- **Router Classification**: `OUT_OF_SCOPE`.
- **Synthesized Output**:
  > "I am a dedicated Financial Operations assistant specialized in analyzing vendor spend, transactions, and reconciliation status. I cannot assist with creative writing, but I'm ready to answer any questions about your financial data."

---

## Evaluation Benchmark Summary

| Rubric Dimension | Evaluated In Scenarios | Verified Behavior |
| :--- | :--- | :--- |
| **Accuracy & Grounding (30%)** | Scenarios 1, 2, 3, 5, 6 | 100% of figures match DuckDB sums; zero LLM arithmetic; 0-row query halts cleanly. |
| **Model Efficiency (20%)** | All Scenarios | Strict Pydantic JSON decoding on 8B model; latency <600ms; prompt tokens <300. |
| **NLU & Multi-Turn (15%)** | Scenarios 1, 3, 4, 7 | Context carried over 3 turns; fuzzy resolution on typos; clean delta updates. |
| **Functionality (15%)** | Scenarios 1, 2, 4, 5 | Drill-down tables, CSV export ready, SQL query trace displayed. |
| **User Experience (10%)** | Scenarios 2, 4, 5, 6 | KPI metric cards, AgGrid sorting, amber anomaly alert banner. |
| **Bonus Features** | Scenarios 4, 5, 6 | Mathematical confidence score calculation + IQR outlier flagging. |
