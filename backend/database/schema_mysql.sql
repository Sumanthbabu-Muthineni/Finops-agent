-- ==============================================================================
-- TBX FinOps Assistant - MySQL Production Relational Schema DDL
-- Scoped to official 3-Table Schema (bank, account, transaction)
-- Includes B-Tree Indexes for 20M-80M Scale and Analytical Views with Masking
-- ==============================================================================

-- 1. Base Tables
DROP VIEW IF EXISTS v_transactions;
DROP VIEW IF EXISTS v_accounts;
DROP VIEW IF EXISTS v_banks;

DROP TABLE IF EXISTS transaction;
DROP TABLE IF EXISTS account;
DROP TABLE IF EXISTS bank;

-- Table 1: Bank Master Table
CREATE TABLE bank (
    bank_code VARCHAR(32) PRIMARY KEY,
    bank_name VARCHAR(255) NOT NULL
);

-- Table 2: Account Master Table
CREATE TABLE account (
    account_id VARCHAR(64) PRIMARY KEY,
    entity_id VARCHAR(64) NOT NULL,
    account_number VARCHAR(64) NOT NULL,
    bank_code VARCHAR(32) NOT NULL,
    program_id BIGINT NOT NULL,
    available_balance DOUBLE NOT NULL,
    FOREIGN KEY (bank_code) REFERENCES bank(bank_code)
);

-- Table 3: Transaction Ledger Table
CREATE TABLE transaction (
    transaction_id VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    program_id BIGINT NOT NULL,
    transaction_date DATETIME NOT NULL,
    transaction_type VARCHAR(32) NOT NULL, -- 'credit', 'debit'
    transaction_amount DOUBLE NOT NULL,
    description TEXT,
    transaction_reference_id VARCHAR(128) NOT NULL,
    utr_number VARCHAR(255),
    FOREIGN KEY (account_id) REFERENCES account(account_id)
);

-- ==============================================================================
-- 2. High-Performance B-Tree Indexes (20M-80M Rows Scalability)
-- ==============================================================================
CREATE INDEX idx_txn_date ON transaction(transaction_date);
CREATE INDEX idx_txn_ref ON transaction(transaction_reference_id);
CREATE INDEX idx_txn_type ON transaction(transaction_type);
CREATE INDEX idx_txn_account ON transaction(account_id);
CREATE INDEX idx_account_bank ON account(bank_code);
CREATE INDEX idx_bank_name ON bank(bank_name);

-- Composite Indexes for High-Frequency FinOps Queries
CREATE INDEX idx_txn_date_type ON transaction(transaction_date, transaction_type);
CREATE INDEX idx_txn_account_date ON transaction(account_id, transaction_date);

-- ==============================================================================
-- 3. Analytical Semantic Views (With Built-In Sensitive Data Masking)
-- ==============================================================================

-- View 1: Transaction Details with Dynamic Masking and Calendar Aliases
CREATE OR REPLACE VIEW v_transactions AS
SELECT 
    t.transaction_id,
    t.account_id,
    a.entity_id,
    CONCAT('****', RIGHT(a.account_number, 4)) AS masked_account_number,
    CONCAT('****', RIGHT(a.account_number, 4)) AS account_number, -- Masked for complete safety
    b.bank_code,
    b.bank_name,
    a.program_id,
    t.transaction_date,
    DATE(t.transaction_date) AS transaction_day,
    LOWER(t.transaction_type) AS transaction_type,
    t.transaction_amount,
    t.transaction_amount AS amount,
    t.description,
    t.transaction_reference_id,
    t.transaction_reference_id AS reference_id,
    t.utr_number AS masked_utr_number,
    t.utr_number,
    a.available_balance,
    YEAR(t.transaction_date) AS txn_year,
    MONTH(t.transaction_date) AS txn_month
FROM transaction t
JOIN account a ON t.account_id = a.account_id
JOIN bank b ON a.bank_code = b.bank_code;

-- View 2: Account Balances View
CREATE OR REPLACE VIEW v_accounts AS
SELECT 
    a.account_id,
    a.entity_id,
    CONCAT('****', RIGHT(a.account_number, 4)) AS masked_account_number,
    CONCAT('****', RIGHT(a.account_number, 4)) AS account_number,
    a.bank_code,
    b.bank_name,
    a.program_id,
    a.available_balance,
    a.available_balance AS balance
FROM account a
JOIN bank b ON a.bank_code = b.bank_code;

-- View 3: Bank Summary View
CREATE OR REPLACE VIEW v_banks AS
SELECT 
    b.bank_code,
    b.bank_name,
    COUNT(a.account_id) AS account_count,
    ROUND(COALESCE(SUM(a.available_balance), 0), 2) AS total_available_balance
FROM bank b
LEFT JOIN account a ON b.bank_code = a.bank_code
GROUP BY b.bank_code, b.bank_name;
