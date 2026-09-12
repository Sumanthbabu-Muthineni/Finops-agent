"""
TBX FinOps Assistant - High-Performance 20M Record MySQL Seeder
Optimized for scale using Multi-Processing and chunked bulk inserts.
"""

import os
import sys
import uuid
import time
import random
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count

# Add project root to sys.path
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pymysql
from backend.core.crypto import encrypt_utr
from backend.database.seed_mysql import SAMPLE_BANKS, SAMPLE_ACCOUNTS, SAMPLE_TRANSACTIONS, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

BATCH_SIZE = 50000

def generate_and_insert_chunk(args):
    worker_id, num_records, start_date_ts, total_seconds, account_lookup, account_ids = args
    
    # Connect directly in the worker
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True
    )
    cur = conn.cursor()
    
    start_dt = datetime.fromtimestamp(start_date_ts)
    descriptions = [
        "FT - Vendor Settlement - SELECTION ELECTRONICS",
        "UPI-NAVYUG SELECTION Retail Payment",
        "NEFT Inflow / SELECTION MALIGAI Vendor Settlement",
        "Payment to Cloud Infrastructure Services",
        "IMPS Settlement - Corporate Vendor Disbursements",
        "NEFT - Operating Expenses - Office Lease",
        "Vendor Payout - IT Support & Maintenance",
        "Direct Deposit - Payroll Settlement",
        "AWS Cloud Hosting - Monthly Bill",
        "Stripe Payment Processing Fee"
    ]
    
    random.seed(os.getpid())  # Unique random sequence per process
    
    inserted = 0
    bulk_rows = []
    
    for i in range(num_records):
        t_id = str(uuid.uuid4())
        acc_id = random.choice(account_ids)
        meta = account_lookup[acc_id]
        dt = start_dt + timedelta(seconds=random.randint(0, total_seconds))
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        txn_type = random.choices(["debit", "credit"], weights=[0.75, 0.25])[0]
        amt = round(random.lognormvariate(10.2, 0.7), 2)
        desc = random.choice(descriptions)
        ref_id = f"REF{random.randint(1000000000, 9999999999)}"
        raw_utr = f"jhI5nAdy{random.randint(100000, 999999)}"
        # Mock encryption to save time (encrypt_utr uses AES, we'll bypass actual encryption in bulk script to speed up 20M rows, or just use a dummy static hash if needed, but we'll use encrypt_utr for safety)
        # Using encrypt_utr per row for 20M rows takes immense CPU time.
        # We will use a pre-computed generic dummy utr for the bulk filler since it's just synthetic volume data
        encrypted_utr = "jhI5nAdyb1qOEjmcB3JvWjC6tTO+ZPVqBFPm/GiErC4TRBWRQ5ylPG3p"
        
        bulk_rows.append((
            t_id, acc_id, meta["entity_id"], meta["program_id"],
            dt_str, txn_type, amt, desc, ref_id, encrypted_utr
        ))
        
        if len(bulk_rows) >= BATCH_SIZE:
            cur.executemany("""
                INSERT INTO transaction (transaction_id, account_id, entity_id, program_id, transaction_date, transaction_type, transaction_amount, description, transaction_reference_id, utr_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, bulk_rows)
            inserted += len(bulk_rows)
            bulk_rows = []
            
    if bulk_rows:
        cur.executemany("""
            INSERT INTO transaction (transaction_id, account_id, entity_id, program_id, transaction_date, transaction_type, transaction_amount, description, transaction_reference_id, utr_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, bulk_rows)
        inserted += len(bulk_rows)
        
    cur.close()
    conn.close()
    return inserted


def seed_database_20m(total_records: int = 20000000):
    print(f"🚀 Initializing High-Performance 20M MySQL Seeder to {DB_HOST}:{DB_PORT}...")
    t_start = time.time()
    
    # 1. Setup Base Tables
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True
    )
    cur = conn.cursor()
    print("1. Truncating existing tables...")
    cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
    cur.execute("TRUNCATE TABLE transaction;")
    cur.execute("TRUNCATE TABLE account;")
    cur.execute("TRUNCATE TABLE bank;")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
    
    print("2. Seeding base Banks and Accounts...")
    cur.executemany("INSERT IGNORE INTO bank (bank_code, bank_name) VALUES (%s, %s)", SAMPLE_BANKS)
    
    acc_rows = [(a[0], a[1], a[2], a[5], a[3], a[4]) for a in SAMPLE_ACCOUNTS]
    cur.executemany("""
        INSERT IGNORE INTO account (account_id, entity_id, account_number, bank_code, program_id, available_balance)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, acc_rows)
    
    account_lookup = {a[0]: {"entity_id": a[1], "program_id": a[3]} for a in SAMPLE_ACCOUNTS}
    account_ids = list(account_lookup.keys())
    
    cur.close()
    conn.close()
    
    # 2. Multi-processed Bulk Insert
    print(f"3. Beginning multi-processing bulk generation of {total_records:,} records...")
    start_dt = datetime(2025, 10, 1)
    end_dt = datetime(2026, 6, 24, 18, 0, 0)
    total_seconds = int((end_dt - start_dt).total_seconds())
    
    num_cores = max(1, cpu_count() - 1)
    records_per_worker = total_records // num_cores
    
    # Ensure exact total
    worker_args = []
    remaining = total_records
    for i in range(num_cores):
        chunk = records_per_worker if i < num_cores - 1 else remaining
        worker_args.append((i, chunk, start_dt.timestamp(), total_seconds, account_lookup, account_ids))
        remaining -= chunk

    print(f"   ⚡ Spawning {num_cores} worker processes (approx {records_per_worker:,} rows each)")
    print(f"   ⏳ This may take several minutes. Please do not close the terminal.")
    
    with Pool(num_cores) as p:
        results = p.map(generate_and_insert_chunk, worker_args)
        
    total_inserted = sum(results)
    elapsed = time.time() - t_start
    
    print(f"\\n🎉 Successfully inserted {total_inserted:,} transaction records in {elapsed:.2f} seconds.")
    print(f"📊 Throughput: {total_inserted/elapsed:,.0f} rows/second")


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20000000
    seed_database_20m(count)
