import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

DUMP_PATH = Path("silson_legal_cloud_dump.sql")

DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_SSLMODE = os.getenv("POSTGRES_SSLMODE", "require")


def require_env(name, value):
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")


def main():
    require_env("POSTGRES_HOST", DB_HOST)
    require_env("POSTGRES_DB", DB_NAME)
    require_env("POSTGRES_USER", DB_USER)
    require_env("POSTGRES_PASSWORD", DB_PASSWORD)

    if not DUMP_PATH.exists():
        raise FileNotFoundError(f"Dump file not found: {DUMP_PATH}")

    if DUMP_PATH.stat().st_size == 0:
        raise RuntimeError(f"Dump file is empty: {DUMP_PATH}")

    print("[INFO] restore target host:", DB_HOST)
    print("[INFO] restore target db:", DB_NAME)
    print("[INFO] restore target user:", DB_USER)
    print("[INFO] dump file:", DUMP_PATH)
    print("[INFO] password is loaded from .env and will not be printed.")

    connection_url = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSLMODE}"
    )

    cmd = [
        "docker",
        "exec",
        "-i",
        "silson_legal_postgres",
        "psql",
        connection_url,
    ]

    with DUMP_PATH.open("rb") as dump_file:
        result = subprocess.run(
            cmd,
            stdin=dump_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    if stdout.strip():
        print("[STDOUT]")
        print(stdout[-5000:])

    if stderr.strip():
        print("[STDERR]")
        print(stderr[-5000:])

    if result.returncode != 0:
        raise RuntimeError(f"Restore failed with exit code {result.returncode}")

    print("[SUCCESS] dump restored to Neon successfully.")


if __name__ == "__main__":
    main()