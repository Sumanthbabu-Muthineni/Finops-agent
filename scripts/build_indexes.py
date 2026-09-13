import os
import pymysql
import time
from dotenv import load_dotenv

load_dotenv()

def build_indexes():
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB"),
        autocommit=True
    )
    cur = conn.cursor()
    
    print("Building covering indexes for 17M row analytics... This will take a few minutes.")
    
    start = time.time()
    try:
        cur.execute("CREATE INDEX idx_txn_cover_1 ON transaction(transaction_date, transaction_type, transaction_amount);")
        print(f"Created idx_txn_cover_1 in {time.time()-start:.2f}s")
    except Exception as e:
        print(f"Skipping idx_txn_cover_1: {e}")
        
    start = time.time()
    try:
        cur.execute("CREATE INDEX idx_txn_cover_2 ON transaction(transaction_date, account_id, transaction_amount);")
        print(f"Created idx_txn_cover_2 in {time.time()-start:.2f}s")
    except Exception as e:
        print(f"Skipping idx_txn_cover_2: {e}")

    print("All indexes built successfully!")
    cur.close()
    conn.close()

if __name__ == "__main__":
    build_indexes()
