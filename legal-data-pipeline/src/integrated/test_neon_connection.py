import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT", "5432"),
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    sslmode=os.getenv("POSTGRES_SSLMODE", "require"),
)

with conn.cursor() as cur:
    cur.execute("SELECT version();")
    print(cur.fetchone()[0])

conn.close()
print("[SUCCESS] Neon connection OK")