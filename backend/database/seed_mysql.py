"""
TBX FinOps Assistant - MySQL Bulk Seeder
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import io
import csv
import random
import uuid
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

import pymysql
from backend.core.crypto import encrypt_utr

# MySQL connection parameters loaded strictly from .env
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = int(os.getenv("MYSQL_PORT", 3306))
DB_USER = os.getenv("MYSQL_USER")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD")
DB_NAME = os.getenv("MYSQL_DB")

SAMPLE_BANKS = [
    ("HDFC", "HDFC BANK LIMITED"),
    ("ICIC", "ICICI BANK LIMITED"),
    ("SBIN", "STATE BANK OF INDIA"),
    ("UTIB", "AXIS BANK LIMITED"),
    ("KKBK", "KOTAK MAHINDRA BANK LIMITED"),
    ("CNRB", "CANARA BANK"),
    ("UBIN", "UNION BANK OF INDIA"),
    ("AUBL", "AU SMALL FINANCE BANK LIMITED"),
    ("TMBL", "TAMILNAD MERCANTILE BANK LIMITED"),
    ("RATN", "RBL BANK LIMITED"),
]

SAMPLE_ACCOUNTS = [
    ("acfbe204-7541-492c-a352-040aa984bedc", "f2f5e332-c2d1-4555-9a6b-65c7cd195077", "50200013729069", 21, -25907487.00, "HDFC"),
    ("6f306737-dfa8-4bf7-8003-be64034b8dea", "2d52dda2-d98a-4381-af80-45bdb173860c", "50200099284137", 21, -94766029.00, "HDFC"),
    ("bfbfe347-11d6-48d7-acff-4f091f59d34b", "e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2", "39208809622308", 4, 40842693.08, "UBIN"),
    ("212239b5-63d9-4da6-aa8c-46485e0f8a42", "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "30123456789012", 46, 109283.80, "SBIN"),
    ("34448e78-c3fe-4b5d-be8c-a45a6349b8d4", "e984c75d-aad6-4655-823a-4e9e06a869bc", "40100556677889", 21, 231680596.77, "UTIB"),
    ("5cecd2c2-f075-4bbd-a08b-b156ca48dc7e", "e0000005-0000-0000-0000-000000000005", "60100112233445", 4, -131629423.33, "HDFC"),
    ("e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2", "00000006-0000-0000-0000-000000000006", "70100334455667", 21, 8695000.75, "KKBK"),
    ("2d52dda2-d98a-4381-af80-45bdb173860c", "00000007-0000-0000-0000-000000000007", "80100123456789", 46, 3887946.81, "CNRB"),
    ("ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "00000008-0000-0000-0000-000000000008", "90100987654321", 21, 3278516.63, "SBIN"),
    ("e984c75d-aad6-4655-823a-4e9e06a869bc", "00000009-0000-0000-0000-000000000009", "20100556677889", 46, -117420771.35, "ICIC"),
    ("a0000010-0000-0000-0000-000000000010", "f2f5e332-c2d1-4555-9a6b-65c7cd195077", "10100123456789", 21, 5420190.50, "AUBL"),
    ("a0000011-0000-0000-0000-000000000011", "2d52dda2-d98a-4381-af80-45bdb173860c", "10200123456789", 4, 12890450.00, "TMBL"),
    ("a0000012-0000-0000-0000-000000000012", "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "10300123456789", 46, 45200310.25, "RATN"),
]

SAMPLE_TRANSACTIONS = [
    ("001cb576-eb28-44b1-a219-0f3f27093fad", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 18:24:06", "debit",  "FT -  95842568 -  50200013729069 - SELECTION ELECTRONICS   DAHISAR EAST",  14866.00,  "1715499972", "jhI5nAdyb1qOEjmcB3JvWjC6tTO+ZPVqBFPm/GiErC4TRBWRQ5ylPG3p"),
    ("0021433a-8d92-40e9-b811-5ba994747975", "6f306737-dfa8-4bf7-8003-be64034b8dea", "2026-05-14 11:31:37", "debit",  "UPI-NAVYUG SELECTION-XXXXXX8672-AUBL0002125-103293775381-260514201735136",      50000.00,  "103293775381", "jhI5nAdyb1qOEjmcB3JvWjC9tzSzbvtkBlK+NSqsiL164ZK8Bl8cYg8y1l8="),
    ("00baf475-8710-4d17-b626-d25fc311eb7f", "5cecd2c2-f075-4bbd-a08b-b156ca48dc7e", "2025-12-16 18:13:34", "credit", "R/RATNR52025121600100235/ZBFLCTP405PBL15667333//SELECTRICITY TWO PRIVATE LIMITED", 260000.00, "S31125841", ""),
    ("014b7179-e696-4837-9b8e-7164d171b760", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 06:39:10", "debit",  "NEFT  - UTIB0002678 - 95604250 - 915020031685136 - UMANG SELECTIONHAPURBPES", 7959.00, "HDFCH01078329532", "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhmQqR0EoF/PNGRDCa1+UTH2I/tV"),
    ("000000ac-39c5-4eb3-9fe3-ed40ceecee5d", "e984c75d-aad6-4655-823a-4e9e06a869bc", "2025-12-03 16:24:54", "debit",  "NEFT/000483399203/ICIC/PARESH VIKRANT GHASE",                                               9241.00,  "S5314253",  ""),
    ("04818df6-e726-4405-a8e3-4f6c15caa956", "e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2", "2026-01-02 09:58:41", "credit", "IMPS/P2A/600228462725/UTIB/918020101986700/00/INET/9211/SELECTIONMALIGAI", 36810.00, "S69244711", ""),
    ("0034a742-dfae-42b7-8ce6-a79ee07908b8", "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "2026-04-16 11:29:16", "debit",  "NEFT -  000474620027 -  SELECTION ENTERPRISES",                                             10000.00, "S19028059", ""),
    ("0266384b-929c-478d-a7da-a54acf984343", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 06:30:27", "debit",  "NEFT  - ICIC0001241 - 95584112 - 124105002702 - SELECTION MOBILE",                          66899.00, "HDFCH01078324740", "jhI5nAdyb1qOEjmcB3JvWvXv2gL55O04cM4aR4pE0x+Q1u7xI/x8="),
    ("02c96198-4397-4160-b5ce-607f6696f581", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 06:56:01", "debit",  "NEFT  - ICIC0001241 - 95600270 - 124105002702 - SELECTION MOBILE",                          79575.00, "HDFCH01078342174", "jhI5nAdyb1qOEjmcB3JvWj6pQx1Z1s3gVw9k6Xl2O3c5="),
    ("02f5a653-535d-4a1e-b816-b8449feee15f", "34448e78-c3fe-4b5d-be8c-a45a6349b8d4", "2026-06-03 14:14:50", "debit",  "NACH/000000000028268670/02-06-2026/BAJAJ FINAN",                                           21937.63, "1713502844", ""),
]

def seed_database(scale_count: int = 10000):
    print(f"🚀 Connecting to MySQL at {DB_HOST}:{DB_PORT}...")
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True
    )
    cur = conn.cursor()

    t_start = time.time()

    print("1. Seeding banks...")
    cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
    cur.execute("TRUNCATE TABLE transaction;")
    cur.execute("TRUNCATE TABLE account;")
    cur.execute("TRUNCATE TABLE bank;")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
    
    cur.executemany(
        "INSERT IGNORE INTO bank (bank_code, bank_name) VALUES (%s, %s)", 
        SAMPLE_BANKS
    )

    print("2. Seeding accounts...")
    acc_rows = []
    for a in SAMPLE_ACCOUNTS:
        acc_rows.append((a[0], a[1], a[2], a[5], a[3], a[4]))
    cur.executemany("""
        INSERT IGNORE INTO account (account_id, entity_id, account_number, bank_code, program_id, available_balance)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, acc_rows)

    account_lookup = {a[0]: {"entity_id": a[1], "program_id": a[3]} for a in SAMPLE_ACCOUNTS}
    account_ids = list(account_lookup.keys())

    print("3. Inserting official canonical sample transactions...")
    canon_rows = []
    for t in SAMPLE_TRANSACTIONS:
        acc_id = t[1]
        acc_meta = account_lookup.get(acc_id, {"entity_id": str(uuid.uuid4()), "program_id": 21})
        encrypted_utr = encrypt_utr(t[7]) if t[7] else ""
        canon_rows.append((
            t[0], acc_id, acc_meta["entity_id"], acc_meta["program_id"],
            t[2], t[3], t[5], t[4], t[6], encrypted_utr
        ))
    cur.executemany("""
        INSERT INTO transaction (transaction_id, account_id, entity_id, program_id, transaction_date, transaction_type, transaction_amount, description, transaction_reference_id, utr_number)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, canon_rows)

    print(f"4. Bulk inserting {scale_count:,} realistic multi-month transactions...")
    
    start_dt = datetime(2025, 10, 1)
    end_dt = datetime(2026, 6, 24, 18, 0, 0)
    total_seconds = int((end_dt - start_dt).total_seconds())

    descriptions = [
        "FT - Vendor Settlement - SELECTION ELECTRONICS",
        "UPI-NAVYUG SELECTION Retail Payment",
        "NEFT Inflow / SELECTION MALIGAI Vendor Settlement",
        "Payment to Cloud Infrastructure Services",
        "IMPS Settlement - Corporate Vendor Disbursements",
        "NEFT - Operating Expenses - Office Lease",
        "Vendor Payout - IT Support & Maintenance",
        "Direct Deposit - Payroll Settlement"
    ]

    random.seed(42)
    bulk_rows = []
    for i in range(scale_count):
        t_id = str(uuid.uuid4())
        acc_id = random.choice(account_ids)
        meta = account_lookup[acc_id]
        dt = start_dt + timedelta(seconds=random.randint(0, total_seconds))
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        if i == 42:
            txn_type = "debit"
            amt = 1850000.00
            desc = "SPECIAL ACQUISITION ESCROW / SELECTION EQUITY TRANSFER"
            dt_str = "2026-06-15 14:20:00"
        elif i == 108:
            txn_type = "debit"
            amt = 950000.00
            desc = "EXECUTIVE BONUS ADVANCE / WIRE DISBURSEMENT"
            dt_str = "2026-06-18 10:15:00"
        else:
            txn_type = random.choices(["debit", "credit"], weights=[0.75, 0.25])[0]
            amt = round(random.lognormvariate(10.2, 0.7), 2)
            desc = random.choice(descriptions)

        ref_id = f"REF{5000000000 + i}"
        raw_utr = f"jhI5nAdy{random.randint(100000, 999999)}"
        encrypted_utr = encrypt_utr(raw_utr)

        bulk_rows.append((
            t_id, acc_id, meta["entity_id"], meta["program_id"],
            dt_str, txn_type, amt, desc, ref_id, encrypted_utr
        ))

        # Batch insert every 5000 rows
        if len(bulk_rows) >= 5000:
            cur.executemany("""
                INSERT INTO transaction (transaction_id, account_id, entity_id, program_id, transaction_date, transaction_type, transaction_amount, description, transaction_reference_id, utr_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, bulk_rows)
            bulk_rows = []

    if bulk_rows:
        cur.executemany("""
            INSERT INTO transaction (transaction_id, account_id, entity_id, program_id, transaction_date, transaction_type, transaction_amount, description, transaction_reference_id, utr_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, bulk_rows)

    elapsed = round(time.time() - t_start, 2)

    cur.execute("SELECT COUNT(*) FROM transaction;")
    total_txns = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM account;")
    total_accs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bank;")
    total_banks = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"🎉 MySQL Seeding Completed in {elapsed}s!")
    print(f"   • Banks:        {total_banks}")
    print(f"   • Accounts:     {total_accs}")
    print(f"   • Transactions: {total_txns:,}")

if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 25000
    seed_database(count)
