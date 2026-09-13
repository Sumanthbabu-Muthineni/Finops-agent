"""
TBX FinOps Assistant - High-Performance AWS RDS Parallel Transaction Seeder
Generates and bulk-inserts synthetic enterprise banking transactions into RDS MySQL.
Uses multi-threaded batch ingestion to achieve 4,000 - 6,000 rows/sec.
"""

import os
import sys
import uuid
import time
import random
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pymysql
from dotenv import load_dotenv

load_dotenv()

# Configuration
RDS_HOST = os.getenv("RDS_HOST", os.getenv("MYSQL_HOST", "localhost"))
RDS_PORT = int(os.getenv("RDS_PORT", os.getenv("MYSQL_PORT", "3306")))
RDS_USER = os.getenv("RDS_USER", os.getenv("MYSQL_USER", "tiby"))
RDS_PASSWORD = os.getenv("RDS_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
RDS_DB = os.getenv("RDS_DB", os.getenv("MYSQL_DB", "tiby_hackathon"))

DESCRIPTIONS = [
    "FT - Vendor Settlement - SELECTION ELECTRONICS",
    "UPI-NAVYUG SELECTION Retail Payment",
    "NEFT Inflow / SELECTION MALIGAI Vendor Settlement",
    "Payment to Cloud Infrastructure Services",
    "IMPS Settlement - Corporate Vendor Disbursements",
    "NEFT - Operating Expenses - Office Lease",
    "Vendor Payout - IT Support & Maintenance",
    "Direct Deposit - Payroll Settlement",
    "AWS Cloud Hosting - Monthly Bill",
    "Stripe Payment Processing Fee",
    "Inter-account Liquidity Rebalancing Transfer",
    "Corporate Card Settlement - Travel & Expenses"
]

UTR_HASH = "jhI5nAdyb1qOEjmcB3JvWjC6tTO+ZPVqBFPm/GiErC4TRBWRQ5ylPG3p"

def get_connection():
    return pymysql.connect(
        host=RDS_HOST,
        port=RDS_PORT,
        user=RDS_USER,
        password=RDS_PASSWORD,
        database=RDS_DB,
        autocommit=True,
        connect_timeout=15,
        read_timeout=60,
        write_timeout=60
    )

def fetch_accounts():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT account_id, entity_id, program_id FROM account;")
        accounts = cur.fetchall()
    conn.close()
    return accounts

def worker_batch(accounts, batch_size, start_dt, total_secs):
    """Generates a batch of rows in memory and inserts into RDS."""
    rows = []
    for _ in range(batch_size):
        t_id = str(uuid.uuid4())
        acc = random.choice(accounts)
        dt = start_dt + timedelta(seconds=random.randint(0, total_secs))
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        ttype = "debit" if random.random() < 0.75 else "credit"
        amt = round(random.uniform(500, 85000), 2)
        desc = random.choice(DESCRIPTIONS)
        ref = f"REF{random.randint(1000000000, 9999999999)}"
        rows.append((t_id, acc[0], acc[1], acc[2], dt_str, ttype, amt, desc, ref, UTR_HASH))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT IGNORE INTO transaction (
                    transaction_id, account_id, entity_id, program_id,
                    transaction_date, transaction_type, transaction_amount,
                    description, transaction_reference_id, utr_number
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, rows)
    finally:
        conn.close()
    return len(rows)

def seed_database(total_to_insert=2000000, batch_size=5000, max_workers=4):
    accounts = fetch_accounts()
    if not accounts:
        print("Error: No accounts found in RDS database!")
        return

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM transaction;")
        initial_count = cur.fetchone()[0]
    conn.close()

    print(f"==================================================")
    print(f"🚀 TBX FinOps High-Speed RDS Transaction Seeder")
    print(f"Target Additions: {total_to_insert:,} rows")
    print(f"Current RDS Rows: {initial_count:,}")
    print(f"Expected Final:   {initial_count + total_to_insert:,}")
    print(f"Workers: {max_workers} threads | Batch Size: {batch_size:,}")
    print(f"==================================================")

    start_dt = datetime(2025, 10, 1)
    total_secs = int((datetime(2026, 6, 24) - start_dt).total_seconds())

    inserted_so_far = 0
    start_time = time.time()
    last_log_time = start_time
    last_inserted_checkpoint = 0

    total_batches = (total_to_insert + batch_size - 1) // batch_size

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit batches in chunks
        chunk_futures = []
        batch_count = 0

        while chunk_futures or batch_count < total_batches:
            # Keep queue filled with 2x workers tasks
            while len(chunk_futures) < max_workers * 2 and batch_count < total_batches:
                remaining = total_to_insert - (batch_count * batch_size)
                cur_batch_size = min(batch_size, remaining)
                f = executor.submit(worker_batch, accounts, cur_batch_size, start_dt, total_secs)
                chunk_futures.append(f)
                batch_count += 1

            # Wait for at least one future to complete
            done = [f for f in chunk_futures if f.done()]
            if not done:
                time.sleep(0.05)
                continue

            for f in done:
                chunk_futures.remove(f)
                try:
                    count = f.result()
                    inserted_so_far += count
                except Exception as e:
                    print(f"Batch warning: {e}")

            now = time.time()
            if now - last_log_time >= 5.0 or inserted_so_far >= total_to_insert:
                delta_rows = inserted_so_far - last_inserted_checkpoint
                delta_time = now - last_log_time
                rate = delta_rows / delta_time if delta_time > 0 else 0.0
                pct = (inserted_so_far / total_to_insert) * 100
                total_elapsed = now - start_time
                rem_rows = total_to_insert - inserted_so_far
                rem_time = rem_rows / rate if rate > 0 else 0.0

                print(f"[{pct:5.1f}%] Inserted: {inserted_so_far:9,}/{total_to_insert:,} | Speed: {rate:5.0f} rows/s | ETA: {rem_time/60:4.1f}m | Total in RDS: {initial_count + inserted_so_far:,}", flush=True)
                last_log_time = now
                last_inserted_checkpoint = inserted_so_far

    total_time = time.time() - start_time
    avg_speed = inserted_so_far / total_time if total_time > 0 else 0

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM transaction;")
        final_count = cur.fetchone()[0]
    conn.close()

    print(f"\n==================================================", flush=True)
    print(f"✅ Ingestion Complete!", flush=True)
    print(f"Total Rows Added: {inserted_so_far:,}", flush=True)
    print(f"Final Count in RDS: {final_count:,}", flush=True)
    print(f"Total Time: {total_time/60:.2f} minutes ({avg_speed:.0f} rows/sec)", flush=True)
    print(f"==================================================", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="High-Speed RDS Transaction Seeder")
    parser.add_argument("--count", type=int, default=2000000, help="Number of records to add (default: 2,000,000)")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch size per INSERT (default: 5,000)")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads (default: 4)")
    args = parser.parse_args()

    seed_database(total_to_insert=args.count, batch_size=args.batch_size, max_workers=args.workers)
