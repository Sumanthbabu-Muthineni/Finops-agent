import sys
import os
import json
import time
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root_dir))

from backend.engine.db import db
from backend.engine.schema_validator import schema_validator
from backend.engine.query_compiler import query_compiler
from backend.core.models import FinancialQueryAST, EntityFilter

def setup_mock_ecommerce_schema():
    """Injects an isolated non-banking schema into the live database to test dynamicity."""
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        # Drop if exists
        cur.execute("DROP TABLE IF EXISTS mock_ecommerce_orders;")
        cur.execute("DROP TABLE IF EXISTS mock_ecommerce_users;")
        
        # Create users table
        cur.execute("""
            CREATE TABLE mock_ecommerce_users (
                user_id INT PRIMARY KEY,
                username VARCHAR(50),
                signup_date DATE,
                loyalty_tier VARCHAR(20)
            );
        """)
        
        # Create orders table
        cur.execute("""
            CREATE TABLE mock_ecommerce_orders (
                order_id INT PRIMARY KEY,
                user_id INT,
                order_date DATETIME,
                total_price DECIMAL(10, 2),
                order_status VARCHAR(20),
                FOREIGN KEY (user_id) REFERENCES mock_ecommerce_users(user_id)
            );
        """)
        
        # Insert a few mock records so dynamic sampling finds them
        cur.execute("INSERT INTO mock_ecommerce_users VALUES (1, 'Alice', '2025-01-01', 'GOLD'), (2, 'Bob', '2025-01-02', 'SILVER');")
        cur.execute("INSERT INTO mock_ecommerce_orders VALUES (101, 1, '2025-02-01 10:00:00', 150.50, 'SHIPPED'), (102, 2, '2025-02-02 11:00:00', 99.99, 'PENDING');")
        
        cur.close()
    finally:
        db.release_connection(conn)

    # Force the database manager to reload its cache to discover the new tables
    db.reload_data()

def cleanup_mock_ecommerce_schema():
    """Drops the mock ecommerce tables."""
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS mock_ecommerce_orders;")
        cur.execute("DROP TABLE IF EXISTS mock_ecommerce_users;")
        cur.close()
    finally:
        db.release_connection(conn)
        
    db.reload_data()

def test_dynamic_ecommerce_schema_introspection():
    print("\n" + "=" * 75)
    print("TEST 1: Dynamic Discovery of Completely Foreign Schema (eCommerce)")
    print("=" * 75)
    
    profile = db.get_schema_profile()
    
    assert "mock_ecommerce_users" in profile
    assert "mock_ecommerce_orders" in profile
    
    orders_cols = profile["mock_ecommerce_orders"]
    assert "total_price" in orders_cols
    assert "order_status" in orders_cols
    
    # Check that sampling works on new domains
    status_samples = orders_cols["order_status"].get("sample_values", [])
    assert any("SHIPPED" in str(s).upper() for s in status_samples)
    
    fks = db.get_foreign_keys()
    fk_found = any(
        fk["from_table"] == "mock_ecommerce_orders" and 
        fk["to_table"] == "mock_ecommerce_users"
        for fk in fks
    )
    assert fk_found, "Foreign key relationship was not dynamically discovered!"
    
    print("✅ Discovered new tables: mock_ecommerce_users, mock_ecommerce_orders")
    print(f"✅ Discovered columns in orders: {list(orders_cols.keys())}")
    print("✅ Discovered foreign key relationships automatically.")

def test_dynamic_query_compilation_ecommerce():
    print("\n" + "=" * 75)
    print("TEST 2: Compiler and Validator Routing on Foreign Schema")
    print("=" * 75)
    
    # Simulate an LLM generating an AST for the new schema
    ast = FinancialQueryAST(
        target_domain="mock_ecommerce_orders",
        target_metric="sum",
        metric_column="total_price",
        entity_filters=[
            EntityFilter(field="order_status", operator="eq", value="SHIPPED")
        ],
        group_by=["loyalty_tier"],  # Note: this column is in the users table!
        order_by_desc=True,
        limit=10
    )
    
    # Validator should heal and confirm
    healed_ast = schema_validator.validate_and_heal(ast)
    
    # Compiler should automatically figure out the JOIN between orders and users
    # because loyalty_tier is in the users table.
    sql = query_compiler.compile(healed_ast)
    
    print(f"⚙️ Compiled Dynamic SQL:\n{sql}\n")
    
    assert "JOIN `mock_ecommerce_users`" in sql or "JOIN mock_ecommerce_users" in sql, "Compiler failed to auto-join the foreign key!"
    assert "loyalty_tier" in sql
    assert "total_price" in sql
    
    print("✅ Verified: Query Compiler successfully auto-joined foreign schema tables based on required columns without any hardcoding.")


if __name__ == "__main__":
    print("🚀 Initializing Live Database Injection for Dynamic Schema Testing...")
    setup_mock_ecommerce_schema()
    try:
        test_dynamic_ecommerce_schema_introspection()
        test_dynamic_query_compilation_ecommerce()
        print("\n🎉 ALL TRULY DYNAMIC SCHEMA TESTS PASSED SUCCESSFULLY!")
    finally:
        print("🧹 Cleaning up injected mock schema...")
        cleanup_mock_ecommerce_schema()
