import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine


load_dotenv()


def _get_env(*names, default=None):
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip() != "":
            return value
    return default


def get_database_url():
    """
    SQLAlchemy DB URL 생성 함수.

    우선순위:
    1. DATABASE_URL이 있으면 그대로 사용
    2. POSTGRES_* 환경변수 사용
    3. DB_* 환경변수 사용

    기존 로컬 Docker 환경과 Neon 환경을 모두 지원한다.
    """

    database_url = _get_env("DATABASE_URL")
    if database_url:
        return database_url

    host = _get_env("POSTGRES_HOST", "DB_HOST", default="localhost")
    port = _get_env("POSTGRES_PORT", "DB_PORT", default="5432")
    dbname = _get_env("POSTGRES_DB", "DB_NAME", default="silson_legal_db")
    user = _get_env("POSTGRES_USER", "DB_USER", default="silson")
    password = _get_env("POSTGRES_PASSWORD", "DB_PASSWORD", default="silson_pw")
    sslmode = _get_env("POSTGRES_SSLMODE", "DB_SSLMODE", default="prefer")

    try:
        int(port)
    except ValueError:
        raise ValueError(
            f"Invalid DB port: {port}. "
            "Check POSTGRES_PORT or DB_PORT in .env / GitHub Secrets."
        )

    user_q = quote_plus(user)
    password_q = quote_plus(password)

    return (
        f"postgresql+psycopg2://{user_q}:{password_q}"
        f"@{host}:{port}/{dbname}?sslmode={sslmode}"
    )


def get_engine():
    url = get_database_url()
    return create_engine(url)