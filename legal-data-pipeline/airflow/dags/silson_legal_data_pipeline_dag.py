from datetime import datetime, timedelta
import subprocess
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator


PROJECT_ROOT = Path("/opt/airflow/project")


def run_script(script_path: str):
    full_path = PROJECT_ROOT / script_path

    result = subprocess.run(
        ["python", str(full_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"Script failed: {script_path}\n"
            f"returncode={result.returncode}\n"
            f"stderr={result.stderr}"
        )


default_args = {
    "owner": "silson-c-legal-data",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="silson_legal_api_refresh_pipeline",
    description="국가법령정보 API 기반 법률·규제 데이터의 주기적 수집·갱신 파이프라인",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 3 * * 1",
    catchup=False,
    tags=["silson", "legal", "api", "regulation", "rag"],
) as dag:

    check_db_connection = PythonOperator(
        task_id="check_db_connection",
        python_callable=run_script,
        op_kwargs={"script_path": "src/test_db_connection.py"},
    )

    load_inventory = PythonOperator(
        task_id="load_inventory",
        python_callable=run_script,
        op_kwargs={"script_path": "src/load_inventory.py"},
    )

    fix_inventory_status = PythonOperator(
        task_id="fix_inventory_status",
        python_callable=run_script,
        op_kwargs={"script_path": "src/fix_inventory_status.py"},
    )

    collect_legal_api = PythonOperator(
        task_id="collect_legal_api",
        python_callable=run_script,
        op_kwargs={"script_path": "src/collect_legal_api.py"},
    )

    collect_legal_body = PythonOperator(
        task_id="collect_legal_body",
        python_callable=run_script,
        op_kwargs={"script_path": "src/collect_legal_body.py"},
    )

    parse_external_docs = PythonOperator(
        task_id="parse_external_docs",
        python_callable=run_script,
        op_kwargs={"script_path": "src/parse_external_docs.py"},
    )

    build_retrieval_registry = PythonOperator(
        task_id="build_retrieval_registry",
        python_callable=run_script,
        op_kwargs={"script_path": "src/build_retrieval_registry.py"},
    )

    seed_risk_query_expansion = PythonOperator(
        task_id="seed_risk_query_expansion",
        python_callable=run_script,
        op_kwargs={"script_path": "src/seed_risk_query_expansion.py"},
    )

    (
        check_db_connection
        >> load_inventory
        >> fix_inventory_status
        >> collect_legal_api
        >> collect_legal_body
        >> parse_external_docs
        >> build_retrieval_registry
        >> seed_risk_query_expansion
    )