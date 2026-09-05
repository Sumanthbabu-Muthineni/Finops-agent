"""
Official TBX Database Schema Dataset Generator
Generates:
1. data/bank.csv
2. data/account.csv
3. data/transaction.csv

Includes the exact 10 canonical sample rows from 'TBX - Database Schema.md'
plus rich, multi-month transactions (2025-2026) across all 10 banks and programs,
with intentional IQR statistical anomalies for testing and demonstration.
"""

import os
import csv
import random
import uuid
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Official Sample Banks from TBX - Database Schema.md
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

# Official Sample Accounts from TBX - Database Schema.md
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
    # Additional accounts so all 10 banks are covered
    ("a0000010-0000-0000-0000-000000000010", "f2f5e332-c2d1-4555-9a6b-65c7cd195077", "10100123456789", 21, 5420190.50, "AUBL"),
    ("a0000011-0000-0000-0000-000000000011", "2d52dda2-d98a-4381-af80-45bdb173860c", "10200123456789", 4, 12890450.00, "TMBL"),
    ("a0000012-0000-0000-0000-000000000012", "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "10300123456789", 46, 45200310.25, "RATN"),
]

# Official Sample Transactions from TBX - Database Schema.md
SAMPLE_TRANSACTIONS = [
    ("001cb576-eb28-44b1-a219-0f3f27093fad", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 18:24:06.000000", "debit",  "FT -  95842568 -  50200013729069 - SELECTION ELECTRONICS   DAHISAR EAST",  14866.00,  "1715499972", "jhI5nAdyb1qOEjmcB3JvWjC6tTO+ZPVqBFPm/GiErC4TRBWRQ5ylPG3p"),
    ("0021433a-8d92-40e9-b811-5ba994747975", "6f306737-dfa8-4bf7-8003-be64034b8dea", "2026-05-14 11:31:37.000000", "debit",  "UPI-NAVYUG SELECTION-XXXXXX8672-AUBL0002125-103293775381-260514201735136",      50000.00,  "103293775381", "jhI5nAdyb1qOEjmcB3JvWjC9tzSzbvtkBlK+NSqsiL164ZK8Bl8cYg8y1l8="),
    ("00baf475-8710-4d17-b626-d25fc311eb7f", "5cecd2c2-f075-4bbd-a08b-b156ca48dc7e", "2025-12-16 18:13:34.000000", "credit", "R/RATNR52025121600100235/ZBFLCTP405PBL15667333//SELECTRICITY TWO PRIVATE LIMITED/RATNR52025121600100235 /SELECTRICITY TWO PRIVATE LIMITED", 260000.00, "S31125841", ""),
    ("014b7179-e696-4837-9b8e-7164d171b760", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 06:39:10.000000", "debit",  "NEFT  - UTIB0002678 - 95604250 - 915020031685136 - UMANG SELECTIONHAPURBPES DPF10129", 7959.00, "HDFCH01078329532", "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhmQqR0EoF/PNGRDCa1+UTH2I/tV"),
    ("000000ac-39c5-4eb3-9fe3-ed40ceecee5d", "e984c75d-aad6-4655-823a-4e9e06a869bc", "2025-12-03 16:24:54.000000", "debit",  "NEFT/000483399203/ICIC/PARESH VIKRANT GHASE",                                               9241.00,  "S5314253",  ""),
    ("04818df6-e726-4405-a8e3-4f6c15caa956", "e767c3c1-3a0d-43b5-b2ff-06f49bdf3de2", "2026-01-02 09:58:41.000000", "credit", "IMPS/P2A/600228462725/UTIB/918020101986700/00/INET/9211/SELECTIONMALIGAI/ZBFLCTP5L2PBL11476675/INWD48", 36810.00, "S69244711", ""),
    ("0178b656-4a7d-98e8-9540f6e24caf", "ac1a0654-461b-4216-95d1-bbcb9ab6da4e", "2026-03-17 14:53:45.000000", "debit",  "IMPS OW/507614422198/Gautam singh/SBIN/43292707719",                                          110.00,   "",          ""),
    ("0266384b-929c-478d-a7da-a54acf984343", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 06:30:27.000000", "debit",  "NEFT  - ICIC0001241 - 95584112 - 124105002702 - SELECTION MOBILE",                             66899.00,  "HDFCH01078324740", "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1NhSSrh+QRpxgqe0VEdKaiI24S8Up"),
    ("02c96198-4397-4160-b5ce-607f6696f581", "acfbe204-7541-492c-a352-040aa984bedc", "2026-06-24 06:56:01.000000", "debit",  "NEFT  - ICIC0001241 - 95600270 - 124105002702 - SELECTION MOBILE",                             79575.00,  "HDFCH01078342174", "jhI5nAdyb1qOEjmcB3JvWknJwkXCbf1jBFm1MBKUrRvYyGUaTtHlT1wi23x31CRl"),
    ("038969bd-5941-4d13-ba9f-dda911cc0b4e", "6f306737-dfa8-4bf7-8003-be64034b8dea", "2026-05-20 09:49:02.000000", "debit",  "FT-RERELI2010000810-RELIANCEDIGITAL RETAIL LTD   SELECT CITY SAKET DELHI",                     21156.00,  "1643797818", "jhI5nAdyb1qOEjmcB3JvWjC7sDW9ZPtrAllbY+gS/wWLLijTRu8nX6op"),
]

def generate_tbx_datasets(seed=42):
    random.seed(seed)
    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Write bank.csv
    bank_path = os.path.join(DATA_DIR, "bank.csv")
    with open(bank_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["bank_code", "bank_name"])
        writer.writerows(SAMPLE_BANKS)
    print(f"Generated: {bank_path} ({len(SAMPLE_BANKS)} banks)")

    # 2. Write account.csv
    account_path = os.path.join(DATA_DIR, "account.csv")
    with open(account_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["account_id", "entity_id", "account_number", "program_id", "available_balance", "bank_code"])
        writer.writerows(SAMPLE_ACCOUNTS)
    print(f"Generated: {account_path} ({len(SAMPLE_ACCOUNTS)} accounts)")

    # 3. Generate transaction.csv
    # Start with the official 10 sample transactions
    transactions = list(SAMPLE_TRANSACTIONS)

    # Generate additional multi-month transactions across 2025-2026
    start_dt = datetime(2025, 10, 1, 9, 0, 0)
    end_dt = datetime(2026, 6, 24, 23, 59, 59)
    days_span = (end_dt - start_dt).days

    account_ids = [acc[0] for acc in SAMPLE_ACCOUNTS]
    descriptions_templates = [
        ("credit", "Disbursement / ZBFLCTP / SELECTRICITY TWO PVT LTD"),
        ("credit", "Cheque Deposit - Clearing Account"),
        ("credit", "IMPS Inward / Customer Collections / INET"),
        ("credit", "NEFT Inflow / SELECTION MALIGAI Vendor Settlement"),
        ("debit", "FT - Vendor Settlement - SELECTION ELECTRONICS"),
        ("debit", "UPI-NAVYUG SELECTION Retail Payment"),
        ("debit", "NEFT - Operating Expenses - Office Lease"),
        ("debit", "IMPS OW - Vendor Wire Settlement"),
        ("debit", "Payment to Cloud Infrastructure Services"),
        ("debit", "Statutory Tax Payment / GST Portal Settlement"),
    ]

    ref_counter = 5000000000
    for day_offset in range(0, days_span, 2):
        cur_day = start_dt + timedelta(days=day_offset)
        # Generate 1 to 4 transactions on this day
        num_txns = random.randint(1, 4)
        for _ in range(num_txns):
            t_id = str(uuid.uuid4())
            acc_id = random.choice(account_ids)
            t_hour = random.randint(8, 20)
            t_min = random.randint(0, 59)
            t_sec = random.randint(0, 59)
            t_dt = cur_day.replace(hour=t_hour, minute=t_min, second=t_sec)
            t_str = t_dt.strftime("%Y-%m-%d %H:%M:%S.000000")

            t_type, desc = random.choice(descriptions_templates)
            
            # Typical amounts: normal baseline $1,000 to $95,000
            if random.random() < 0.65:
                amount = round(random.uniform(2500.0, 48000.0), 2)
            else:
                amount = round(random.uniform(50000.0, 150000.0), 2)

            ref_id = f"REF{ref_counter}"
            ref_counter += 1
            utr = f"jhI5nAdyb1qOEjmcB3Jv{random.randint(100000, 999999)}"

            transactions.append((t_id, acc_id, t_str, t_type, desc, amount, ref_id, utr))

    # Add 2 intentional statistical outliers for IQR anomaly detection (bonus requirement!)
    outlier_dt_1 = "2026-06-15 14:20:00.000000"
    transactions.append((
        str(uuid.uuid4()),
        "acfbe204-7541-492c-a352-040aa984bedc", # HDFC account
        outlier_dt_1,
        "debit",
        "EMERGENCY SPECIAL DIVIDEND / CAPITAL EXPENDITURE OUTLIER",
        1850000.00, # Massive outlier compared to typical <=150,000
        "OUTLIER-DEBIT-999",
        "jhI5nAdyb1qOEjmcB3JvOUTLIER1"
    ))

    outlier_dt_2 = "2026-04-10 11:00:00.000000"
    transactions.append((
        str(uuid.uuid4()),
        "34448e78-c3fe-4b5d-be8c-a45a6349b8d4", # UTIB account
        outlier_dt_2,
        "credit",
        "STRATEGIC EQUITY INFUSION INFLOW OUTLIER",
        3500000.00, # Massive credit outlier
        "OUTLIER-CREDIT-888",
        "jhI5nAdyb1qOEjmcB3JvOUTLIER2"
    ))

    # Sort transactions by date
    transactions.sort(key=lambda x: x[2])

    txn_path = os.path.join(DATA_DIR, "transaction.csv")
    with open(txn_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "transaction_id", "account_id", "transaction_date", "transaction_type",
            "description", "transaction_amount", "transaction_reference_id", "utr_number"
        ])
        writer.writerows(transactions)
    print(f"Generated: {txn_path} ({len(transactions)} transactions)")

if __name__ == "__main__":
    generate_tbx_datasets()
